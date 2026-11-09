from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import struct
import tempfile
from pathlib import Path
from typing import Any

from Crypto.Cipher import AES

from .windows_profiles import DecoderProfile, safe_identifier
from .windows_snapshot import capture_stable_snapshot, committed_wal_frames


SQLITE_HEADER = b"SQLite format 3\x00"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
IMAGE_PLACEHOLDER = "此内容为图片，不支持展示"
UNKNOWN_PLACEHOLDER = "此消息类型暂不支持展示"


def _entry_keys(entry: dict[str, str], profile: DecoderProfile) -> tuple[bytes, bytes]:
    encryption_key = bytes.fromhex(str(entry.get("encryption_key", "")))
    authentication_key = bytes.fromhex(str(entry.get("hmac_key", "")))
    expected_hmac_key_size = int(profile.crypto.get("hmac_key_size", 32))
    if len(encryption_key) != 32 or len(authentication_key) != expected_hmac_key_size:
        raise ValueError("invalid protected database key entry")
    return encryption_key, authentication_key


def derive_authentication_key(
    encryption_key: bytes, database_salt: bytes, profile: DecoderProfile
) -> bytes:
    if len(encryption_key) != 32 or len(database_salt) != 16:
        raise ValueError("invalid SQLCipher key or database salt")
    if profile.crypto.get("hmac_key_source") != "sqlcipher4-derived":
        raise RuntimeError("decoder profile requires a provided HMAC key")
    mask = int(profile.crypto.get("hmac_salt_mask", 0x3A))
    iterations = int(profile.crypto.get("hmac_kdf_iterations", 2))
    key_size = int(profile.crypto.get("hmac_key_size", 32))
    if not 0 <= mask <= 255 or not 1 <= iterations <= 1_000_000:
        raise ValueError("invalid HMAC key derivation profile")
    hmac_salt = bytes(value ^ mask for value in database_salt)
    return hashlib.pbkdf2_hmac(
        "sha512", encryption_key, hmac_salt, iterations, dklen=key_size
    )


def authenticate_page(
    page: bytes,
    page_number: int,
    profile: DecoderProfile,
    authentication_key: bytes,
) -> None:
    page_size = int(profile.crypto.get("page_size", 4096))
    reserve_size = int(profile.crypto.get("reserve_size", 80))
    if len(page) != page_size:
        raise ValueError("incomplete encrypted database page")
    if profile.crypto.get("page_authentication") != "hmac-sha512":
        raise RuntimeError("decoder profile lacks verified page authentication")
    auth_size = int(profile.crypto.get("hmac_size", 64))
    iv_size = int(profile.crypto.get("iv_size", 16))
    if iv_size + auth_size > reserve_size:
        raise ValueError("page authentication does not fit reserve bytes")
    page_number_endian = str(profile.crypto.get("page_number_endian", "little"))
    if page_number_endian not in {"little", "big"}:
        raise ValueError("invalid page_number_endian")
    start = (
        16
        if page_number == 1 and bool(profile.crypto.get("exclude_page1_salt", True))
        else 0
    )
    material = page[start : page_size - reserve_size + iv_size] + page_number.to_bytes(
        4, page_number_endian
    )
    expected = hmac.new(authentication_key, material, hashlib.sha512).digest()[:auth_size]
    actual = page[page_size - reserve_size + iv_size : page_size - reserve_size + iv_size + auth_size]
    if not hmac.compare_digest(expected, actual):
        raise RuntimeError(f"database page authentication failed at page {page_number}")


def decrypt_page(
    page: bytes,
    page_number: int,
    profile: DecoderProfile,
    encryption_key: bytes,
    authentication_key: bytes,
) -> bytes:
    authenticate_page(page, page_number, profile, authentication_key)
    page_size = int(profile.crypto.get("page_size", 4096))
    reserve_size = int(profile.crypto.get("reserve_size", 80))
    encrypted_start = 16 if page_number == 1 else 0
    encrypted_end = page_size - reserve_size
    iv = page[encrypted_end : encrypted_end + 16]
    plaintext = AES.new(encryption_key, AES.MODE_CBC, iv).decrypt(
        page[encrypted_start:encrypted_end]
    )
    output = bytearray(page_size)
    if page_number == 1:
        output[:16] = SQLITE_HEADER
        output[16 : 16 + len(plaintext)] = plaintext
        output[16:18] = struct.pack(">H", 1 if page_size == 65536 else page_size)
    else:
        output[: len(plaintext)] = plaintext
    return bytes(output)


def sqlite_schema_signature(path: Path, dynamic_table_prefix: str = "") -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        signatures: dict[str, dict[str, Any]] = {}
        for table in tables:
            normalized_table = (
                f"{dynamic_table_prefix}*"
                if dynamic_table_prefix and table.startswith(dynamic_table_prefix)
                else table
            )
            signature = {
                "table": normalized_table,
                "columns": [
                    [str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5])]
                    for row in connection.execute(f"PRAGMA table_info([{table}])")
                ],
            }
            signatures[json.dumps(signature, ensure_ascii=True, sort_keys=True)] = signature
        return [signatures[key] for key in sorted(signatures)]
    finally:
        connection.close()


def schema_fingerprint(decrypted_root: Path, profile: DecoderProfile) -> str:
    contact_relative = str(profile.schema.get("contact_relative_path", "contact/contact.db"))
    message_glob = str(profile.schema.get("message_glob", "message/message_*.db"))
    message_prefix = safe_identifier(str(profile.schema.get("message_table_prefix", "Msg_")))
    signatures: list[dict[str, Any]] = []
    contact = decrypted_root / contact_relative
    if contact.exists():
        signatures.append({"role": "contact", "schema": sqlite_schema_signature(contact)})
    message_signatures = {
        json.dumps(
            sqlite_schema_signature(path, message_prefix), ensure_ascii=True, sort_keys=True
        )
        for path in decrypted_root.glob(message_glob)
    }
    for signature in sorted(message_signatures):
        signatures.append({"role": "message-shard", "schema": json.loads(signature)})
    payload = json.dumps(signatures, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_schema(decrypted_root: Path, profile: DecoderProfile) -> str:
    contact_relative = str(profile.schema.get("contact_relative_path", "contact/contact.db"))
    contact_path = decrypted_root / contact_relative
    contact_table = safe_identifier(str(profile.schema.get("contact_table", "contact")))
    if not contact_path.exists():
        raise RuntimeError("decrypted contact database is missing")
    connection = sqlite3.connect(f"file:{contact_path}?mode=ro", uri=True)
    try:
        columns = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info([{contact_table}])")
        }
    finally:
        connection.close()
    required_contact = {
        safe_identifier(str(profile.schema.get("contact_id_column", "username"))),
        *(
            safe_identifier(str(value))
            for value in profile.schema.get("contact_name_columns", ["remark", "nick_name", "alias"])
        ),
    }
    if not required_contact.issubset(columns):
        raise RuntimeError("contact schema does not match decoder profile")
    message_paths = sorted(
        decrypted_root.glob(str(profile.schema.get("message_glob", "message/message_*.db")))
    )
    if not message_paths:
        raise RuntimeError("decrypted message shards are missing")
    fingerprint = schema_fingerprint(decrypted_root, profile)
    if fingerprint != profile.schema_fingerprint:
        raise RuntimeError("decrypted schema fingerprint does not match the enabled profile")
    return fingerprint


def decrypt_database_snapshot(
    source_db: Path,
    destination_db: Path,
    entry: dict[str, str],
    profile: DecoderProfile,
    private_snapshot_root: Path,
) -> dict[str, Any]:
    if source_db.resolve() == destination_db.resolve():
        raise RuntimeError("decrypted destination must not overwrite the source database")
    encryption_key, authentication_key = _entry_keys(entry, profile)
    bundle = capture_stable_snapshot(source_db, private_snapshot_root)
    page_size = int(profile.crypto.get("page_size", 4096))
    try:
        encrypted = bundle.database.read_bytes()
        if not encrypted or len(encrypted) % page_size:
            raise RuntimeError("encrypted database size is not page-aligned")
        result = bytearray()
        page_count = len(encrypted) // page_size
        for index in range(page_count):
            page = encrypted[index * page_size : (index + 1) * page_size]
            result.extend(
                decrypt_page(page, index + 1, profile, encryption_key, authentication_key)
            )
        wal_frames: list[tuple[int, bytes]] = []
        committed_size: int | None = None
        if bundle.wal:
            wal_frames, committed_size = committed_wal_frames(bundle.wal, page_size)
        for page_number, encrypted_page in wal_frames:
            start = (page_number - 1) * page_size
            required = start + page_size
            if len(result) < required:
                result.extend(b"\x00" * (required - len(result)))
            result[start:required] = decrypt_page(
                encrypted_page,
                page_number,
                profile,
                encryption_key,
                authentication_key,
            )
        if committed_size is not None:
            result = result[: committed_size * page_size]
        destination_db.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination_db.with_suffix(destination_db.suffix + ".tmp")
        try:
            temporary.write_bytes(result)
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            connection = sqlite3.connect(f"file:{temporary}?mode=ro", uri=True)
            try:
                quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            finally:
                connection.close()
            if quick_check != "ok":
                raise RuntimeError("decrypted snapshot failed quick_check")
            temporary.replace(destination_db)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "base_pages": page_count,
            "committed_wal_frames": len(wal_frames),
            "quick_check": "ok",
        }
    finally:
        shutil.rmtree(bundle.directory, ignore_errors=True)


def decode_value(value: Any) -> str:
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


def _contact_rows(
    contact_db: Path, profile: DecoderProfile
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    table = safe_identifier(str(profile.schema.get("contact_table", "contact")))
    id_column = safe_identifier(str(profile.schema.get("contact_id_column", "username")))
    name_columns = [
        safe_identifier(str(value))
        for value in profile.schema.get("contact_name_columns", ["remark", "nick_name", "alias"])
    ]
    columns = ", ".join(f"[{value}]" for value in [id_column, *name_columns])
    names: dict[str, str] = {}
    groups: dict[str, str] = {}
    duplicate_groups: set[str] = set()
    connection = sqlite3.connect(f"file:{contact_db}?mode=ro", uri=True)
    try:
        for row in connection.execute(f"SELECT {columns} FROM [{table}]"):
            identity = str(row[0] or "")
            display = next((str(value) for value in row[1:] if value), identity)
            names[identity] = display
            if identity.endswith("@chatroom"):
                if display in groups and groups[display] != identity:
                    duplicate_groups.add(display)
                else:
                    groups[display] = identity
    finally:
        connection.close()
    return names, groups, duplicate_groups


def read_messages(
    decrypted_root: Path,
    profile: DecoderProfile,
    groups: list[str],
    *,
    limit: int,
    history_groups: set[str] | None = None,
    history_cutoff: int | None = None,
    high_water: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    history_groups = history_groups or set()
    high_water = high_water or {}
    contact_path = decrypted_root / str(
        profile.schema.get("contact_relative_path", "contact/contact.db")
    )
    contact_names, group_ids, duplicate_groups = _contact_rows(contact_path, profile)
    errors = {
        group: "未唯一匹配到群聊"
        for group in groups
        if group not in group_ids or group in duplicate_groups
    }
    prefix = safe_identifier(str(profile.schema.get("message_table_prefix", "Msg_")))
    columns = {
        key: safe_identifier(str(profile.schema[key]))
        for key in (
            "message_id_column",
            "message_type_column",
            "message_sender_column",
            "message_time_column",
            "message_content_column",
        )
    }
    local_id_column = safe_identifier(str(profile.schema.get("message_local_id_column", "local_id")))
    compressed_column = safe_identifier(
        str(profile.schema.get("message_compressed_column", "compress_content"))
    )
    member_table = safe_identifier(str(profile.schema.get("member_table", "Name2Id")))
    member_id_column = safe_identifier(str(profile.schema.get("member_id_column", "rowid")))
    member_name_column = safe_identifier(str(profile.schema.get("member_name_column", "user_name")))
    rows: list[dict[str, Any]] = []
    groups_with_message_tables: set[str] = set()
    for shard in sorted(
        decrypted_root.glob(str(profile.schema.get("message_glob", "message/message_*.db")))
    ):
        connection = sqlite3.connect(f"file:{shard}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            try:
                member_names = {
                    int(row[0]): contact_names.get(str(row[1]), str(row[1]))
                    for row in connection.execute(
                        f"SELECT [{member_id_column}], [{member_name_column}] FROM [{member_table}]"
                    )
                }
            except sqlite3.Error:
                member_names = {}
            for group in groups:
                group_id = group_ids.get(group)
                if not group_id or group in duplicate_groups:
                    continue
                table = prefix + hashlib.md5(group_id.encode("utf-8")).hexdigest()
                if not connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone():
                    continue
                groups_with_message_tables.add(group)
                selected = [local_id_column, *columns.values(), compressed_column]
                query = f"SELECT {', '.join(f'[{value}]' for value in selected)} FROM [{table}]"
                parameters: tuple[Any, ...] = ()
                minimum_timestamp = (
                    history_cutoff
                    if group in history_groups
                    else min(
                        max(0, int(high_water.get(group, 0)) - 5),
                        history_cutoff,
                    )
                    if group in high_water and history_cutoff is not None
                    else max(0, int(high_water.get(group, 0)) - 5)
                    if group in high_water
                    else history_cutoff
                )
                if minimum_timestamp is not None:
                    query += f" WHERE [{columns['message_time_column']}] >= ?"
                    parameters = (minimum_timestamp,)
                query += f" ORDER BY [{columns['message_time_column']}] DESC, [{local_id_column}] DESC"
                if minimum_timestamp is None:
                    query += " LIMIT ?"
                    parameters += (max(1, min(limit, 5000)),)
                for row in connection.execute(query, parameters):
                    message_type = str(row[columns["message_type_column"]])
                    content = decode_value(row[columns["message_content_column"]]) or decode_value(
                        row[compressed_column]
                    )
                    if message_type in {"3", "image", "图片"}:
                        content = IMAGE_PLACEHOLDER
                    elif message_type not in {"1", "text", "文本", "244813135921"}:
                        content = UNKNOWN_PLACEHOLDER
                    server_id = int(row[columns["message_id_column"]] or 0)
                    local_id = int(row[local_id_column] or 0)
                    timestamp = int(row[columns["message_time_column"]] or 0)
                    stable_material = (
                        f"{group_id}:{server_id}"
                        if server_id
                        else f"{group_id}:{local_id}:{timestamp}:{hashlib.sha256(content.encode()).hexdigest()}"
                    )
                    sender_id = int(row[columns["message_sender_column"]] or 0)
                    rows.append(
                        {
                            "source_id": hashlib.sha256(stable_material.encode()).hexdigest(),
                            "chat": group,
                            "sender": member_names.get(sender_id, "我" if sender_id == 2 else "未知成员"),
                            "content": content[:20_000],
                            "msg_type": message_type,
                            "timestamp": timestamp,
                            "is_group": True,
                        }
                    )
        finally:
            connection.close()
    for group in groups:
        if group in group_ids and group not in duplicate_groups and group not in groups_with_message_tables:
            errors[group] = "message table was not found in any verified shard"
    rows.sort(key=lambda item: (item["timestamp"], item["source_id"]), reverse=True)
    return rows, errors
