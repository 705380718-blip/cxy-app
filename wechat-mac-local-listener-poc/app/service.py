from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import nullcontext
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from .config import Settings
from .content import IMAGE_PLACEHOLDER, normalize_message_content, parse_message_content
from .db import Database
from .extractor import extract
from .models import DecoderMessage, RuleSettingsUpdate


UTC = timezone.utc
CST = timezone(timedelta(hours=8))


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


class ReviewConflict(RuntimeError):
    pass


class OrganizerService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self._ensure_defaults()
        self._refresh_quote_classification()

    def _ensure_defaults(self) -> None:
        now = iso(now_utc())
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO settings(
                    id, groups_json, self_names_json, target_names_json, keywords_json,
                    require_at_me, retention_days, updated_at
                ) VALUES (1, ?, ?, '[]', ?, 0, 7, ?)
                """,
                (
                    json.dumps(self.settings.initial_groups, ensure_ascii=False),
                    json.dumps(self.settings.initial_self_names, ensure_ascii=False),
                    json.dumps(["延期", "风险", "报错", "无法", "投诉"], ensure_ascii=False),
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO listener_state(
                    id, state, detail, wal_event_count, decode_error_count
                ) VALUES (1, 'stopped', '监听服务尚未启动', 0, 0)
                """
            )

    def _refresh_quote_classification(self) -> None:
        """Classify migrated quote messages from their reply text, never from quoted context."""
        rules = self.get_settings()
        now = iso(now_utc())
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT m.id, m.content_text, m.is_at_me, q.id AS question_id
                FROM messages m LEFT JOIN questions q ON q.message_id=m.id
                WHERE m.content_kind='quote'
                """
            ).fetchall()
            for row in rows:
                content = str(row["content_text"] or "").strip()
                at_me = bool(row["is_at_me"]) or any(
                    f"@{name}" in content or f"＠{name}" in content
                    for name in rules["self_names"]
                )
                match = extract(
                    content,
                    tuple(rules["keywords"]),
                    at_me,
                    tuple(rules["target_names"]),
                )
                if rules["require_at_me"] and not at_me:
                    match = None
                conn.execute(
                    "UPDATE messages SET is_at_me=?, matched_rules_json=? WHERE id=?",
                    (
                        int(at_me),
                        json.dumps(match.rules if match else (), ensure_ascii=False),
                        row["id"],
                    ),
                )
                if match and row["question_id"] is None:
                    conn.execute(
                        """
                        INSERT INTO questions(
                            message_id, title, category, confidence, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (row["id"], match.title, match.category, match.confidence, now, now),
                    )

    def get_settings(self) -> dict[str, Any]:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        return {
            "groups": json.loads(row["groups_json"]),
            "self_names": json.loads(row["self_names_json"]),
            "target_names": json.loads(row["target_names_json"]),
            "keywords": json.loads(row["keywords_json"]),
            "require_at_me": bool(row["require_at_me"]),
            "retention_days": row["retention_days"],
            "updated_at": row["updated_at"],
        }

    def update_settings(self, update: RuleSettingsUpdate) -> dict[str, Any]:
        now = iso(now_utc())
        with self.database.connection() as conn:
            conn.execute(
                """
                UPDATE settings SET groups_json=?, self_names_json=?, target_names_json=?, keywords_json=?,
                    require_at_me=?, retention_days=?, updated_at=? WHERE id=1
                """,
                (
                    json.dumps(update.groups, ensure_ascii=False),
                    json.dumps(update.self_names, ensure_ascii=False),
                    json.dumps(update.target_names, ensure_ascii=False),
                    json.dumps(update.keywords, ensure_ascii=False),
                    int(update.require_at_me),
                    update.retention_days,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO audit_log(action, detail_json, created_at) VALUES ('update_rules', ?, ?)",
                (
                    json.dumps(
                        {
                            "groups": len(update.groups),
                            "self_names": len(update.self_names),
                            "target_names": len(update.target_names),
                            "keywords": len(update.keywords),
                        }
                    ),
                    now,
                ),
            )
        self.cleanup_expired(update.retention_days)
        self._refresh_quote_classification()
        return self.get_settings()

    def cleanup_expired(self, retention_days: int | None = None) -> int:
        days = retention_days or int(self.get_settings()["retention_days"])
        cutoff = iso(now_utc() - timedelta(days=days))
        now = iso(now_utc())
        with self.database.connection() as conn:
            expired_ids = {row[0] for row in conn.execute("SELECT id FROM messages WHERE source_time < ?", (cutoff,))}
            if expired_ids:
                affected = {row[0] for row in conn.execute("SELECT DISTINCT e.item_id FROM item_evidence e JOIN messages m ON m.id=e.message_id WHERE m.source_time<?", (cutoff,))}
                for item_id in affected:
                    conn.execute("UPDATE work_items SET title='依据已过期',owner=NULL,due_at=NULL,due_text=NULL,latest_progress=NULL,evidence_expired=1,review_status='ignored',version=version+1,updated_at=? WHERE id=?", (now,item_id))
                    conn.execute("DELETE FROM item_evidence WHERE item_id=?", (item_id,))
                    conn.execute("DELETE FROM item_proposals WHERE target_item_id=?", (item_id,))
                for job in conn.execute("SELECT id,input_message_ids,context_message_ids FROM ai_jobs").fetchall():
                    if expired_ids.intersection(json.loads(job["input_message_ids"])+json.loads(job["context_message_ids"])):
                        conn.execute("DELETE FROM ai_jobs WHERE id=?", (job["id"],))
                conn.execute("DELETE FROM ai_previews")
                conn.execute("DELETE FROM followup_reports")
                conn.execute("DELETE FROM reports")
                conn.execute("DELETE FROM evaluation_runs")
            conn.execute("UPDATE import_batches SET preview_json='[]',error_rows='[]',status='expired' WHERE status='preview' AND created_at<?", (iso(now_utc()-timedelta(hours=24)),))
            cursor = conn.execute("DELETE FROM messages WHERE source_time < ?", (cutoff,))
            deleted = int(cursor.rowcount)
            if deleted:
                conn.execute(
                    "INSERT INTO audit_log(action, detail_json, created_at) VALUES ('retention_cleanup', ?, ?)",
                    (json.dumps({"retention_days": days, "deleted_messages": deleted}), now),
                )
        return deleted

    @staticmethod
    def _source_id(message: DecoderMessage) -> str:
        if message.source_id:
            return message.source_id
        raw = "\x1f".join(
            (
                message.chat_name,
                message.sender,
                message.message_type,
                iso(message.source_time),
                message.content,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def ingest(self, message: DecoderMessage) -> dict[str, Any]:
        return self.ingest_many((message,))["results"][0]

    def ingest_many(self, messages: tuple[DecoderMessage, ...] | list[DecoderMessage], *, connection=None, project_source_id=None, import_batch_id=None) -> dict[str, Any]:
        rules = self.get_settings()
        observed_at = iso(now_utc())
        results: list[dict[str, Any]] = []
        inserted = 0
        duplicates = 0
        question_count = 0
        with (nullcontext(connection) if connection is not None else self.database.connection()) as conn:
            for message in messages:
                if not message.is_group or message.chat_name not in rules["groups"]:
                    results.append({"accepted": False, "reason": "group_not_allowed"})
                    continue
                display = parse_message_content(message.content, message.message_type)
                content = display.storage_text
                match_content = display.text if display.kind == "quote" else content
                at_me = message.is_at_me or any(
                    f"@{name}" in match_content or f"＠{name}" in match_content
                    for name in rules["self_names"]
                )
                is_text_message = (
                    message.message_type.strip().lower() in {"1", "text", "文本"}
                    or display.kind == "quote"
                )
                match = (
                    extract(
                        match_content,
                        tuple(rules["keywords"]),
                        at_me,
                        tuple(rules["target_names"]),
                    )
                    if is_text_message
                    else None
                )
                if rules["require_at_me"] and not at_me:
                    match = None
                bound_source_id = project_source_id
                if bound_source_id is None and message.source_kind in {"decoder", "decoder_history", "mac-decoder", "mac-history", "windows-decoder", "windows-history"}:
                    source = conn.execute("SELECT id FROM project_sources WHERE source_kind='decoder' AND source_key=?", (message.chat_name,)).fetchone()
                    bound_source_id = source["id"] if source else None
                source_id = self._source_id(message)
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO messages(
                        source_id, chat_name, sender, content, message_type, source_time,
                        observed_at, is_at_me, matched_rules_json, source_kind,
                        content_kind, content_text, quote_sender, quote_content, quote_kind,
                        raw_content, project_source_id, import_batch_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        message.chat_name,
                        message.sender,
                        content,
                        message.message_type,
                        iso(message.source_time),
                        observed_at,
                        int(at_me),
                        json.dumps(match.rules if match else (), ensure_ascii=False),
                        message.source_kind,
                        display.kind,
                        display.text,
                        display.quote_sender,
                        display.quote_content,
                        display.quote_kind,
                        message.content,
                        bound_source_id,
                        import_batch_id,
                    ),
                )
                if cursor.rowcount == 0:
                    duplicates += 1
                    results.append({"accepted": True, "duplicate": True, "source_id": source_id})
                    continue
                inserted += 1
                question_id = None
                if match:
                    q = conn.execute(
                        """
                        INSERT INTO questions(
                            message_id, title, category, confidence, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cursor.lastrowid,
                            match.title,
                            match.category,
                            match.confidence,
                            observed_at,
                            observed_at,
                        ),
                    )
                    question_id = q.lastrowid
                    question_count += 1
                results.append(
                    {
                        "accepted": True,
                        "duplicate": False,
                        "source_id": source_id,
                        "question_id": question_id,
                    }
                )
        return {
            "results": results,
            "inserted": inserted,
            "duplicates": duplicates,
            "questions": question_count,
        }

    def pending_history_groups(self, groups: tuple[str, ...]) -> tuple[str, ...]:
        if not groups:
            return ()
        placeholders = ",".join("?" for _ in groups)
        with self.database.connection() as conn:
            rows = conn.execute(
                f"SELECT group_name FROM group_history_sync WHERE group_name IN ({placeholders})",
                groups,
            ).fetchall()
        completed = {str(row["group_name"]) for row in rows}
        return tuple(group for group in groups if group not in completed)

    def mark_history_imported(
        self, group_name: str, source_message_count: int, inserted_message_count: int
    ) -> None:
        imported_at = iso(now_utc())
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO group_history_sync(
                    group_name, imported_at, source_message_count, inserted_message_count
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(group_name) DO UPDATE SET
                    imported_at=excluded.imported_at,
                    source_message_count=excluded.source_message_count,
                    inserted_message_count=excluded.inserted_message_count
                """,
                (group_name, imported_at, source_message_count, inserted_message_count),
            )
            conn.execute(
                "INSERT INTO audit_log(action, detail_json, created_at) VALUES ('history_import', ?, ?)",
                (
                    json.dumps(
                        {
                            "group": group_name,
                            "source_message_count": source_message_count,
                            "inserted_message_count": inserted_message_count,
                        },
                        ensure_ascii=False,
                    ),
                    imported_at,
                ),
            )

    def message_high_water(self, groups: tuple[str, ...]) -> dict[str, int]:
        if not groups:
            return {}
        placeholders = ",".join("?" for _ in groups)
        with self.database.connection() as conn:
            rows = conn.execute(
                f"SELECT chat_name, MAX(source_time) AS source_time FROM messages "
                f"WHERE chat_name IN ({placeholders}) GROUP BY chat_name",
                groups,
            ).fetchall()
        result: dict[str, int] = {}
        for row in rows:
            if row["source_time"]:
                result[str(row["chat_name"])] = int(
                    datetime.fromisoformat(str(row["source_time"])).timestamp()
                )
        return result

    @staticmethod
    def _safe_message_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item.pop("raw_content", None)
        if not item.get("content_text"):
            display = parse_message_content(item["content"], item["message_type"])
            item.update(
                content=display.storage_text,
                content_kind=display.kind,
                content_text=display.text,
                quote_sender=display.quote_sender,
                quote_content=display.quote_content,
                quote_kind=display.quote_kind,
            )
        else:
            item["content"] = normalize_message_content(item["content"], item["message_type"])
        item["is_at_me"] = bool(item["is_at_me"])
        item["matched_rules"] = json.loads(item["matched_rules_json"])
        return item

    def list_messages(self, page: int, page_size: int, search: str = "") -> dict[str, Any]:
        term = search.strip()
        where = ""
        params: list[Any] = []
        if term:
            safe = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where = (
                "WHERE chat_name LIKE ? ESCAPE '\\' OR sender LIKE ? ESCAPE '\\' "
                "OR content LIKE ? ESCAPE '\\'"
            )
            params = [f"%{safe}%"] * 3
        offset = (page - 1) * page_size
        with self.database.connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM messages {where}", params).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT m.*, q.id AS question_id, q.status AS question_status
                FROM messages m LEFT JOIN questions q ON q.message_id=m.id
                {where} ORDER BY m.source_time DESC, m.id DESC LIMIT ? OFFSET ?
                """,
                (*params, page_size, offset),
            ).fetchall()
        pages = max(1, (total + page_size - 1) // page_size)
        return {
            "items": [self._safe_message_row(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "total": total,
        }

    def list_questions(
        self, status: str = "pending", limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT q.*, m.chat_name, m.sender, m.content, m.message_type, m.source_time,
                       m.is_at_me, m.matched_rules_json
                FROM questions q JOIN messages m ON m.id=q.message_id
                WHERE q.status=? ORDER BY q.created_at DESC LIMIT ? OFFSET ?
                """,
                (status, limit, offset),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["content"] = normalize_message_content(item["content"], item["message_type"])
            if item["content"] == IMAGE_PLACEHOLDER:
                item["title"] = IMAGE_PLACEHOLDER
            item["is_at_me"] = bool(item["is_at_me"])
            item["matched_rules"] = json.loads(item["matched_rules_json"])
            items.append(item)
        return items

    def count_questions(self, status: str = "pending") -> int:
        with self.database.connection() as conn:
            return int(
                conn.execute("SELECT COUNT(*) FROM questions WHERE status=?", (status,)).fetchone()[0]
            )

    def review(self, question_id: int, status: str, expected_version: int) -> dict[str, Any] | None:
        now = iso(now_utc())
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE questions SET status=?, version=version+1, updated_at=?
                WHERE id=? AND version=?
                """,
                (status, now, question_id, expected_version),
            )
            if cursor.rowcount == 0:
                exists = conn.execute("SELECT 1 FROM questions WHERE id=?", (question_id,)).fetchone()
                if exists:
                    raise ReviewConflict(question_id)
                return None
            conn.execute(
                "INSERT INTO audit_log(action, detail_json, created_at) VALUES ('review', ?, ?)",
                (json.dumps({"question_id": question_id, "status": status}), now),
            )
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT q.*, m.chat_name, m.sender, m.content, m.message_type, m.source_time,
                       m.is_at_me, m.matched_rules_json
                FROM questions q JOIN messages m ON m.id=q.message_id
                WHERE q.id=?
                """,
                (question_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["content"] = normalize_message_content(item["content"], item["message_type"])
        item["is_at_me"] = bool(item["is_at_me"])
        item["matched_rules"] = json.loads(item["matched_rules_json"])
        return item

    def batch_review(self, items: list[tuple[int, int]], status: str) -> dict[str, Any]:
        now = iso(now_utc())
        updated_ids: list[int] = []
        skipped_ids: list[int] = []
        with self.database.connection() as conn:
            for question_id, expected_version in items:
                cursor = conn.execute(
                    """
                    UPDATE questions SET status=?, version=version+1, updated_at=?
                    WHERE id=? AND status='pending' AND version=?
                    """,
                    (status, now, question_id, expected_version),
                )
                (updated_ids if cursor.rowcount else skipped_ids).append(question_id)
            conn.execute(
                "INSERT INTO audit_log(action, detail_json, created_at) VALUES ('batch_review', ?, ?)",
                (
                    json.dumps(
                        {
                            "status": status,
                            "updated_ids": updated_ids,
                            "skipped_ids": skipped_ids,
                        }
                    ),
                    now,
                ),
            )
        return {
            "status": status,
            "updated": len(updated_ids),
            "skipped": len(skipped_ids),
            "updated_ids": updated_ids,
            "skipped_ids": skipped_ids,
        }

    def generate_report(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        today = datetime.now(CST).date()
        start_target = date.fromisoformat(start_date) if start_date else today
        end_target = date.fromisoformat(end_date) if end_date else start_target
        if start_target > end_target:
            raise ValueError("开始日期不能晚于结束日期")
        if end_target > today:
            raise ValueError("结束日期不能晚于今天")
        if (end_target - start_target).days > 364:
            raise ValueError("汇总时间最多为 365 天")
        start_value = start_target.isoformat()
        end_value = end_target.isoformat()
        single_day = start_target == end_target
        report_key = f"D:{start_value}" if single_day else f"R:{start_value}:{end_value}"
        start = datetime.combine(start_target, time.min, tzinfo=CST).astimezone(UTC)
        end = datetime.combine(end_target + timedelta(days=1), time.min, tzinfo=CST).astimezone(UTC)
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT q.status, q.title, m.chat_name, m.sender, m.source_time, m.id AS message_id
                FROM questions q JOIN messages m ON m.id=q.message_id
                WHERE m.source_time>=? AND m.source_time<? AND q.status!='ignored'
                ORDER BY CASE q.status WHEN 'confirmed' THEN 0 ELSE 1 END, m.source_time
                """,
                (iso(start), iso(end)),
            ).fetchall()
            confirmed = [row for row in rows if row["status"] == "confirmed"]
            pending = [row for row in rows if row["status"] == "pending"]
            title = (
                f"{start_value} 微信群聊问题报告"
                if single_day
                else f"{start_value} 至 {end_value} 微信群聊问题汇总报告"
            )
            lines = [
                f"# {title}",
                "",
                (
                    f"> 仅基于 {'Windows' if self.settings.runtime_platform == 'windows' else 'Mac'} "
                    "本机当前仍保留、且已成功解码并采集的消息生成；监听中断区间不代表无消息。"
                ),
                "",
                f"- 已确认：{len(confirmed)}",
                f"- 待复核：{len(pending)}",
                "",
            ]
            for heading, items in (("已确认问题", confirmed), ("待人工复核", pending)):
                lines.append(f"## {heading}")
                if not items:
                    lines.append("- 暂无")
                for row in items:
                    time_format = "%H:%M" if single_day else "%m-%d %H:%M"
                    when = datetime.fromisoformat(row["source_time"]).astimezone(CST).strftime(time_format)
                    lines.append(
                        f"- {row['title']}（{row['chat_name']} · {row['sender']} · {when} · 原消息 #{row['message_id']}）"
                    )
                lines.append("")
            content = "\n".join(lines).strip()
            now = iso(now_utc())
            conn.execute(
                """
                INSERT INTO reports(
                    report_key, report_date, period_start, period_end, content,
                    question_count, confirmed_count, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_key) DO UPDATE SET content=excluded.content,
                    question_count=excluded.question_count, confirmed_count=excluded.confirmed_count,
                    updated_at=excluded.updated_at
                """,
                (
                    report_key, start_value, start_value, end_value, content,
                    len(rows), len(confirmed), now, now,
                ),
            )
        return self.get_report(report_key)

    def get_report(self, report_key: str) -> dict[str, Any]:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM reports WHERE report_key=?", (report_key,)).fetchone()
        if not row:
            raise LookupError(report_key)
        return dict(row)

    def list_reports(self, limit: int = 60) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM reports ORDER BY period_end DESC, period_start DESC, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_report(self, report_date: str) -> bool:
        target = date.fromisoformat(report_date).isoformat()
        now = iso(now_utc())
        with self.database.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM reports WHERE report_key=?", (f"D:{target}",)
            )
            if cursor.rowcount:
                conn.execute(
                    "INSERT INTO audit_log(action, detail_json, created_at) VALUES ('delete_report', ?, ?)",
                    (json.dumps({"report_date": target}), now),
                )
        return bool(cursor.rowcount)

    def delete_report_by_id(self, report_id: int) -> bool:
        now = iso(now_utc())
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT report_key, period_start, period_end FROM reports WHERE id=?",
                (report_id,),
            ).fetchone()
            if not row:
                return False
            cursor = conn.execute("DELETE FROM reports WHERE id=?", (report_id,))
            conn.execute(
                "INSERT INTO audit_log(action, detail_json, created_at) VALUES ('delete_report', ?, ?)",
                (
                    json.dumps(
                        {
                            "report_key": row["report_key"],
                            "period_start": row["period_start"],
                            "period_end": row["period_end"],
                        }
                    ),
                    now,
                ),
            )
        return bool(cursor.rowcount)

    def update_listener_state(self, **fields: Any) -> None:
        allowed = {
            "state", "detail", "last_probe_at", "last_wal_activity_at", "last_decode_at",
            "wal_event_count", "decode_error_count",
        }
        data = {key: value for key, value in fields.items() if key in allowed}
        if not data:
            return
        assignments = ", ".join(f"{key}=?" for key in data)
        with self.database.connection() as conn:
            conn.execute(f"UPDATE listener_state SET {assignments} WHERE id=1", tuple(data.values()))

    def listener_state(self) -> dict[str, Any]:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM listener_state WHERE id=1").fetchone()
        return dict(row)

    def dashboard(self, probe: dict[str, Any]) -> dict[str, Any]:
        with self.database.connection() as conn:
            stats = conn.execute(
                """
                SELECT (SELECT COUNT(*) FROM messages) AS message_count,
                       (SELECT COUNT(*) FROM questions WHERE status='pending') AS pending_count,
                       (SELECT COUNT(*) FROM questions WHERE status='confirmed') AS confirmed_count,
                       (SELECT MAX(observed_at) FROM messages) AS last_message_at
                """
            ).fetchone()
        return {
            "stats": dict(stats),
            "listener": self.listener_state(),
            "probe": probe,
            "settings": self.get_settings(),
            "high_water": self.message_high_water(tuple(self.get_settings()["groups"])),
        }
