#!/usr/bin/env python3
"""User-triggered validation and DPAPI sealing for Windows database keys.

This command intentionally does not scan process memory. A target-build-specific,
user-approved provider may export candidate encryption/HMAC keys into a temporary
JSON file. This tool validates those candidates against stable snapshots before
anything is written to the protected key store.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.platforms.windows import (
    account_fingerprint,
    discover_windows_accounts,
    windows_file_version,
)
from app.platforms.windows_decoder import (
    decrypt_database_snapshot,
    derive_authentication_key,
    schema_fingerprint,
    validate_schema,
)
from app.platforms.windows_profiles import layout_fingerprint, load_profiles, required_key_paths
from app.platforms.windows_security import WindowsKeyStore
from scripts.windows_vault_decoder import create_private_session


def selected_account(settings: Settings) -> Path:
    accounts = discover_windows_accounts(settings.wechat_data_root)
    if settings.windows_account_id:
        accounts = [path for path in accounts if path.name == settings.windows_account_id]
    if len(accounts) != 1:
        raise RuntimeError("必须通过 WML_WINDOWS_ACCOUNT_ID 唯一选择一个微信账号")
    return accounts[0]


def redacted_diagnostics(settings: Settings) -> dict:
    version, build = windows_file_version(settings.wechat_app_path)
    accounts = discover_windows_accounts(settings.wechat_data_root)
    selected = None
    try:
        selected = selected_account(settings)
    except RuntimeError:
        pass
    relative_files = (
        sorted(
            path.relative_to(selected).as_posix()
            for path in (selected / "db_storage").rglob("*")
            if path.is_file()
            and (
                path.name.endswith(".db")
                or path.name.endswith(".db-wal")
                or path.name.endswith(".db-shm")
            )
        )
        if selected
        else []
    )
    return {
        "format": 1,
        "platform": "windows",
        "wechat": {
            "executable_name": settings.wechat_app_path.name,
            "installed": settings.wechat_app_path.exists(),
            "version": version,
            "build": build,
        },
        "accounts": {
            "count": len(accounts),
            "selection_required": len(accounts) != 1 and not settings.windows_account_id,
            "selected_fingerprint": account_fingerprint(selected)[:12] if selected else "",
        },
        "data": {
            "layout_fingerprint": layout_fingerprint(selected) if selected else "",
            "relative_files": relative_files,
        },
        "privacy": {
            "contains_keys": False,
            "contains_chat_content": False,
            "contains_account_name": False,
        },
    }


def choose_profile(settings: Settings, profile_id: str, require_enabled: bool):
    profiles = {profile.profile_id: profile for profile in load_profiles(settings.windows_profiles_path)}
    profile = profiles.get(profile_id)
    if not profile:
        raise RuntimeError("未找到指定 decoder profile")
    if require_enabled and not profile.enabled:
        raise RuntimeError("正式密钥准备只允许使用 enabled profile")
    version, build = windows_file_version(settings.wechat_app_path)
    account = selected_account(settings)
    if profile.version != (version or "") or profile.build != (build or ""):
        raise RuntimeError("decoder profile 的版本或构建号与当前微信不一致")
    if profile.layout_fingerprint != layout_fingerprint(account):
        raise RuntimeError("decoder profile 的数据布局指纹与当前账号不一致")
    return profile, account


def load_candidates(path: Path, profile) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    rows = payload.get("keys", payload) if isinstance(payload, dict) else {}
    if not isinstance(rows, dict) or not rows:
        raise RuntimeError("候选密钥文件必须包含非空 keys 映射")
    normalized: dict[str, dict[str, str]] = {}
    for relative, entry in rows.items():
        if not isinstance(entry, dict):
            raise RuntimeError("每个数据库必须同时提供 encryption_key 与 hmac_key")
        encryption_key = bytes.fromhex(str(entry.get("encryption_key", "")))
        hmac_hex = str(entry.get("hmac_key", ""))
        hmac_key = bytes.fromhex(hmac_hex) if hmac_hex else b""
        expected_hmac_size = int(profile.crypto.get("hmac_key_size", 32))
        if len(encryption_key) != 32:
            raise RuntimeError("候选数据库 AES 密钥长度不符合 profile 要求")
        if profile.crypto.get("hmac_key_source") == "provided" and len(hmac_key) != expected_hmac_size:
            raise RuntimeError("候选数据库 HMAC 密钥长度不符合 profile 要求")
        if hmac_key and len(hmac_key) != expected_hmac_size:
            raise RuntimeError("候选数据库 HMAC 密钥长度不符合 profile 要求")
        normalized[Path(str(relative)).as_posix()] = {"encryption_key": encryption_key.hex()}
        if hmac_key:
            normalized[Path(str(relative)).as_posix()]["hmac_key"] = hmac_key.hex()
    return normalized


def validate_candidates(settings: Settings, profile, account: Path, candidates_path: Path):
    candidates = load_candidates(candidates_path, profile)
    expected_paths = required_key_paths(account, profile)
    if sorted(candidates) != expected_paths:
        raise RuntimeError("候选密钥未完整覆盖 profile 要求的数据库分片")
    if settings.windows_snapshot_root is None:
        raise RuntimeError('密钥验证必须配置本工具私有快照目录')
    validation_root = create_private_session(settings.windows_snapshot_root, account, 'key-validation-')
    decrypted_root = validation_root / "decrypted"
    capture_root = validation_root / "captures"
    try:
        validated: dict[str, dict[str, str]] = {}
        for relative, entry in candidates.items():
            source = (account / relative).resolve()
            if account.resolve() not in source.parents or not source.exists() or source.suffix != ".db":
                raise RuntimeError("候选密钥映射包含无效数据库相对路径")
            if not entry.get("hmac_key"):
                with source.open("rb") as handle:
                    database_salt = handle.read(16)
                entry["hmac_key"] = derive_authentication_key(
                    bytes.fromhex(entry["encryption_key"]), database_salt, profile
                ).hex()
            decrypt_database_snapshot(source, decrypted_root / relative, entry, profile, capture_root)
            validated[relative] = entry
        fingerprint = schema_fingerprint(decrypted_root, profile)
        return validated, fingerprint, decrypted_root
    except Exception:
        shutil.rmtree(validation_root, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    diagnose = subparsers.add_parser("diagnose")
    diagnose.add_argument("--output", type=Path)
    inspect = subparsers.add_parser("inspect-candidates")
    inspect.add_argument("--profile-id", required=True)
    inspect.add_argument("--candidates", type=Path, required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--profile-id", required=True)
    prepare.add_argument("--candidates", type=Path, required=True)
    subparsers.add_parser("status")
    args = parser.parse_args()

    settings = Settings.from_env()
    if settings.runtime_platform != "windows":
        raise RuntimeError("windows_key_prep.py 只能在 Windows 配置下运行")
    if args.command == "diagnose":
        payload = redacted_diagnostics(settings)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(text + "\n", encoding="utf-8")
            print(f"脱敏诊断已写入：{args.output}")
        else:
            print(text)
        return
    store = WindowsKeyStore(settings.windows_key_store_path)
    if args.command == "status":
        metadata = store.metadata()
        print(
            json.dumps(
                {
                    "prepared": bool(metadata),
                    "profile_id": metadata.profile_id if metadata else "",
                    "validated_at": metadata.validated_at if metadata else None,
                    "database_count": metadata.database_count if metadata else 0,
                },
                ensure_ascii=False,
            )
        )
        return

    profile, account = choose_profile(
        settings, args.profile_id, require_enabled=args.command == "prepare"
    )
    validated, fingerprint, decrypted_root = validate_candidates(
        settings, profile, account, args.candidates
    )
    validation_root = decrypted_root.parent
    try:
        if args.command == "inspect-candidates":
            print(
                json.dumps(
                    {
                        "profile_id": profile.profile_id,
                        "database_count": len(validated),
                        "schema_fingerprint": fingerprint,
                        "quick_check": "ok",
                        "keys_in_output": False,
                    },
                    ensure_ascii=False,
                )
            )
            return
        if fingerprint != profile.schema_fingerprint:
            raise RuntimeError("解密后的 schema 指纹与 enabled profile 不一致")
        validate_schema(decrypted_root, profile)
        metadata = store.save(
            profile_id=profile.profile_id,
            account_fingerprint=account_fingerprint(account),
            layout_fingerprint=layout_fingerprint(account),
            schema_fingerprint=fingerprint,
            keys=validated,
        )
        print(
            json.dumps(
                {
                    "prepared": True,
                    "profile_id": metadata.profile_id,
                    "validated_at": metadata.validated_at,
                    "database_count": metadata.database_count,
                    "keys_in_output": False,
                },
                ensure_ascii=False,
            )
        )
    finally:
        shutil.rmtree(validation_root, ignore_errors=True)


if __name__ == "__main__":
    main()
