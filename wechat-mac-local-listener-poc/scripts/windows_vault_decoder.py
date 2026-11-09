#!/usr/bin/env python3
"""Decode verified Windows WeChat snapshots into the shared JSON contract."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.platforms.windows import account_fingerprint, discover_windows_accounts
from app.platforms.windows_decoder import (
    decrypt_database_snapshot,
    read_messages,
    validate_schema,
)
from app.platforms.windows_profiles import layout_fingerprint, load_profiles
from app.platforms.windows_security import WindowsKeyStore, apply_current_user_acl, reject_private_links


def configured_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    try:
        values = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        values = []
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def configured_high_water() -> dict[str, int]:
    raw = os.getenv("WML_HIGH_WATER_JSON", "")
    try:
        values = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        values = {}
    if not isinstance(values, dict):
        return {}
    return {
        str(group): int(timestamp)
        for group, timestamp in values.items()
        if str(group).strip() and str(timestamp).isdigit()
    }


def selected_account(root: Path, expected_fingerprint: str) -> Path:
    matches = [
        account
        for account in discover_windows_accounts(root)
        if account_fingerprint(account) == expected_fingerprint
    ]
    if len(matches) != 1:
        raise RuntimeError("protected key mapping does not uniquely match a local account")
    return matches[0]


def safe_source(account: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or relative_path.drive or ".." in relative_path.parts:
        raise RuntimeError("protected key mapping contains an unsafe relative path")
    candidate = (account / relative_path).resolve()
    account_root = account.resolve()
    if candidate != account_root and account_root not in candidate.parents:
        raise RuntimeError("protected key mapping escaped the selected account")
    return candidate


def require_private_vault(vault: Path, account: Path) -> Path:
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required for Windows private snapshots")
    reject_private_links(vault.absolute())
    private_path = Path(local_app_data) / "GroupChatOrganizer/private"
    reject_private_links(private_path.absolute())
    private_root = private_path.resolve()
    resolved = vault.resolve()
    if resolved != private_root and private_root not in resolved.parents:
        raise RuntimeError("decoder vault must stay below the fixed private app directory")
    account_root = account.resolve()
    if resolved == account_root or resolved in account_root.parents or account_root in resolved.parents:
        raise RuntimeError("decoder vault must not overlap the WeChat account directory")
    return resolved


def create_private_session(vault: Path, account: Path, prefix: str) -> Path:
    """Protect plaintext snapshot storage even when this CLI runs without its launcher."""
    private_vault = require_private_vault(vault, account)
    private_vault.mkdir(mode=0o700, parents=True, exist_ok=True)
    def protect(path):
        reject_private_links(path)
        if os.name == 'nt':
            apply_current_user_acl(path)
        else:
            path.chmod(0o700)
    protect(private_vault)
    session = Path(tempfile.mkdtemp(prefix=prefix, dir=private_vault))
    try:
        protect(session)
        for name in ('decrypted', 'captures'):
            child = session / name
            child.mkdir(mode=0o700)
            protect(child)
        return session
    except Exception:
        shutil.rmtree(session, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["new-messages"])
    parser.add_argument("--wechat-root", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    protected = WindowsKeyStore(args.keys).load()
    profiles = {profile.profile_id: profile for profile in load_profiles(args.profiles)}
    profile = profiles.get(str(protected.get("profile_id", "")))
    if not profile or not profile.enabled:
        raise RuntimeError("protected keys do not reference an enabled decoder profile")
    account = selected_account(args.wechat_root, str(protected["account_fingerprint"]))
    if layout_fingerprint(account) != profile.layout_fingerprint:
        raise RuntimeError("current database layout no longer matches the decoder profile")

    session_root = create_private_session(args.vault, account, 'decode-session-')
    decrypted_root = session_root / "decrypted"
    capture_root = session_root / "captures"
    try:
        refreshed: list[dict] = []
        for relative, entry in dict(protected.get("keys", {})).items():
            source = safe_source(account, str(relative))
            if not source.exists():
                raise RuntimeError("a validated database in the protected mapping is missing")
            destination = decrypted_root / Path(str(relative))
            info = decrypt_database_snapshot(source, destination, dict(entry), profile, capture_root)
            refreshed.append({"database_role": Path(relative).parent.name, **info})

        fingerprint = validate_schema(decrypted_root, profile)
        if fingerprint != str(protected.get("schema_fingerprint", "")):
            raise RuntimeError("protected key validation schema no longer matches")
        groups = configured_list("WML_TARGET_GROUPS_JSON")
        if not groups:
            raise RuntimeError("at least one exact group name is required")
        history_groups = set(configured_list("WML_HISTORY_GROUPS_JSON")).intersection(groups)
        try:
            history_days = max(1, min(365, int(os.getenv("WML_HISTORY_DAYS", "7"))))
        except ValueError:
            history_days = 7
        cutoff = int(time.time()) - history_days * 86400
        messages, errors = read_messages(
            decrypted_root,
            profile,
            groups,
            limit=max(1, min(args.limit, 5000)),
            history_groups=history_groups,
            history_cutoff=cutoff,
            high_water=configured_high_water(),
        )
        print(
            json.dumps(
                {
                    "messages": messages,
                    "meta": {
                        "profile_id": profile.profile_id,
                        "refreshed": refreshed,
                        "history_groups": sorted(history_groups),
                        "group_errors": errors,
                        "schema_verified": True,
                    },
                },
                ensure_ascii=False,
            )
        )
    finally:
        shutil.rmtree(session_root, ignore_errors=True)


if __name__ == "__main__":
    main()
