from __future__ import annotations

import sqlite3
import os
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .content import parse_message_content
from .delivery_schema import SCHEMA_VERSION, execute_script, migrate_delivery
from .platforms.windows_security import apply_current_user_acl, reject_private_links

WINDOWS = os.name == 'nt'


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL UNIQUE,
    chat_name TEXT NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text',
    source_time TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    is_at_me INTEGER NOT NULL DEFAULT 0,
    matched_rules_json TEXT NOT NULL DEFAULT '[]',
    source_kind TEXT NOT NULL DEFAULT 'decoder',
    content_kind TEXT NOT NULL DEFAULT 'text',
    content_text TEXT NOT NULL DEFAULT '',
    quote_sender TEXT NOT NULL DEFAULT '',
    quote_content TEXT NOT NULL DEFAULT '',
    quote_kind TEXT NOT NULL DEFAULT '',
    raw_content TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(source_time DESC);
CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_name, source_time DESC);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','ignored')),
    confidence REAL NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_key TEXT NOT NULL UNIQUE,
    report_date TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    content TEXT NOT NULL,
    question_count INTEGER NOT NULL,
    confirmed_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    groups_json TEXT NOT NULL,
    self_names_json TEXT NOT NULL,
    target_names_json TEXT NOT NULL DEFAULT '[]',
    keywords_json TEXT NOT NULL,
    require_at_me INTEGER NOT NULL DEFAULT 0,
    retention_days INTEGER NOT NULL DEFAULT 7,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS listener_state (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    state TEXT NOT NULL,
    detail TEXT NOT NULL,
    last_probe_at TEXT,
    last_wal_activity_at TEXT,
    last_decode_at TEXT,
    wal_event_count INTEGER NOT NULL DEFAULT 0,
    decode_error_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_history_sync (
    group_name TEXT PRIMARY KEY,
    imported_at TEXT NOT NULL,
    source_message_count INTEGER NOT NULL DEFAULT 0,
    inserted_message_count INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: Path):
        if WINDOWS:
            reject_private_links(path.absolute())
        self.path = path.resolve()

    def initialize(self) -> None:
        if WINDOWS:
            reject_private_links(self.path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if WINDOWS:
            apply_current_user_acl(self.path.parent)
            for existing in (self.path, Path(str(self.path)+'-wal'), Path(str(self.path)+'-shm')):
                reject_private_links(existing)
                if existing.exists():
                    apply_current_user_acl(existing)
        if self.path.exists() and self.path.stat().st_size:
            with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as source:
                version = source.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise RuntimeError("数据库版本高于程序版本，请使用较新程序")
                if version < SCHEMA_VERSION:
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                    backup = self.path.parent / "backups" / f"{self.path.stem}-before-v{SCHEMA_VERSION}-{stamp}.db"
                    if WINDOWS:
                        reject_private_links(backup)
                    backup.parent.mkdir(mode=0o700, exist_ok=True)
                    if WINDOWS:
                        apply_current_user_acl(backup.parent)
                        backup.touch(exist_ok=False)
                        apply_current_user_acl(backup)
                    else:
                        backup.parent.chmod(0o700)
                    with sqlite3.connect(backup) as target:
                        source.backup(target)
                    if not WINDOWS:
                        backup.chmod(0o600)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            execute_script(conn, SCHEMA)
            setting_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()
            }
            if "target_names_json" not in setting_columns:
                conn.execute(
                    "ALTER TABLE settings ADD COLUMN target_names_json TEXT NOT NULL DEFAULT '[]'"
                )
            message_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()
            }
            message_column_defaults = {
                "content_kind": "TEXT NOT NULL DEFAULT 'text'",
                "content_text": "TEXT NOT NULL DEFAULT ''",
                "quote_sender": "TEXT NOT NULL DEFAULT ''",
                "quote_content": "TEXT NOT NULL DEFAULT ''",
                "quote_kind": "TEXT NOT NULL DEFAULT ''",
                "raw_content": "TEXT NOT NULL DEFAULT ''",
            }
            for name, definition in message_column_defaults.items():
                if name not in message_columns:
                    conn.execute(f"ALTER TABLE messages ADD COLUMN {name} {definition}")
            report_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(reports)").fetchall()
            }
            if "report_key" not in report_columns:
                conn.execute("ALTER TABLE reports RENAME TO reports_legacy")
                execute_script(conn,
                    """
                    CREATE TABLE reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        report_key TEXT NOT NULL UNIQUE,
                        report_date TEXT NOT NULL,
                        period_start TEXT NOT NULL,
                        period_end TEXT NOT NULL,
                        content TEXT NOT NULL,
                        question_count INTEGER NOT NULL,
                        confirmed_count INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO reports(
                        id, report_key, report_date, period_start, period_end, content,
                        question_count, confirmed_count, created_at, updated_at
                    )
                    SELECT id, 'D:' || report_date, report_date, report_date, report_date, content,
                        question_count, confirmed_count, created_at, updated_at
                    FROM reports_legacy;
                    DROP TABLE reports_legacy;
                    """
                )
            rows = conn.execute(
                """
                SELECT id, content, message_type, content_text, raw_content
                FROM messages
                WHERE content_text='' OR raw_content='' OR content LIKE '<?xml%' OR content LIKE '<msg%'
                """
            ).fetchall()
            for row in rows:
                display = parse_message_content(row["content"], row["message_type"])
                conn.execute(
                    """
                    UPDATE messages SET content=?, content_kind=?, content_text=?, quote_sender=?,
                        quote_content=?, quote_kind=?, raw_content=? WHERE id=?
                    """,
                    (
                        display.storage_text,
                        display.kind,
                        display.text,
                        display.quote_sender,
                        display.quote_content,
                        display.quote_kind,
                        row["raw_content"] or row["content"],
                        row["id"],
                    ),
                )
                conn.execute(
                    """
                    UPDATE questions SET title=?
                    WHERE message_id=? AND (title LIKE '<?xml%' OR title LIKE '%<appmsg%')
                    """,
                    (display.text or display.storage_text, row["id"]),
                )

            migrate_delivery(conn)
        if WINDOWS:
            apply_current_user_acl(self.path)
        else:
            self.path.chmod(0o600)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
