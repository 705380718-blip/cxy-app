#!/usr/bin/env python3
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from Crypto.Cipher import AES


PAGE_SIZE = 4096
RESERVE = 80


def key_works(database: Path, key_hex: str) -> bool:
    try:
        key = bytes.fromhex(key_hex)
        if len(key) != 32:
            return False
        with database.open("rb") as handle:
            page = handle.read(PAGE_SIZE)
        if len(page) != PAGE_SIZE:
            return False
        encrypted_size = PAGE_SIZE - RESERVE - 16
        iv = page[PAGE_SIZE - RESERVE : PAGE_SIZE - RESERVE + 16]
        decrypted = AES.new(key, AES.MODE_CBC, iv).decrypt(
            page[16 : 16 + encrypted_size]
        )
        rebuilt = b"SQLite format 3\x00" + decrypted
        return (
            struct.unpack(">H", rebuilt[16:18])[0] == PAGE_SIZE
            and rebuilt[18] in (1, 2)
            and rebuilt[19] in (1, 2)
            and rebuilt[20] == RESERVE
            and rebuilt[21:24] == bytes((64, 32, 32))
        )
    except (OSError, ValueError, KeyError):
        return False


def main() -> int:
    home = Path.home()
    keys_path = home / ".config/wechat-keys.json"
    roots = sorted(
        (home / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files").glob(
            "*/db_storage"
        )
    )
    if len(roots) != 1 or not keys_path.exists():
        print("  [VERIFY] 未找到唯一微信账号数据库或密钥文件。")
        return 1

    keys = json.loads(keys_path.read_text(encoding="utf-8"))
    db_base = roots[0]
    required = [("contact", db_base / "contact/contact.db")]
    required.extend(
        (path.stem, path)
        for path in sorted((db_base / "message").glob("message_[0-9]*.db"))
    )
    failed = []
    for name, database in required:
        relative = str(database.relative_to(db_base))
        key_hex = keys.get(name) or keys.get(relative) or ""
        if not key_works(database, key_hex):
            failed.append(name)

    if failed:
        print("  [VERIFY] 以下关键数据库仍无法解密：" + ", ".join(failed))
        return 1
    print(f"  [VERIFY] 已验证 contact 和 {len(required) - 1} 个消息数据库。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
