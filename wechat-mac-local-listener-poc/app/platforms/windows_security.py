from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import stat
import tempfile
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


DPAPI_HEADER = b"WML-DPAPI-1\n"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI is only available on Windows")


def _windows_libraries():
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def protect_current_user(data: bytes) -> bytes:
    _require_windows()
    source, source_buffer = _blob(data)
    destination = DATA_BLOB()
    crypt32, kernel32 = _windows_libraries()
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "GroupChatOrganizer",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(destination),
    ):
        raise ctypes.WinError()
    del source_buffer
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)


def unprotect_current_user(data: bytes) -> bytes:
    _require_windows()
    source, source_buffer = _blob(data)
    destination = DATA_BLOB()
    description = wintypes.LPWSTR()
    crypt32, kernel32 = _windows_libraries()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source),
        ctypes.byref(description),
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(destination),
    ):
        raise ctypes.WinError()
    del source_buffer
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        if destination.pbData:
            kernel32.LocalFree(destination.pbData)
        if description:
            kernel32.LocalFree(description)


def reject_private_links(path: Path) -> None:
    for entry in reversed((path, *path.parents)):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('protected path contains a link or reparse point')


_ACL_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$path = [IO.Path]::GetFullPath($env:WML_ACL_TARGET)
$cursor = $path
while ($cursor) {
    if (Test-Path -LiteralPath $cursor) {
        if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point rejected.' }
    }
    $parent = Split-Path $cursor -Parent
    if ($parent -eq $cursor) { break }
    $cursor = $parent
}
$item = Get-Item -LiteralPath $path -Force
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
if ($item.PSIsContainer) {
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
} else {
    $acl = New-Object Security.AccessControl.FileSecurity
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','Allow')
}
$acl.SetOwner($sid)
$acl.SetAccessRuleProtection($true,$false)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $path -AclObject $acl
$verified = Get-Acl -LiteralPath $path
$rules = @($verified.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if (-not $verified.AreAccessRulesProtected -or $rules.Count -ne 1 -or
    $verified.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value -or
    $rules[0].IdentityReference.Value -ne $sid.Value -or $rules[0].AccessControlType -ne 'Allow' -or
    $rules[0].FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl -or
    $rules[0].IsInherited) { throw 'ACL verification failed.' }
if ($item.PSIsContainer -and $rules[0].InheritanceFlags -ne ([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit)) { throw 'Directory inheritance verification failed.' }
Write-Output 'WML-ACL-OK'
'''


def apply_current_user_acl(path: Path) -> None:
    _require_windows()
    path = Path(path).absolute()
    reject_private_links(path)
    env = {**os.environ, 'WML_ACL_TARGET': str(path)}
    # Never interpolate a filesystem path into executable PowerShell text.
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    try:
        result = subprocess.run(
            [str(powershell), '-NoProfile', '-NonInteractive', '-Command', _ACL_SCRIPT],
            capture_output=True, text=True, check=False, timeout=20, env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('failed to protect private path ACL') from exc
    if result.returncode != 0 or result.stdout.strip() != 'WML-ACL-OK':
        raise RuntimeError('failed to verify private path ACL')


@dataclass(frozen=True)
class KeyStoreMetadata:
    profile_id: str
    account_fingerprint: str
    layout_fingerprint: str
    schema_fingerprint: str
    database_paths_fingerprint: str
    validated_at: str
    database_count: int


class WindowsKeyStore:
    def __init__(
        self,
        path: Path,
        protect: Callable[[bytes], bytes] = protect_current_user,
        unprotect: Callable[[bytes], bytes] = unprotect_current_user,
        acl: Callable[[Path], None] = apply_current_user_acl,
    ):
        self.path = path
        self._protect = protect
        self._unprotect = unprotect
        self._acl = acl

    def save(
        self,
        *,
        profile_id: str,
        account_fingerprint: str,
        layout_fingerprint: str,
        schema_fingerprint: str,
        keys: dict[str, str | dict[str, str]],
    ) -> KeyStoreMetadata:
        normalized: dict[str, dict[str, str]] = {}
        for relative, key_value in keys.items():
            clean_relative = Path(relative).as_posix().lstrip("/")
            if ".." in Path(clean_relative).parts:
                raise ValueError("key mapping path must stay below the selected account")
            entry = (
                {"encryption_key": key_value}
                if isinstance(key_value, str)
                else dict(key_value)
            )
            raw_key = bytes.fromhex(str(entry.get("encryption_key", "")))
            if len(raw_key) != 32:
                raise ValueError("every validated database key must be 32 bytes")
            hmac_key = bytes.fromhex(str(entry.get("hmac_key", "")))
            if not 16 <= len(hmac_key) <= 128:
                raise ValueError("validated database HMAC key length is invalid")
            normalized[clean_relative] = {
                "encryption_key": raw_key.hex(),
                "hmac_key": hmac_key.hex(),
            }
        validated_at = datetime.now(timezone.utc).isoformat()
        paths_payload = json.dumps(
            sorted(normalized), ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        database_paths_fingerprint = hashlib.sha256(paths_payload).hexdigest()
        payload = json.dumps(
            {
                "format": 1,
                "profile_id": profile_id,
                "account_fingerprint": account_fingerprint,
                "layout_fingerprint": layout_fingerprint,
                "schema_fingerprint": schema_fingerprint,
                "database_paths_fingerprint": database_paths_fingerprint,
                "validated_at": validated_at,
                "keys": normalized,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        sealed = self._protect(payload)
        reject_private_links(self.path.absolute())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._acl(self.path.parent)
        fd, temporary_name = tempfile.mkstemp(prefix='keys-', suffix='.tmp', dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            self._acl(temporary)
            with os.fdopen(fd, 'wb') as handle:
                fd = -1
                handle.write(DPAPI_HEADER + sealed)
                handle.flush()
                os.fsync(handle.fileno())
            reject_private_links(self.path.absolute())
            temporary.replace(self.path)
        finally:
            if fd != -1:
                os.close(fd)
            temporary.unlink(missing_ok=True)
        return KeyStoreMetadata(
            profile_id=profile_id,
            account_fingerprint=account_fingerprint,
            layout_fingerprint=layout_fingerprint,
            schema_fingerprint=schema_fingerprint,
            database_paths_fingerprint=database_paths_fingerprint,
            validated_at=validated_at,
            database_count=len(normalized),
        )

    def load(self) -> dict:
        raw = self.path.read_bytes()
        if not raw.startswith(DPAPI_HEADER):
            raise RuntimeError("unsupported protected key-store format")
        payload = json.loads(self._unprotect(raw[len(DPAPI_HEADER) :]).decode("utf-8"))
        if payload.get("format") != 1 or not isinstance(payload.get("keys"), dict):
            raise RuntimeError("invalid protected key-store payload")
        return payload

    def metadata(self) -> KeyStoreMetadata | None:
        if not self.path.exists():
            return None
        payload = self.load()
        return KeyStoreMetadata(
            profile_id=str(payload.get("profile_id", "")),
            account_fingerprint=str(payload.get("account_fingerprint", "")),
            layout_fingerprint=str(payload.get("layout_fingerprint", "")),
            schema_fingerprint=str(payload.get("schema_fingerprint", "")),
            database_paths_fingerprint=str(payload.get("database_paths_fingerprint", "")),
            validated_at=str(payload.get("validated_at", "")),
            database_count=len(payload.get("keys", {})),
        )
