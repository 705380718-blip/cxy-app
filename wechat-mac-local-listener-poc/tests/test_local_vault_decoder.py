from __future__ import annotations

import importlib.util
import json
import sqlite3
import struct
import hashlib
import shutil
import os
from pathlib import Path

import pytest
from Crypto.Cipher import AES
from app.platforms.windows_snapshot import wal_checksum


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/local_vault_decoder.py"
SPEC = importlib.util.spec_from_file_location("local_vault_decoder", SCRIPT)
decoder = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(decoder)


def test_zstandard_message_round_trip_and_invalid_data():
    import zstandard
    text='构造群消息：请明天提交验收材料。'
    assert decoder.decode_value(zstandard.ZstdCompressor().compress(text.encode()))==text
    assert decoder.decode_value(decoder.ZSTD_MAGIC+b'invalid')=='[压缩消息解码失败]'


def encrypted_page(key: bytes, page_number: int, plaintext: bytes) -> bytes:
    page = bytearray(decoder.PAGE_SIZE)
    start = 16 if page_number == 1 else 0
    payload = plaintext[start : decoder.PAGE_SIZE - decoder.RESERVE_SIZE]
    iv = bytes([page_number]) * 16
    page[start : decoder.PAGE_SIZE - decoder.RESERVE_SIZE] = AES.new(
        key, AES.MODE_CBC, iv
    ).encrypt(payload)
    page[decoder.PAGE_SIZE - decoder.RESERVE_SIZE : decoder.PAGE_SIZE - decoder.RESERVE_SIZE + 16] = iv
    return bytes(page)


def test_decrypt_page_round_trip():
    key = b"k" * 32
    plaintext = bytearray(decoder.PAGE_SIZE)
    plaintext[:16] = b"SQLite format 3\x00"
    plaintext[16 : decoder.PAGE_SIZE - decoder.RESERVE_SIZE] = b"x" * (
        decoder.PAGE_SIZE - decoder.RESERVE_SIZE - 16
    )
    encrypted = encrypted_page(key, 1, bytes(plaintext))
    result = decoder.decrypt_page(encrypted, key, 1)
    assert result[:16] == plaintext[:16]
    assert result[18 : decoder.PAGE_SIZE - decoder.RESERVE_SIZE] == plaintext[18 : decoder.PAGE_SIZE - decoder.RESERVE_SIZE]
    assert result[16:18] == struct.pack(">H", decoder.PAGE_SIZE)


def test_wal_frames_filters_other_generations(tmp_path: Path):
    salt = b"12345678"
    first = struct.pack(">IIII", 0x377F0682, 3_007_000, decoder.PAGE_SIZE, 1) + salt
    seed = wal_checksum(first, "little")
    header = first + struct.pack(">II", *seed)
    frame_first = struct.pack(">II", 7, 7)
    page = b"a" * decoder.PAGE_SIZE
    checksum = wal_checksum(frame_first + page, "little", seed)
    valid = frame_first + salt + struct.pack(">II", *checksum) + page
    stale = struct.pack(">II", 8, 0) + b"87654321" + b"\x00" * 8 + b"b" * decoder.PAGE_SIZE
    wal = tmp_path / "sample.db-wal"
    wal.write_bytes(header + valid + stale)
    frames = decoder.wal_frames(wal)
    assert [(number, page[:1]) for number, page in frames] == [(7, b"a")]


def test_mac_wal_drops_uncommitted_tail_and_corruption(tmp_path: Path):
    salt = b"12345678"
    first = struct.pack(">IIII", 0x377F0682, 3_007_000, decoder.PAGE_SIZE, 1) + salt
    seed = wal_checksum(first, "little")
    data = first + struct.pack(">II", *seed)
    for number, size in [(1, 1), (2, 0)]:
        frame = struct.pack(">II", number, size)
        page = bytes([number]) * decoder.PAGE_SIZE
        seed = wal_checksum(frame + page, "little", seed)
        data += frame + salt + struct.pack(">II", *seed) + page
    path = tmp_path / "sample-wal"
    path.write_bytes(data)
    assert [n for n, _ in decoder.wal_frames(path)] == [1]
    path.write_bytes(data[:31] + bytes([data[31] ^ 1]) + data[32:])
    with pytest.raises(RuntimeError, match="header checksum"):
        decoder.wal_frames(path)


def test_exact_group_requires_unique_chatroom(tmp_path: Path):
    path = tmp_path / "contact.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE contact(username TEXT, remark TEXT, nick_name TEXT, alias TEXT)")
    connection.execute("INSERT INTO contact VALUES ('room@chatroom', '小组长', '', '')")
    connection.commit()
    connection.close()
    assert decoder.exact_group(path, "小组长") == "room@chatroom"


def test_configured_groups_prefers_runtime_settings(monkeypatch):
    monkeypatch.setenv("WML_TARGET_GROUPS_JSON", json.dumps(["小组长", "产品群", "小组长"]))
    assert decoder.configured_groups(["旧群"]) == ["小组长", "产品群"]


def test_history_groups_are_limited_to_allowed_groups(monkeypatch):
    monkeypatch.setenv("WML_HISTORY_GROUPS_JSON", json.dumps(["小组长", "未监听群"]))
    assert decoder.configured_history_groups(["小组长", "产品群"]) == {"小组长"}


def test_history_cutoff_defaults_to_seven_days(monkeypatch):
    monkeypatch.delenv("WML_HISTORY_DAYS", raising=False)
    monkeypatch.setattr(decoder.time, "time", lambda: 1_000_000)
    assert decoder.history_cutoff_epoch() == 1_000_000 - 7 * 86400


def test_decoder_hides_sender_prefix_and_image_xml():
    assert decoder.clean_message_content("hyv5478: 我的微信号是这个呀", 1) == "我的微信号是这个呀"
    assert decoder.clean_message_content("hyv5478:\n<?xml version='1.0'?><msg><img /></msg>", 3) == decoder.IMAGE_PLACEHOLDER


@pytest.mark.parametrize("value", ['[]', '{bad', '{"测试群":true}', '{"测试群":-1}', '{"其他群":100}'])
def test_high_water_rejects_invalid_or_unselected_values(monkeypatch, value):
    monkeypatch.setenv("WML_HIGH_WATER_JSON", value)
    assert decoder.configured_high_water(["测试群"]) == {}


def test_refresh_tracks_contact_wal_and_concurrent_write(tmp_path, monkeypatch):
    source = tmp_path / "contact.db"
    source.write_bytes(b"database")
    wal = Path(f"{source}-wal")
    wal.write_bytes(b"wal")
    os.utime(source, ns=(100, 100)); os.utime(wal, ns=(200, 200))
    destination = tmp_path / "decoded.db"
    calls = []
    def decrypt(source, destination, key):
        calls.append(source.name)
        destination.write_bytes(b"snapshot")
        os.utime(wal, ns=(300, 300))
        return {"base_pages": 1}
    monkeypatch.setattr(decoder, "decrypt_snapshot", decrypt)
    assert decoder.refresh_snapshot(source, destination, "key")
    assert destination.stat().st_mtime_ns == 200
    assert decoder.refresh_snapshot(source, destination, "key")
    assert decoder.refresh_snapshot(source, destination, "key") is None
    assert len(calls) == 2


def test_incremental_reads_over_200_and_discovers_changed_shard(tmp_path, monkeypatch, capsys):
    base = tmp_path / "source"; vault = tmp_path / "private"
    (base / "contact").mkdir(parents=True); (base / "message").mkdir()
    contact = base / "contact/contact.db"
    with sqlite3.connect(contact) as conn:
        conn.execute("CREATE TABLE contact(username TEXT, remark TEXT, nick_name TEXT, alias TEXT)")
        conn.execute("INSERT INTO contact VALUES ('room@chatroom', '测试群', '', '')")
    table = "Msg_" + hashlib.md5(b"room@chatroom").hexdigest()
    for number in (0, 1):
        with sqlite3.connect(base / f"message/message_{number}.db") as conn:
            conn.execute(f"CREATE TABLE [{table if number == 0 else 'unrelated'}] (local_id INTEGER,server_id INTEGER,local_type INTEGER,real_sender_id INTEGER,create_time INTEGER,message_content TEXT,compress_content TEXT)")
            if number == 0:conn.execute(f"INSERT INTO [{table}] VALUES (1,1,1,2,100,'已有消息','')")
    def decrypt(source, destination, key):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return {"base_pages": 1, "wal_frames": 0}
    monkeypatch.setattr(decoder, "decrypt_snapshot", decrypt)
    keys = tmp_path / "keys.json"; keys.write_text(json.dumps({"contact":"fixture","message_0":"fixture","message_1":"fixture"}))
    monkeypatch.setattr(decoder.sys,"argv",["decoder","new-messages","--db-base",str(base),"--keys",str(keys),"--vault",str(vault)])
    monkeypatch.setenv("WML_TARGET_GROUPS_JSON",json.dumps(["测试群"]))
    monkeypatch.setenv("WML_HISTORY_GROUPS_JSON","[]")
    monkeypatch.setenv("WML_HIGH_WATER_JSON",json.dumps({"测试群":100}))
    monkeypatch.setattr(decoder.time,"time",lambda: 1000)
    decoder.main(); assert len(json.loads(capsys.readouterr().out)["messages"]) == 1
    shard = base / "message/message_1.db"
    with sqlite3.connect(shard) as conn:
        conn.execute(f"CREATE TABLE [{table}] (local_id INTEGER,server_id INTEGER,local_type INTEGER,real_sender_id INTEGER,create_time INTEGER,message_content TEXT,compress_content TEXT)")
        conn.executemany(f"INSERT INTO [{table}] VALUES (?,?,1,2,101,'新增消息','')", [(n,n) for n in range(1,252)])
    decoder.main(); result=json.loads(capsys.readouterr().out)
    assert len(result["messages"]) == 252
    assert result["meta"]["group_errors"] == {}
    assert len({m['source_id'] for m in result['messages']}) == 252
