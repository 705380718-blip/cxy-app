from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import struct
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from Crypto.Cipher import AES

from app.platforms.windows import WindowsEnvironmentProbe, account_fingerprint
from app.platforms.windows_decoder import (
    authenticate_page,
    decrypt_database_snapshot,
    derive_authentication_key,
    read_messages,
    schema_fingerprint,
    validate_schema,
)
from app.platforms.windows_profiles import (
    DecoderProfile,
    layout_fingerprint,
    load_profiles,
    match_profile,
)
from scripts.windows_vault_decoder import safe_source
from app.platforms.windows_security import DPAPI_HEADER, KeyStoreMetadata, WindowsKeyStore
from app.platforms.windows_snapshot import (
    WAL_MAGIC_BIG_CHECKSUM,
    capture_stable_snapshot,
    committed_wal_frames,
    wal_checksum,
)


def make_profile(**overrides) -> DecoderProfile:
    raw = {
        "id": "windows-test-profile",
        "enabled": True,
        "version": "4.2.0",
        "build": "12345",
        "layout_fingerprint": "a" * 64,
        "schema_fingerprint": "b" * 64,
        "crypto": {
            "cipher": "aes-256-cbc-raw-key",
            "page_size": 4096,
            "reserve_size": 80,
            "page_authentication": "hmac-sha512",
            "hmac_size": 64,
            "hmac_key_size": 32,
            "hmac_material": "ciphertext-iv-pgno",
            "hmac_key_source": "provided",
            "iv_size": 16,
            "page_number_endian": "little",
            "exclude_page1_salt": True,
        },
        "schema": {
            "key_database_globs": [
                "db_storage/contact/contact.db",
                "db_storage/message/message_*.db",
            ],
            "contact_relative_path": "db_storage/contact/contact.db",
            "contact_table": "contact",
            "contact_id_column": "username",
            "contact_name_columns": ["remark", "nick_name", "alias"],
            "message_glob": "db_storage/message/message_*.db",
            "message_table_prefix": "Msg_",
            "message_table_hash": "md5",
            "message_id_column": "server_id",
            "message_local_id_column": "local_id",
            "message_type_column": "local_type",
            "message_sender_column": "real_sender_id",
            "message_time_column": "create_time",
            "message_content_column": "message_content",
            "message_compressed_column": "compress_content",
            "member_table": "Name2Id",
            "member_id_column": "rowid",
            "member_name_column": "user_name",
        },
    }
    raw.update(overrides)
    return DecoderProfile.from_dict(raw)


def test_enabled_profile_requires_exact_build_layout_schema_and_hmac():
    profile = make_profile()
    assert match_profile([profile], "4.2.0", "12345", "a" * 64) == profile
    assert match_profile([profile], "4.2.1", "12345", "a" * 64) is None
    assert match_profile([profile], "4.2.0", "99999", "a" * 64) is None
    assert match_profile([profile], "4.2.0", "12345", "c" * 64) is None
    with pytest.raises(ValueError, match="hmac-sha512"):
        make_profile(crypto={"page_size": 4096, "reserve_size": 80, "page_authentication": "none"})


@pytest.mark.parametrize(
    ("field", "value"),
    (("hmac_size", 0), ("hmac_size", 1), ("iv_size", 0), ("iv_size", 32)),
)
def test_enabled_profile_rejects_downgraded_crypto_parameters(field: str, value: int):
    crypto = dict(make_profile().crypto)
    crypto[field] = value
    with pytest.raises(ValueError, match=field):
        make_profile(crypto=crypto)


def test_layout_fingerprint_normalizes_shard_numbers(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, number in ((first, "0"), (second, "99")):
        path = root / "db_storage/message" / f"message_{number}.db"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"db")
        Path(f"{path}-wal").write_bytes(b"wal")
    assert layout_fingerprint(first) == layout_fingerprint(second)
    Path(f"{first / 'db_storage/message/message_0.db'}-shm").write_bytes(b"shm")
    Path(f"{first / 'db_storage/message/message_0.db'}-wal").unlink()
    assert layout_fingerprint(first) == layout_fingerprint(second)


def test_key_store_envelope_never_contains_plaintext_key(tmp_path: Path):
    path = tmp_path / "keys.dpapi"
    transform = lambda data: bytes(value ^ 0xA5 for value in data)
    store = WindowsKeyStore(
        path,
        protect=transform,
        unprotect=transform,
        acl=lambda _: None,
    )
    encryption_key = "11" * 32
    authentication_key = "22" * 32
    metadata = store.save(
        profile_id="windows-test-profile",
        account_fingerprint="account",
        layout_fingerprint="layout",
        schema_fingerprint="schema",
        keys={
            "db_storage/contact/contact.db": {
                "encryption_key": encryption_key,
                "hmac_key": authentication_key,
            }
        },
    )
    raw = path.read_bytes()
    assert raw.startswith(DPAPI_HEADER)
    assert encryption_key.encode() not in raw
    assert authentication_key.encode() not in raw
    assert metadata.database_count == 1
    assert store.load()["keys"]["db_storage/contact/contact.db"]["encryption_key"] == encryption_key


def test_stable_snapshot_copies_db_wal_and_shm(tmp_path: Path):
    source = tmp_path / "source/message_0.db"
    source.parent.mkdir()
    source.write_bytes(b"database")
    Path(f"{source}-wal").write_bytes(b"wal")
    Path(f"{source}-shm").write_bytes(b"shm")
    bundle = capture_stable_snapshot(source, tmp_path / "private", debounce_seconds=0)
    assert bundle.database.read_bytes() == b"database"
    assert bundle.wal and bundle.wal.read_bytes() == b"wal"
    assert bundle.shm and bundle.shm.read_bytes() == b"shm"


def _wal_header(salt: bytes) -> tuple[bytes, tuple[int, int]]:
    first = struct.pack(">IIII", WAL_MAGIC_BIG_CHECKSUM, 3_007_000, 4096, 1) + salt
    checksum = wal_checksum(first, "big")
    return first + struct.pack(">II", *checksum), checksum


def _wal_frame(
    page_number: int,
    database_size: int,
    salt: bytes,
    page: bytes,
    seed: tuple[int, int],
) -> tuple[bytes, tuple[int, int]]:
    first = struct.pack(">II", page_number, database_size)
    checksum = wal_checksum(first + page, "big", seed)
    return first + salt + struct.pack(">II", *checksum) + page, checksum


def test_wal_parser_stops_at_last_valid_commit(tmp_path: Path):
    salt = b"12345678"
    header, checksum = _wal_header(salt)
    committed, checksum = _wal_frame(2, 2, salt, b"a" * 4096, checksum)
    uncommitted, _ = _wal_frame(3, 0, salt, b"b" * 4096, checksum)
    wal = tmp_path / "sample.db-wal"
    wal.write_bytes(header + committed + uncommitted)
    frames, database_size = committed_wal_frames(wal, 4096)
    assert [(number, page[:1]) for number, page in frames] == [(2, b"a")]
    assert database_size == 2


def test_wal_parser_rejects_bad_header_checksum(tmp_path: Path):
    header, _ = _wal_header(b"12345678")
    wal = tmp_path / "sample.db-wal"
    wal.write_bytes(header[:-1] + bytes([header[-1] ^ 1]))
    with pytest.raises(RuntimeError, match="header checksum"):
        committed_wal_frames(wal, 4096)


def encrypted_authenticated_page(profile: DecoderProfile, page_number: int = 1):
    encryption_key = b"e" * 32
    authentication_key = b"h" * 32
    page_size = int(profile.crypto["page_size"])
    reserve_size = int(profile.crypto["reserve_size"])
    page = bytearray(page_size)
    start = 16 if page_number == 1 else 0
    iv = bytes([page_number]) * 16
    plaintext = b"p" * (page_size - reserve_size - start)
    page[start : page_size - reserve_size] = AES.new(encryption_key, AES.MODE_CBC, iv).encrypt(plaintext)
    page[page_size - reserve_size : page_size - reserve_size + 16] = iv
    material = bytes(page[start : page_size - reserve_size + 16]) + page_number.to_bytes(4, "little")
    digest = hmac.new(authentication_key, material, hashlib.sha512).digest()
    page[page_size - reserve_size + 16 :] = digest
    return bytes(page), encryption_key, authentication_key


def test_page_hmac_detects_tampering():
    profile = make_profile()
    page, _, authentication_key = encrypted_authenticated_page(profile)
    authenticate_page(page, 1, profile, authentication_key)
    tampered = bytearray(page)
    tampered[100] ^= 1
    with pytest.raises(RuntimeError, match="authentication failed"):
        authenticate_page(bytes(tampered), 1, profile, authentication_key)


def test_sqlcipher4_authentication_key_derivation_uses_page_salt():
    profile = make_profile(
        crypto={**make_profile().crypto, "hmac_key_source": "sqlcipher4-derived"}
    )
    encryption_key = bytes(range(32))
    salt = bytes(range(16))
    expected = hashlib.pbkdf2_hmac(
        "sha512", encryption_key, bytes(value ^ 0x3A for value in salt), 2, dklen=32
    )
    assert derive_authentication_key(encryption_key, salt, profile) == expected


def test_authenticated_database_fixture_decrypts_and_passes_quick_check(tmp_path: Path):
    plain_path = tmp_path / "plain.db"
    connection = sqlite3.connect(plain_path)
    connection.execute("PRAGMA page_size=4096")
    connection.execute("VACUUM")
    connection.close()
    plaintext = bytearray(plain_path.read_bytes())
    assert len(plaintext) == 4096
    plaintext[20] = 80
    plaintext[105:107] = struct.pack(">H", 4016)

    profile = make_profile()
    encryption_key = b"e" * 32
    authentication_key = b"h" * 32
    encrypted = bytearray(4096)
    encrypted[:16] = b"s" * 16
    iv = b"i" * 16
    encrypted[16:4016] = AES.new(encryption_key, AES.MODE_CBC, iv).encrypt(
        bytes(plaintext[16:4016])
    )
    encrypted[4016:4032] = iv
    material = bytes(encrypted[16:4032]) + (1).to_bytes(4, "little")
    encrypted[4032:] = hmac.new(authentication_key, material, hashlib.sha512).digest()
    source = tmp_path / "source.db"
    source.write_bytes(encrypted)
    destination = tmp_path / "decrypted.db"

    result = decrypt_database_snapshot(
        source,
        destination,
        {
            "encryption_key": encryption_key.hex(),
            "hmac_key": authentication_key.hex(),
        },
        profile,
        tmp_path / "private",
    )

    assert result["quick_check"] == "ok"
    connection = sqlite3.connect(f"file:{destination}?mode=ro", uri=True)
    try:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_decrypt_refuses_to_overwrite_source(tmp_path: Path):
    source = tmp_path / "source.db"
    source.write_bytes(b"encrypted")
    with pytest.raises(RuntimeError, match="must not overwrite"):
        decrypt_database_snapshot(
            source,
            source,
            {"encryption_key": "11" * 32, "hmac_key": "22" * 32},
            make_profile(),
            tmp_path / "private",
        )


def test_safe_source_rejects_absolute_and_parent_paths(tmp_path: Path):
    account = tmp_path / "account"
    account.mkdir()
    for unsafe in ("../outside.db", str((tmp_path / "outside.db").resolve())):
        with pytest.raises(RuntimeError, match="unsafe relative path"):
            safe_source(account, unsafe)


def create_schema_fixture(root: Path) -> str:
    contact = root / "db_storage/contact/contact.db"
    contact.parent.mkdir(parents=True)
    connection = sqlite3.connect(contact)
    connection.execute("CREATE TABLE contact(username TEXT, remark TEXT, nick_name TEXT, alias TEXT)")
    connection.execute("INSERT INTO contact VALUES ('room@chatroom', '测试群', '', '')")
    connection.execute("INSERT INTO contact VALUES ('member-a', '成员甲', '', '')")
    connection.commit()
    connection.close()

    message = root / "db_storage/message/message_0.db"
    message.parent.mkdir(parents=True)
    table = "Msg_" + hashlib.md5(b"room@chatroom").hexdigest()
    connection = sqlite3.connect(message)
    connection.execute("CREATE TABLE Name2Id(rowid INTEGER, user_name TEXT)")
    connection.execute("INSERT INTO Name2Id VALUES (7, 'member-a')")
    connection.execute(
        f"CREATE TABLE [{table}](local_id INTEGER, server_id INTEGER, local_type INTEGER, "
        "real_sender_id INTEGER, create_time INTEGER, message_content BLOB, compress_content BLOB)"
    )
    connection.execute(
        f"INSERT INTO [{table}] VALUES (1, 9001, 1, 7, 1786500000, '请问如何处理？', NULL)"
    )
    connection.commit()
    connection.close()
    return table


def test_schema_fingerprint_and_profile_driven_message_mapping(tmp_path: Path):
    create_schema_fixture(tmp_path)
    draft = make_profile(enabled=False, schema_fingerprint="")
    fingerprint = schema_fingerprint(tmp_path, draft)
    profile = make_profile(schema_fingerprint=fingerprint)
    assert validate_schema(tmp_path, profile) == fingerprint
    messages, errors = read_messages(
        tmp_path, profile, ["测试群"], limit=10
    )
    assert errors == {}
    assert len(messages) == 1
    assert messages[0]["sender"] == "成员甲"
    assert messages[0]["content"] == "请问如何处理？"


def test_incremental_read_rescans_retention_window_for_delayed_rows(tmp_path: Path):
    create_schema_fixture(tmp_path)
    profile = make_profile(enabled=False, schema_fingerprint="")
    messages, errors = read_messages(
        tmp_path,
        profile,
        ["测试群"],
        limit=10,
        history_cutoff=1786400000,
        high_water={"测试群": 1786600000},
    )
    assert errors == {}
    assert [item["content"] for item in messages] == ["请问如何处理？"]


def test_missing_group_message_table_is_blocked(tmp_path: Path):
    create_schema_fixture(tmp_path)
    message = tmp_path / "db_storage/message/message_0.db"
    connection = sqlite3.connect(message)
    table = "Msg_" + hashlib.md5(b"room@chatroom").hexdigest()
    connection.execute(f"DROP TABLE [{table}]")
    connection.commit()
    connection.close()
    profile = make_profile(enabled=False, schema_fingerprint="")
    messages, errors = read_messages(tmp_path, profile, ["测试群"], limit=10)
    assert messages == []
    assert errors["测试群"] == "message table was not found in any verified shard"


def test_duplicate_exact_group_names_are_blocked(tmp_path: Path):
    create_schema_fixture(tmp_path)
    contact = tmp_path / "db_storage/contact/contact.db"
    connection = sqlite3.connect(contact)
    connection.execute("INSERT INTO contact VALUES ('other@chatroom', '测试群', '', '')")
    connection.commit()
    connection.close()
    profile = make_profile(enabled=False, schema_fingerprint="")
    messages, errors = read_messages(tmp_path, profile, ["测试群"], limit=10)
    assert messages == []
    assert "测试群" in errors


def test_windows_probe_fails_closed_without_keys(monkeypatch, settings, tmp_path: Path):
    root = tmp_path / "xwechat_files"
    account = root / "account-a"
    database = account / "db_storage/message/message_0.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"encrypted")
    executable = tmp_path / "Weixin.exe"
    executable.write_bytes(b"pe")
    layout = layout_fingerprint(account)
    profile_path = tmp_path / "profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "windows-test-profile",
                        "enabled": True,
                        "version": "4.2.0",
                        "build": "12345",
                        "layout_fingerprint": layout,
                        "schema_fingerprint": "b" * 64,
                        "crypto": make_profile().crypto,
                        "schema": make_profile().schema,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    windows_settings = replace(
        settings,
        runtime_platform="windows",
        wechat_app_path=executable,
        wechat_data_root=root,
        decoder_command=(sys.executable, "decoder.py"),
        windows_profiles_path=profile_path,
        windows_key_store_path=tmp_path / "missing.dpapi",
        windows_snapshot_root=tmp_path / "snapshots",
        windows_account_id="account-a",
    )
    monkeypatch.setattr("app.platforms.windows.windows_file_version", lambda _: ("4.2.0", "12345"))
    monkeypatch.setattr("app.platforms.windows.windows_wechat_running", lambda: True)
    payload = WindowsEnvironmentProbe(windows_settings).inspect()
    assert payload["can_observe_wal"] is True
    assert payload["can_decode"] is False
    assert payload["decoder"]["profile_exact_match"] is True
    assert "keys_not_prepared" in {item["code"] for item in payload["blocker_details"]}
    assert str(account) not in json.dumps(payload)


def test_windows_probe_requires_account_selection(monkeypatch, settings, tmp_path: Path):
    root = tmp_path / "xwechat_files"
    for name in ("account-a", "account-b"):
        path = root / name / "db_storage/message/message_0.db"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"encrypted")
    windows_settings = replace(
        settings,
        runtime_platform="windows",
        wechat_data_root=root,
        windows_profiles_path=tmp_path / "missing.json",
        windows_key_store_path=tmp_path / "missing.dpapi",
        windows_account_id="",
    )
    monkeypatch.setattr("app.platforms.windows.windows_file_version", lambda _: ("4.2.0", "12345"))
    monkeypatch.setattr("app.platforms.windows.windows_wechat_running", lambda: True)
    payload = WindowsEnvironmentProbe(windows_settings).inspect()
    assert payload["can_observe_wal"] is False
    assert "account_selection_required" in {item["code"] for item in payload["blocker_details"]}
