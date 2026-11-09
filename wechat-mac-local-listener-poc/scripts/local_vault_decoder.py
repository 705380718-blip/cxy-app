#!/usr/bin/env python3
"""Read one exact local WeChat group through private decrypted snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import tempfile
import re
import time
import sys
from pathlib import Path

from Crypto.Cipher import AES

# Standalone decoder processes start with scripts/ on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.platforms.windows_snapshot import capture_stable_snapshot, committed_wal_frames


PAGE_SIZE = 4096
RESERVE_SIZE = 80
WAL_HEADER_SIZE = 32
WAL_FRAME_HEADER_SIZE = 24
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
IMAGE_PLACEHOLDER = "此内容为图片，不支持展示"
WECHAT_SENDER_PREFIX = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.-]{2,127}:(?:\r?\n|\s+)(?P<body>[\s\S]*)$"
)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def decrypt_page(page: bytes, key: bytes, page_number: int) -> bytes:
    if len(page) != PAGE_SIZE:
        raise ValueError("incomplete SQLCipher page")
    encrypted_start = 16 if page_number == 1 else 0
    encrypted_size = PAGE_SIZE - RESERVE_SIZE - encrypted_start
    iv = page[PAGE_SIZE - RESERVE_SIZE : PAGE_SIZE - RESERVE_SIZE + 16]
    plaintext = AES.new(key, AES.MODE_CBC, iv).decrypt(
        page[encrypted_start : encrypted_start + encrypted_size]
    )
    output = bytearray(PAGE_SIZE)
    if page_number == 1:
        output[:16] = b"SQLite format 3\x00"
        output[16 : 16 + len(plaintext)] = plaintext
        output[16:18] = struct.pack(">H", PAGE_SIZE)
    else:
        output[: len(plaintext)] = plaintext
    return bytes(output)


def copy_stable(source: Path, destination: Path, attempts: int = 4) -> None:
    for _ in range(attempts):
        before = source.stat()
        shutil.copy2(source, destination)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
            return
    raise RuntimeError(f"source kept changing while copying: {source.name}")


def wal_frames(wal_path: Path) -> list[tuple[int, bytes]]:
    return committed_wal_frames(wal_path, PAGE_SIZE)[0]


def decrypt_snapshot(source_db: Path, destination_db: Path, key_hex: str) -> dict:
    key = bytes.fromhex(key_hex)
    if len(key) != 32:
        raise ValueError("database key must be 32 bytes")
    destination_db.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wechat-readonly-") as temp_name:
        temp_dir = Path(temp_name)
        bundle = capture_stable_snapshot(source_db, temp_dir)
        db_copy = bundle.database

        encrypted = db_copy.read_bytes()
        page_count = len(encrypted) // PAGE_SIZE
        result = bytearray()
        for index in range(page_count):
            page = encrypted[index * PAGE_SIZE : (index + 1) * PAGE_SIZE]
            result.extend(decrypt_page(page, key, index + 1))

        frames, committed_size = (
            committed_wal_frames(bundle.wal, PAGE_SIZE) if bundle.wal else ([], None)
        )
        applied = 0
        for page_number, page in frames:
            if committed_size is not None and page_number > committed_size:
                continue
            start = (page_number - 1) * PAGE_SIZE
            required = start + PAGE_SIZE
            if len(result) < required:
                result.extend(b"\x00" * (required - len(result)))
            result[start:required] = decrypt_page(page, key, page_number)
            applied += 1
        if committed_size is not None:
            result = result[: committed_size * PAGE_SIZE]

        temporary_output = destination_db.with_suffix(".tmp")
        temporary_output.write_bytes(result)
        os.chmod(temporary_output, 0o600)
        connection = sqlite3.connect(f"file:{temporary_output}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            connection.close()
        if integrity != "ok":
            temporary_output.unlink(missing_ok=True)
            raise RuntimeError(f"decrypted snapshot failed quick_check: {source_db.name}")
        temporary_output.replace(destination_db)
        return {"base_pages": page_count, "wal_frames": applied}


def decode_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raw = bytes(value)
    if raw.startswith(ZSTD_MAGIC):
        try:
            import zstandard

            raw = zstandard.ZstdDecompressor().decompress(raw, max_output_size=1_000_000)
        except Exception:
            return "[压缩消息解码失败]"
    return raw.decode("utf-8", errors="replace")


def clean_message_content(content: str, message_type: int | str) -> str:
    text = str(content or "").strip()
    if str(message_type).strip().lower() in {"3", "image", "图片"}:
        return IMAGE_PLACEHOLDER
    match = WECHAT_SENDER_PREFIX.match(text)
    if match:
        text = match.group("body").strip()
    lowered = text.lower()
    if lowered.startswith("<?xml") and "<img" in lowered:
        return IMAGE_PLACEHOLDER
    return text


def exact_group(contact_db: Path, group_name: str) -> str:
    connection = sqlite3.connect(f"file:{contact_db}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT username FROM contact WHERE remark=? OR nick_name=? OR alias=?",
            (group_name, group_name, group_name),
        ).fetchall()
    finally:
        connection.close()
    groups = [str(row[0]) for row in rows if str(row[0]).endswith("@chatroom")]
    if len(groups) != 1:
        raise RuntimeError(f"exact group match must be unique; found {len(groups)}")
    return groups[0]


def name_mapping(connection: sqlite3.Connection) -> dict[int, str]:
    try:
        return {
            int(row[0]): str(row[1])
            for row in connection.execute("SELECT rowid, user_name FROM Name2Id")
            if row[1]
        }
    except sqlite3.Error:
        return {}


def contact_names(contact_db: Path) -> dict[str, str]:
    connection = sqlite3.connect(f"file:{contact_db}?mode=ro", uri=True)
    try:
        return {
            str(row[0]): str(row[1] or row[2] or row[3] or row[0])
            for row in connection.execute("SELECT username, remark, nick_name, alias FROM contact")
        }
    finally:
        connection.close()


def read_messages(
    decrypted_dir: Path, group_name: str, limit: int | None, min_timestamp: int | None = None
) -> list[dict]:
    contact_db = decrypted_dir / "contact/contact.db"
    group_id = exact_group(contact_db, group_name)
    names = contact_names(contact_db)
    table = "Msg_" + hashlib.md5(group_id.encode()).hexdigest()
    rows: list[dict] = []
    for db_path in sorted((decrypted_dir / "message").glob("message_[0-9]*.db")):
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                continue
            mapping = name_mapping(connection)
            query = (
                f"SELECT local_id, server_id, local_type, real_sender_id, create_time, "
                f"message_content, compress_content FROM [{table}] "
                + ("WHERE create_time >= ? " if min_timestamp is not None else "")
                + "ORDER BY create_time DESC, local_id DESC"
            )
            parameters: tuple[int, ...] = (min_timestamp,) if min_timestamp is not None else ()
            if limit is not None:
                query += " LIMIT ?"
                parameters += (limit,)
            for row in connection.execute(query, parameters):
                content = decode_value(row["message_content"]) or decode_value(row["compress_content"])
                sender_id = int(row["real_sender_id"] or 0)
                sender_username = mapping.get(sender_id, "")
                if ":\n" in content:
                    prefix, remainder = content.split(":\n", 1)
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{2,127}", prefix):
                        sender_username = sender_username or prefix
                content = clean_message_content(content, row["local_type"])
                source_material = (
                    f"{group_id}:{db_path.name}:{row['server_id']}:{row['local_id']}:"
                    f"{row['create_time']}:{row['local_type']}"
                )
                rows.append(
                    {
                        "source_id": hashlib.sha256(source_material.encode()).hexdigest(),
                        "chat": group_name,
                        "sender": names.get(sender_username, "我" if sender_id == 2 else "未知成员"),
                        "content": content[:20_000],
                        "msg_type": str(row["local_type"]),
                        "timestamp": int(row["create_time"]),
                        "is_group": True,
                    }
                )
        finally:
            connection.close()
    rows.sort(key=lambda item: (item["timestamp"], item["source_id"]), reverse=True)
    return rows if limit is None else rows[:limit]


def configured_groups(argument_groups: list[str]) -> list[str]:
    raw = os.getenv("WML_TARGET_GROUPS_JSON", "")
    if raw:
        try:
            values = json.loads(raw)
            if isinstance(values, list):
                return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))
        except json.JSONDecodeError:
            pass
    return list(dict.fromkeys(item.strip() for item in argument_groups if item.strip()))


def configured_history_groups(groups: list[str]) -> set[str]:
    raw = os.getenv("WML_HISTORY_GROUPS_JSON", "")
    try:
        values = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        values = []
    requested = {str(item).strip() for item in values if str(item).strip()}
    return requested.intersection(groups)


def history_cutoff_epoch() -> int:
    try:
        days = int(os.getenv("WML_HISTORY_DAYS", "7"))
    except ValueError:
        days = 7
    return int(time.time()) - max(1, min(days, 365)) * 86400


def configured_high_water(groups: list[str]) -> dict[str, int]:
    try:
        values = json.loads(os.getenv("WML_HIGH_WATER_JSON", "{}"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(values, dict):
        return {}
    return {
        group: value for group in groups
        if type(value := values.get(group)) is int and value > 0
    }


def source_mtime(source: Path) -> int:
    wal = Path(f"{source}-wal")
    return max(source.stat().st_mtime_ns, wal.stat().st_mtime_ns if wal.exists() else 0)


def refresh_snapshot(source: Path, destination: Path, key: str) -> dict | None:
    observed_mtime = source_mtime(source)
    if destination.exists() and destination.stat().st_mtime_ns >= observed_mtime:
        return None
    info = decrypt_snapshot(source, destination, key)
    # Cache against the signature observed before capture, so concurrent later writes
    # are retried rather than hidden by the output file's newer wall-clock time.
    os.utime(destination, ns=(observed_mtime, observed_mtime))
    return info


def group_message_sources(decrypted_dir: Path, groups: list[str]) -> set[str]:
    contact_db = decrypted_dir / "contact/contact.db"
    if not contact_db.exists():
        return set()
    tables: set[str] = set()
    for group in groups:
        try:
            group_id = exact_group(contact_db, group)
        except RuntimeError:
            continue
        tables.add("Msg_" + hashlib.md5(group_id.encode()).hexdigest())
    sources: set[str] = set()
    for db_path in sorted((decrypted_dir / "message").glob("message_[0-9]*.db")):
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            placeholders = ",".join("?" for _ in tables)
            if tables and connection.execute(
                f"SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ({placeholders}) LIMIT 1",
                tuple(tables),
            ).fetchone():
                sources.add(db_path.stem)
        finally:
            connection.close()
    return sources


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["new-messages"])
    parser.add_argument("--group", action="append", default=[])
    parser.add_argument("--db-base", type=Path, required=True)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    keys = load_json(args.keys)
    args.vault.mkdir(parents=True, exist_ok=True)
    os.chmod(args.vault, 0o700)
    groups = configured_groups(args.group)
    if not groups:
        raise RuntimeError("at least one exact group name is required")
    history_groups = configured_history_groups(groups)
    high_water = configured_high_water(groups)
    history_cutoff = history_cutoff_epoch()
    message_sources = sorted((args.db_base / "message").glob("message_[0-9]*.db"))
    required = ["contact"] + [path.stem for path in message_sources]
    refreshed = []
    contact_source = args.db_base / "contact/contact.db"
    contact_destination = args.vault / "contact/contact.db"
    contact_key = keys.get("contact") or keys.get("contact/contact.db")
    if contact_key and contact_source.exists():
        info = refresh_snapshot(contact_source, contact_destination, contact_key)
        if info:
            refreshed.append({"database": "contact", **info})

    for name in required:
        relative = "contact/contact.db" if name == "contact" else f"message/{name}.db"
        key = keys.get(name) or keys.get(relative)
        source = args.db_base / relative
        if not key or not source.exists():
            continue
        destination = args.vault / relative
        if name == "contact":
            continue
        info = refresh_snapshot(source, destination, key)
        if info:
            refreshed.append({"database": name, **info})

    messages: list[dict] = []
    group_errors: dict[str, str] = {}
    per_group_limit = max(1, min(args.limit, 1000))
    for group in groups:
        try:
            group_messages = read_messages(
                args.vault,
                group,
                None if group in history_groups or group in high_water else per_group_limit,
                history_cutoff if group in history_groups else (
                    max(history_cutoff, high_water[group]) if group in high_water else None
                ),
            )
            messages.extend(group_messages)
        except RuntimeError as exc:
            group_errors[group] = str(exc)
    messages.sort(key=lambda item: (item["timestamp"], item["source_id"]), reverse=True)
    print(
        json.dumps(
            {
                "messages": messages,
                "meta": {
                    "refreshed": refreshed,
                    "groups": groups,
                    "history_groups": sorted(history_groups),
                    "history_cutoff_epoch": history_cutoff,
                    "group_errors": group_errors,
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
