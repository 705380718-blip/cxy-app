from __future__ import annotations

import ctypes
import hashlib
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..config import Settings
from ..mac_probe import DecoderAdapter
from ..service import OrganizerService, iso, now_utc
from .windows_profiles import (
    database_paths_fingerprint,
    layout_fingerprint,
    load_profiles,
    match_profile,
    required_key_paths,
)
from .windows_security import WindowsKeyStore


class VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", ctypes.c_uint32),
        ("dwStrucVersion", ctypes.c_uint32),
        ("dwFileVersionMS", ctypes.c_uint32),
        ("dwFileVersionLS", ctypes.c_uint32),
        ("dwProductVersionMS", ctypes.c_uint32),
        ("dwProductVersionLS", ctypes.c_uint32),
        ("dwFileFlagsMask", ctypes.c_uint32),
        ("dwFileFlags", ctypes.c_uint32),
        ("dwFileOS", ctypes.c_uint32),
        ("dwFileType", ctypes.c_uint32),
        ("dwFileSubtype", ctypes.c_uint32),
        ("dwFileDateMS", ctypes.c_uint32),
        ("dwFileDateLS", ctypes.c_uint32),
    ]


def windows_file_version(path: Path) -> tuple[str | None, str | None]:
    if not path.exists() or not hasattr(ctypes, "windll"):
        return None, None
    version_dll = ctypes.windll.version
    version_dll.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    version_dll.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
    version_dll.GetFileVersionInfoW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    version_dll.GetFileVersionInfoW.restype = ctypes.c_int
    version_dll.VerQueryValueW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint),
    ]
    version_dll.VerQueryValueW.restype = ctypes.c_int
    handle = ctypes.c_ulong(0)
    size = version_dll.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle))
    if not size:
        return None, None
    buffer = ctypes.create_string_buffer(size)
    if not version_dll.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None, None
    pointer = ctypes.c_void_p()
    length = ctypes.c_uint()
    if not version_dll.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        return None, None
    if length.value < ctypes.sizeof(VS_FIXEDFILEINFO):
        return None, None
    values = ctypes.cast(pointer, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
    if values.dwSignature != 0xFEEF04BD:
        return None, None
    major = values.dwFileVersionMS >> 16
    minor = values.dwFileVersionMS & 0xFFFF
    patch = values.dwFileVersionLS >> 16
    build = values.dwFileVersionLS & 0xFFFF
    return f"{major}.{minor}.{patch}", str(build)


def windows_wechat_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    output = result.stdout.lower()
    return "weixin.exe" in output or "wechat.exe" in output


def discover_windows_accounts(root: Path) -> list[Path]:
    candidates: set[Path] = set()
    if (root / "db_storage").is_dir():
        candidates.add(root)
    if root.is_dir():
        for db_storage in root.glob("*/db_storage"):
            if db_storage.is_dir():
                candidates.add(db_storage.parent)
    return sorted(candidates, key=lambda item: item.name.lower())


def account_fingerprint(account: Path) -> str:
    return hashlib.sha256(str(account.resolve()).lower().encode("utf-8")).hexdigest()


def account_files(account: Path) -> list[Path]:
    db_root = account / "db_storage"
    if not db_root.exists():
        return []
    return sorted(
        path
        for path in db_root.rglob("*")
        if path.is_file()
        and (
            path.name.endswith(".db")
            or path.name.endswith(".db-wal")
            or path.name.endswith(".db-shm")
        )
    )


class WindowsEnvironmentProbe:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _selected_account(self, accounts: list[Path]) -> Path | None:
        if self.settings.windows_account_id:
            return next(
                (path for path in accounts if path.name == self.settings.windows_account_id), None
            )
        return accounts[0] if len(accounts) == 1 else None

    def inspect(self) -> dict[str, Any]:
        version, build = windows_file_version(self.settings.wechat_app_path)
        accounts = discover_windows_accounts(self.settings.wechat_data_root)
        selected = self._selected_account(accounts)
        files = account_files(selected) if selected else []
        databases = [path for path in files if path.name.endswith(".db")]
        wal_files = [path for path in files if path.name.endswith(".db-wal")]
        shm_files = [path for path in files if path.name.endswith(".db-shm")]
        layout = layout_fingerprint(selected) if selected else ""
        blocker_details: list[dict[str, str]] = []

        def block(code: str, message: str, action: str) -> None:
            blocker_details.append({"code": code, "message": message, "action": action})

        if not self.settings.wechat_app_path.exists():
            block("wechat_not_found", "未找到 Windows 微信程序", "设置 WML_WECHAT_APP 为实际 exe 路径")
        running = windows_wechat_running()
        if not running:
            block("wechat_not_running", "Windows 微信当前未运行", "登录微信后重新探测")
        if not accounts:
            block("account_not_found", "未发现含 db_storage 的微信账号目录", "设置 WML_WECHAT_DATA_ROOT")
        elif len(accounts) > 1 and not self.settings.windows_account_id:
            block("account_selection_required", "发现多个微信账号，已禁止自动合并", "设置 WML_WINDOWS_ACCOUNT_ID")
        elif self.settings.windows_account_id and selected is None:
            block("account_selection_invalid", "配置的微信账号目录不存在", "重新设置 WML_WINDOWS_ACCOUNT_ID")
        if selected and not databases:
            block("database_not_found", "已选账号下未发现数据库分片", "确认微信已登录并产生本地消息")

        profile = None
        profile_error = ""
        try:
            profiles = load_profiles(self.settings.windows_profiles_path)
            profile = match_profile(profiles, version, build, layout)
        except Exception as exc:
            profile_error = str(exc)[:200]
            block("profile_invalid", "Windows 解码配置文件无效", "修复配置后重新探测")
        if not profile and not profile_error:
            block(
                "build_not_verified",
                "当前微信版本、构建号与数据布局不在已验证清单",
                "导出脱敏诊断并完成该版本适配",
            )

        key_metadata = None
        key_error = ""
        if self.settings.windows_key_store_path:
            try:
                key_metadata = WindowsKeyStore(self.settings.windows_key_store_path).metadata()
            except Exception as exc:
                key_error = str(exc)[:160]
                block("key_store_unreadable", "当前用户无法读取受保护密钥", "重新运行首次密钥准备")
        if profile and not key_metadata:
            block("keys_not_prepared", "尚未准备并验证当前版本的数据库密钥", "运行 1-首次密钥准备.cmd")
        selected_fingerprint = account_fingerprint(selected) if selected else ""
        if profile and key_metadata:
            if key_metadata.profile_id != profile.profile_id:
                block("key_profile_mismatch", "密钥与当前解码配置不匹配", "重新运行首次密钥准备")
            if key_metadata.account_fingerprint != selected_fingerprint:
                block("key_account_mismatch", "密钥不属于当前选择的微信账号", "选择正确账号后重新准备密钥")
            if key_metadata.layout_fingerprint != layout:
                block("key_layout_mismatch", "数据库布局已变化，密钥映射需要重新验证", "重新运行首次密钥准备")
            if key_metadata.schema_fingerprint != profile.schema_fingerprint:
                block("key_schema_mismatch", "已验证 schema 与当前配置不匹配", "停止解码并重新适配")
            current_paths_fingerprint = database_paths_fingerprint(
                required_key_paths(selected, profile)
            )
            if key_metadata.database_paths_fingerprint != current_paths_fingerprint:
                block("key_coverage_mismatch", "数据库分片已变化，密钥覆盖范围需要重新验证", "重新运行首次密钥准备")
        executable_available = bool(
            self.settings.decoder_command
            and (
                Path(self.settings.decoder_command[0]).exists()
                or shutil.which(self.settings.decoder_command[0])
            )
        )
        if profile and key_metadata and not executable_available:
            block("decoder_missing", "未找到 Windows 解码器运行时", "重新构建或修复本地运行包")

        blocking_codes = {
            "wechat_not_found",
            "wechat_not_running",
            "account_not_found",
            "account_selection_required",
            "account_selection_invalid",
            "database_not_found",
            "profile_invalid",
            "build_not_verified",
            "keys_not_prepared",
            "key_store_unreadable",
            "key_profile_mismatch",
            "key_account_mismatch",
            "key_layout_mismatch",
            "key_schema_mismatch",
            "key_coverage_mismatch",
            "decoder_missing",
        }
        can_observe = bool(selected and databases)
        can_decode = can_observe and not any(
            item["code"] in blocking_codes for item in blocker_details
        )
        return {
            "platform": "Windows",
            "platform_code": "windows",
            "wechat": {
                "installed": self.settings.wechat_app_path.exists(),
                "running": running,
                "version": version,
                "build": build,
                "executable_name": self.settings.wechat_app_path.name,
            },
            "data": {
                "profile_count": len(accounts),
                "selected": bool(selected),
                "selected_account_fingerprint": selected_fingerprint[:12] if selected else "",
                "database_count": len(databases),
                "wal_count": len(wal_files),
                "shm_count": len(shm_files),
                "layout_fingerprint": layout[:16] if layout else "",
                "profiles": [
                    {
                        "profile_id": selected_fingerprint[:12],
                        "database_count": len(databases),
                        "wal_count": len(wal_files),
                    }
                ]
                if selected
                else [],
            },
            "decoder": {
                "installed": executable_available,
                "allowed": can_decode,
                "version_supported": bool(profile),
                "profile_id": profile.profile_id if profile else "",
                "profile_exact_match": bool(profile),
                "key_prepared": bool(key_metadata),
                "key_validated_at": key_metadata.validated_at if key_metadata else None,
                "validated_database_count": key_metadata.database_count if key_metadata else 0,
                "schema_fingerprint": (
                    key_metadata.schema_fingerprint[:16] if key_metadata else ""
                ),
                "override_enabled": False,
                "profile_error": profile_error,
                "key_error": key_error,
            },
            "blockers": [item["message"] for item in blocker_details],
            "blocker_details": blocker_details,
            "can_observe_wal": can_observe,
            "can_decode": can_decode,
            "probed_at": iso(now_utc()),
        }


class WindowsListener:
    def __init__(self, settings: Settings, service: OrganizerService):
        self.settings = settings
        self.service = service
        self.probe = WindowsEnvironmentProbe(settings)
        self.decoder = DecoderAdapter(settings, "windows")
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._signatures: dict[str, tuple[int, int, int]] = {}
        self._history_retry_after = 0.0
        self._decode_retry_after = 0.0
        self._decoder_failure_state = ""
        self._decoder_failure_detail = ""
        self._next_cleanup_at = 0.0

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "thread_name": self._thread.name if self._thread else None,
        }

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="windows-wechat-listener", daemon=True
            )
            self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._thread and self._thread.is_alive():
            self.service.update_listener_state(
                state="stopping",
                detail="正在等待当前只读解码安全结束，不会再入库",
                last_probe_at=iso(now_utc()),
            )
        else:
            self.service.update_listener_state(
                state="stopped", detail="监听服务已停止", last_probe_at=iso(now_utc())
            )
        return self.status()

    def _watch_files(self) -> list[Path]:
        accounts = discover_windows_accounts(self.settings.wechat_data_root)
        selected = self.probe._selected_account(accounts)
        return account_files(selected) if selected else []

    def _changed(self, paths: list[Path]) -> bool:
        current: dict[str, tuple[int, int, int]] = {}
        for path in paths:
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            current[str(path)] = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        changed = bool(current and not self._signatures) or current != self._signatures
        self._signatures = current
        return changed

    def _run(self) -> None:
        self.service.update_listener_state(
            state="probing", detail="正在探测 Windows 微信、账号与数据库分片"
        )
        while not self._stop.is_set():
            if time.monotonic() >= self._next_cleanup_at:
                self.service.cleanup_expired()
                self._next_cleanup_at = time.monotonic() + 3600
            probe = self.probe.inspect()
            now = iso(now_utc())
            changed = self._changed(self._watch_files())
            state = self.service.listener_state()
            updates: dict[str, Any] = {"last_probe_at": now}
            if changed:
                updates["last_wal_activity_at"] = now
                updates["wal_event_count"] = int(state["wal_event_count"]) + 1
            if not probe["can_observe_wal"]:
                updates |= {"state": "blocked", "detail": "未发现可观察的 Windows 微信数据库"}
            elif not probe["can_decode"]:
                updates |= {
                    "state": "observe_only",
                    "detail": "已观察 DB/WAL/SHM 变化；版本、密钥或 schema 门禁尚未通过",
                }
            else:
                retry_due = bool(
                    self._decoder_failure_state
                    and time.monotonic() >= self._decode_retry_after
                )
                if self._decoder_failure_state and not retry_due:
                    updates |= {
                        "state": self._decoder_failure_state,
                        "detail": self._decoder_failure_detail,
                    }
                else:
                    updates |= {
                        "state": "listening",
                        "detail": "Windows 只读快照与增量解码已启用",
                    }
                groups = tuple(self.service.get_settings()["groups"])
                pending_history = self.service.pending_history_groups(groups)
                history_groups = (
                    pending_history
                    if pending_history and time.monotonic() >= self._history_retry_after
                    else ()
                )
                if changed or history_groups or retry_due:
                    try:
                        retention_days = int(self.service.get_settings()["retention_days"])
                        high_water = self.service.message_high_water(groups)
                        messages = self.decoder.fetch(
                            groups, history_groups, retention_days, high_water=high_water
                        )
                        if self._stop.is_set():
                            break
                        cutoff = now_utc().timestamp() - retention_days * 86400
                        messages = [item for item in messages if item.source_time.timestamp() >= cutoff]
                        group_errors = self.decoder.last_meta.get("group_errors", {})
                        inserted = 0
                        for group in groups:
                            group_messages = [item for item in messages if item.chat_name == group]
                            summary = self.service.ingest_many(group_messages)
                            inserted += int(summary["inserted"])
                            if group in history_groups and group not in group_errors:
                                self.service.mark_history_imported(
                                    group, len(group_messages), int(summary["inserted"])
                                )
                        if group_errors:
                            failed_groups = [group for group in groups if group in group_errors]
                            self._decoder_failure_state = "partial_blocked"
                            self._decoder_failure_detail = (
                                f"{len(failed_groups)} 个目标群未唯一匹配，30 秒后重试："
                                + "、".join(failed_groups[:3])
                            )
                            updates |= {
                                "state": self._decoder_failure_state,
                                "detail": self._decoder_failure_detail,
                            }
                            self._decode_retry_after = time.monotonic() + 30
                            self._history_retry_after = self._decode_retry_after
                        else:
                            self._decoder_failure_state = ""
                            self._decoder_failure_detail = ""
                            self._decode_retry_after = 0.0
                            updates["state"] = "listening"
                            updates["last_decode_at"] = now
                        if history_groups and not group_errors:
                            updates["detail"] = f"最近 {retention_days} 天历史处理完成，本次新增 {inserted} 条"
                            self._history_retry_after = 0.0
                    except Exception as exc:
                        error_code = type(exc).__name__
                        self._decoder_failure_state = "decoder_error"
                        self._decoder_failure_detail = (
                            f"Windows 增量解码失败（{error_code}），30 秒后重试"
                        )
                        self._decode_retry_after = time.monotonic() + 30
                        updates["state"] = self._decoder_failure_state
                        updates["detail"] = self._decoder_failure_detail
                        updates["decode_error_count"] = int(state["decode_error_count"]) + 1
                        self._history_retry_after = self._decode_retry_after
            self.service.update_listener_state(**updates)
            self._stop.wait(self.settings.poll_interval_seconds)
        self.service.update_listener_state(
            state="stopped", detail="监听服务已停止", last_probe_at=iso(now_utc())
        )
