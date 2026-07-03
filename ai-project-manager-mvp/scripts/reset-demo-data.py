#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
DB_PATH = BACKEND_DIR / "data" / "app.db"
BACKUP_DIR = BACKEND_DIR / "data" / "backups"
STORAGE_DIR = ROOT_DIR / "storage"
SMOKE_PATTERNS = ("%Smoke%", "%smoke%", "%0526%", "%today-smoke%")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    return connection


def backup_db() -> Path | None:
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"app-{timestamp}.db"
    shutil.copy2(DB_PATH, target)
    return target


def like_clause(columns: tuple[str, ...]) -> tuple[str, list[str]]:
    clauses = []
    params: list[str] = []
    for column in columns:
        for pattern in SMOKE_PATTERNS:
            clauses.append(f"{column} like ?")
            params.append(pattern)
    return " or ".join(clauses), params


def select_ids(connection: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> list[int]:
    clause, params = like_clause(columns)
    rows = connection.execute(f"select id from {table} where {clause}", params).fetchall()
    return [int(row["id"]) for row in rows]


def count_rows(connection: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> int:
    clause, params = like_clause(columns)
    row = connection.execute(f"select count(*) as total from {table} where {clause}", params).fetchone()
    return int(row["total"] or 0)


def delete_ids(connection: sqlite3.Connection, table: str, ids: list[int]) -> int:
    if not ids:
        return 0
    placeholders = ", ".join("?" for _ in ids)
    cursor = connection.execute(f"delete from {table} where id in ({placeholders})", ids)
    return cursor.rowcount


def cleanup_smoke_data(dry_run: bool) -> dict[str, int]:
    if not DB_PATH.exists():
        return {}
    summary: dict[str, int] = {}
    with connect() as connection:
        snippet_ids = select_ids(connection, "snippets", ("raw_text", "source_type"))
        extraction_ids = select_ids(connection, "extractions", ("title", "description", "response"))
        if snippet_ids:
            placeholders = ", ".join("?" for _ in snippet_ids)
            rows = connection.execute(
                f"select id from extractions where snippet_id in ({placeholders})",
                snippet_ids,
            ).fetchall()
            extraction_ids.extend(int(row["id"]) for row in rows)
        extraction_ids = sorted(set(extraction_ids))

        table_specs = [
            ("tasks", ("title", "description", "owner")),
            ("risks", ("title", "description", "response")),
            ("demands", ("title", "description", "scope_impact")),
            ("milestones", ("title", "status")),
            ("document_versions", ("title", "content_markdown", "export_path")),
            ("document_templates", ("name", "original_filename", "file_path")),
            ("chat_messages", ("content", "action_payload")),
        ]
        for table, columns in table_specs:
            summary[table] = count_rows(connection, table, columns)
        summary["extractions"] = len(extraction_ids)
        summary["snippets"] = len(snippet_ids)

        if dry_run:
            return summary

        for table, columns in table_specs:
            ids = select_ids(connection, table, columns)
            summary[table] = delete_ids(connection, table, ids)
        summary["extractions"] = delete_ids(connection, "extractions", extraction_ids)
        summary["snippets"] = delete_ids(connection, "snippets", snippet_ids)
        connection.commit()
    return summary


def reset_demo_database() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    sys.path.insert(0, str(BACKEND_DIR))
    from app.db import init_db

    init_db()


def cleanup_generated_smoke_files(dry_run: bool) -> list[str]:
    targets = [
        ROOT_DIR / "output" / "playwright" / "today-smoke-gantt.png",
        ROOT_DIR / "output" / "playwright" / "today-settings-restored.png",
        ROOT_DIR / "output" / "playwright" / "today-smoke-template.md",
    ]
    targets.extend((STORAGE_DIR / "exports").glob("*Smoke*"))
    targets.extend((STORAGE_DIR / "exports").glob("*0526*"))
    targets.extend((STORAGE_DIR / "templates").glob("*today-smoke*"))
    removed: list[str] = []
    for path in targets:
        if path.exists():
            removed.append(str(path.relative_to(ROOT_DIR)))
            if not dry_run:
                path.unlink()
    return sorted(set(removed))


def print_summary(title: str, summary: dict[str, int]) -> None:
    print(title)
    if not summary:
        print("  no database found")
        return
    for key in sorted(summary):
        print(f"  {key}: {summary[key]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean smoke data or reset the local demo database.")
    parser.add_argument("--smoke-only", action="store_true", help="remove records and generated files that look like smoke-test data")
    parser.add_argument("--reset-demo", action="store_true", help="recreate the SQLite database with bundled seed data")
    parser.add_argument("--yes", action="store_true", help="apply changes; without this flag the script only prints a dry run")
    parser.add_argument("--keep-files", action="store_true", help="keep generated smoke files when using --smoke-only")
    args = parser.parse_args()

    if not args.smoke_only and not args.reset_demo:
        parser.error("choose --smoke-only or --reset-demo")
    if args.smoke_only and args.reset_demo:
        parser.error("choose only one cleanup mode")

    dry_run = not args.yes
    backup_path = backup_db() if args.yes else None
    if backup_path:
        print(f"backup: {backup_path.relative_to(ROOT_DIR)}")

    if args.smoke_only:
        summary = cleanup_smoke_data(dry_run)
        print_summary("smoke data cleanup" + (" dry run" if dry_run else ""), summary)
        if not args.keep_files:
            files = cleanup_generated_smoke_files(dry_run)
            print("generated files" + (" dry run" if dry_run else ""))
            for path in files:
                print(f"  {path}")
        return 0

    if dry_run:
        print("reset demo dry run")
        print(f"  database: {DB_PATH.relative_to(ROOT_DIR)}")
        print("  would recreate database from bundled seed data")
        return 0

    reset_demo_database()
    print("reset demo database")
    print(f"  database: {DB_PATH.relative_to(ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
