from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SHARD_NUMBER = re.compile(r"(?<=_)[0-9]+(?=\.db(?:-(?:wal|shm))?$)")


def safe_identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe schema identifier: {value!r}")
    return value


def normalized_layout_paths(account_root: Path) -> list[str]:
    paths: set[str] = set()
    db_root = account_root / "db_storage"
    if not db_root.exists():
        return []
    for path in db_root.rglob("*.db"):
        if not path.is_file():
            continue
        relative = PurePosixPath(path.relative_to(account_root).as_posix())
        paths.add(SHARD_NUMBER.sub("#", str(relative)).lower())
    return sorted(paths)


def layout_fingerprint(account_root: Path) -> str:
    payload = json.dumps(
        normalized_layout_paths(account_root), ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def required_key_paths(account_root: Path, profile: "DecoderProfile") -> list[str]:
    paths: set[str] = set()
    for pattern in profile.schema.get("key_database_globs", []):
        for path in account_root.glob(str(pattern)):
            if path.is_file() and path.name.endswith(".db"):
                paths.add(path.relative_to(account_root).as_posix())
    return sorted(paths)


def database_paths_fingerprint(paths: list[str]) -> str:
    payload = json.dumps(sorted(paths), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DecoderProfile:
    profile_id: str
    enabled: bool
    version: str
    build: str
    layout_fingerprint: str
    schema_fingerprint: str
    crypto: dict[str, Any]
    schema: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DecoderProfile":
        profile = cls(
            profile_id=str(raw.get("id", "")).strip(),
            enabled=bool(raw.get("enabled", False)),
            version=str(raw.get("version", "")).strip(),
            build=str(raw.get("build", "")).strip(),
            layout_fingerprint=str(raw.get("layout_fingerprint", "")).strip().lower(),
            schema_fingerprint=str(raw.get("schema_fingerprint", "")).strip().lower(),
            crypto=dict(raw.get("crypto") or {}),
            schema=dict(raw.get("schema") or {}),
        )
        profile.validate()
        return profile

    def validate(self) -> None:
        page_size = int(self.crypto.get("page_size", 4096))
        reserve_size = int(self.crypto.get("reserve_size", 80))
        if not self.profile_id or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", self.profile_id):
            raise ValueError("decoder profile id must be kebab-case")
        if self.enabled and not all(
            (self.version, self.build, self.layout_fingerprint, self.schema_fingerprint)
        ):
            raise ValueError(
                f"enabled decoder profile {self.profile_id!r} must pin version, build, layout and schema"
            )
        if self.layout_fingerprint and not re.fullmatch(r"[0-9a-f]{64}", self.layout_fingerprint):
            raise ValueError("layout_fingerprint must be a SHA-256 hex digest")
        if self.schema_fingerprint and not re.fullmatch(r"[0-9a-f]{64}", self.schema_fingerprint):
            raise ValueError("schema_fingerprint must be a SHA-256 hex digest")
        if self.enabled and self.crypto.get("page_authentication") != "hmac-sha512":
            raise ValueError(
                f"enabled decoder profile {self.profile_id!r} must use verified hmac-sha512 page authentication"
            )
        if self.enabled:
            required_crypto = {
                "iv_size": 16,
                "hmac_size": 64,
                "hmac_key_size": 32,
                "hmac_material": "ciphertext-iv-pgno",
                "exclude_page1_salt": True,
            }
            for key, expected in required_crypto.items():
                if self.crypto.get(key) != expected:
                    raise ValueError(
                        f"enabled decoder profile {self.profile_id!r} requires {key}={expected!r}"
                    )
            if self.crypto.get("hmac_key_source") not in {
                "provided",
                "sqlcipher4-derived",
            }:
                raise ValueError("enabled decoder profile has invalid hmac_key_source")
            if self.crypto.get("page_number_endian") not in {"little", "big"}:
                raise ValueError("enabled decoder profile has invalid page_number_endian")
            if reserve_size != 80:
                raise ValueError("enabled decoder profile currently requires reserve_size=80")
        if self.enabled and not self.schema.get("key_database_globs"):
            raise ValueError(
                f"enabled decoder profile {self.profile_id!r} must define key_database_globs"
            )
        if self.enabled and self.schema.get("message_table_hash") != "md5":
            raise ValueError("enabled decoder profile currently requires message_table_hash=md5")
        if page_size not in {1024, 2048, 4096, 8192, 16384, 32768, 65536}:
            raise ValueError("unsupported crypto page_size")
        if not 16 <= reserve_size < page_size or reserve_size % 16:
            raise ValueError("reserve_size must be a positive AES-block multiple")
        if str(self.crypto.get("cipher", "aes-256-cbc-raw-key")) != "aes-256-cbc-raw-key":
            raise ValueError("only the fixture-tested aes-256-cbc-raw-key profile is implemented")
        for key in (
            "contact_table",
            "contact_id_column",
            "message_table_prefix",
            "message_id_column",
            "message_type_column",
            "message_sender_column",
            "message_time_column",
            "message_content_column",
        ):
            if key in self.schema:
                safe_identifier(str(self.schema[key]))


def load_profiles(path: Path | None) -> list[DecoderProfile]:
    if path is None or not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    rows = payload.get("profiles", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("decoder profile file must contain a profiles list")
    profiles = [DecoderProfile.from_dict(row) for row in rows if isinstance(row, dict)]
    ids = [profile.profile_id for profile in profiles]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate decoder profile id")
    return profiles


def match_profile(
    profiles: list[DecoderProfile], version: str | None, build: str | None, layout: str
) -> DecoderProfile | None:
    matches = [
        profile
        for profile in profiles
        if profile.enabled
        and profile.version == (version or "")
        and profile.build == (build or "")
        and profile.layout_fingerprint == layout
    ]
    if len(matches) > 1:
        raise RuntimeError("multiple enabled decoder profiles match the same build")
    return matches[0] if matches else None
