from __future__ import annotations

import json
import os
import plistlib
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from .config import Settings
from .models import DecoderMessage
from .service import OrganizerService, iso, now_utc


def _wechat_version(app_path: Path) -> tuple[str | None, str | None]:
    plist_path = app_path / "Contents/Info.plist"
    if not plist_path.exists():
        return None, None
    with plist_path.open("rb") as handle:
        data = plistlib.load(handle)
    return data.get("CFBundleShortVersionString"), data.get("CFBundleVersion")


def _version_supported(current: str | None, maximum: str) -> bool:
    if not current:
        return False
    try:
        return Version(current) <= Version(maximum)
    except InvalidVersion:
        return False


def _wechat_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-x", "WeChat"], capture_output=True, text=True, check=False, timeout=3
    )
    return result.returncode == 0


def _discover_profiles(root: Path) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    if not root.exists():
        return profiles
    candidates = list(root.glob("*/Message"))
    candidates.extend(root.glob("*/db_storage/message"))
    if root.name in {"Message", "message"}:
        candidates.append(root)
    for message_dir in sorted(set(candidates)):
        databases = sorted(message_dir.glob("msg_*.db"))
        databases.extend(sorted(message_dir.glob("message_*.db")))
        wal_files = sorted(message_dir.glob("msg_*.db-wal"))
        wal_files.extend(sorted(message_dir.glob("message_*.db-wal")))
        if databases:
            profile_dir = message_dir.parent.parent if message_dir.name == "message" else message_dir.parent
            profiles.append(
                {
                    "profile_id": profile_dir.name,
                    "message_dir": str(message_dir),
                    "database_count": len(databases),
                    "wal_count": len(wal_files),
                }
            )
    return profiles


class MacEnvironmentProbe:
    def __init__(self, settings: Settings):
        self.settings = settings

    def inspect(self) -> dict[str, Any]:
        version, build = _wechat_version(self.settings.wechat_app_path)
        profiles = _discover_profiles(self.settings.wechat_data_root)
        command = self.settings.decoder_command
        executable = shutil.which(command[0]) if command else None
        version_supported = _version_supported(version, self.settings.max_verified_wechat_version)
        decoder_allowed = bool(
            executable and (version_supported or self.settings.allow_unverified_decoder)
        )
        blockers: list[str] = []
        if not self.settings.wechat_app_path.exists():
            blockers.append("未找到 Mac 微信应用")
        if not _wechat_running():
            blockers.append("Mac 微信当前未运行")
        if not profiles:
            blockers.append("未发现 Message/msg_*.db 数据分片")
        if not executable:
            blockers.append("未安装解码适配器命令")
        if version and not version_supported and not self.settings.allow_unverified_decoder:
            blockers.append(
                f"微信 {version} 超出当前已验证适配范围 ≤ {self.settings.max_verified_wechat_version}"
            )
        return {
            "platform": "macOS",
            "wechat": {
                "installed": self.settings.wechat_app_path.exists(),
                "running": _wechat_running(),
                "version": version,
                "build": build,
                "app_path": str(self.settings.wechat_app_path),
            },
            "data": {
                "root": str(self.settings.wechat_data_root),
                "profiles": profiles,
                "profile_count": len(profiles),
                "database_count": sum(p["database_count"] for p in profiles),
                "wal_count": sum(p["wal_count"] for p in profiles),
            },
            "decoder": {
                "command": list(command),
                "executable": executable,
                "installed": bool(executable),
                "version_supported": version_supported,
                "allowed": decoder_allowed,
                "max_verified_wechat_version": self.settings.max_verified_wechat_version,
                "override_enabled": self.settings.allow_unverified_decoder,
            },
            "blockers": blockers,
            "can_observe_wal": bool(profiles),
            "can_decode": decoder_allowed,
            "probed_at": iso(now_utc()),
        }


class DecoderAdapter:
    def __init__(self, settings: Settings, source_kind_prefix: str = "mac"):
        self.settings = settings
        self.source_kind_prefix = source_kind_prefix
        self.last_meta: dict[str, Any] = {}

    def fetch(
        self,
        groups: tuple[str, ...] = (),
        history_groups: tuple[str, ...] = (),
        history_days: int = 7,
        high_water: dict[str, int] | None = None,
    ) -> list[DecoderMessage]:
        if not self.settings.decoder_command:
            return []
        last_error = ""
        payload: Any = None
        retry_delays = (0.15, 0.30, 0.60)
        for attempt in range(len(retry_delays) + 1):
            result = subprocess.run(
                list(self.settings.decoder_command),
                capture_output=True,
                text=True,
                check=False,
                timeout=120 if history_groups else 30,
                env={
                    **os.environ,
                    "NO_COLOR": "1",
                    "WML_TARGET_GROUPS_JSON": json.dumps(groups, ensure_ascii=False),
                    "WML_HISTORY_GROUPS_JSON": json.dumps(history_groups, ensure_ascii=False),
                    "WML_HISTORY_DAYS": str(history_days),
                    "WML_HIGH_WATER_JSON": json.dumps(high_water or {}, ensure_ascii=False),
                },
            )
            if result.returncode == 0:
                try:
                    payload = json.loads(result.stdout)
                    break
                except json.JSONDecodeError as exc:
                    last_error = f"decoder returned invalid JSON: {exc}"
            else:
                last_error = (result.stderr or result.stdout).strip()[-500:]
                last_error = last_error or f"decoder exited {result.returncode}"
            if attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])
        if payload is None:
            raise RuntimeError(last_error or "decoder failed")
        raw_items = payload.get("messages", []) if isinstance(payload, dict) else payload
        self.last_meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        history_group_set = set(history_groups)
        items: list[DecoderMessage] = []
        for raw in raw_items:
            if not isinstance(raw, dict) or not raw.get("is_group", True):
                continue
            timestamp = raw.get("timestamp")
            chat_name = str(raw.get("chat") or raw.get("chat_name") or raw.get("username") or "")
            if (
                timestamp is not None
                and chat_name not in history_group_set
                and float(timestamp) <= self.settings.decoder_baseline_epoch
            ):
                continue
            when = (
                datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
                if timestamp is not None
                else raw.get("source_time", iso(now_utc()))
            )
            username = str(raw.get("username") or raw.get("chat_username") or "")
            source_id = raw.get("source_id")
            if not source_id:
                source_id = f"{username}:{timestamp}:{raw.get('last_message', raw.get('content', ''))}"
            items.append(
                DecoderMessage(
                    source_id=str(source_id),
                    chat_name=chat_name or username,
                    sender=str(raw.get("sender") or raw.get("sender_name") or "未知成员"),
                    content=str(raw.get("last_message") or raw.get("content") or ""),
                    message_type=str(raw.get("msg_type") or raw.get("message_type") or "text"),
                    source_time=when,
                    is_group=bool(raw.get("is_group", True)),
                    is_at_me=bool(raw.get("is_at_me", False)),
                    source_kind=(
                        f"{self.source_kind_prefix}-history"
                        if chat_name in history_group_set
                        else f"{self.source_kind_prefix}-decoder"
                    ),
                )
            )
        return items


class MacListener:
    def __init__(self, settings: Settings, service: OrganizerService):
        self.settings = settings
        self.service = service
        self.probe = MacEnvironmentProbe(settings)
        self.decoder = DecoderAdapter(settings)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._signatures: dict[str, tuple[int, int]] = {}
        self._history_retry_after = 0.0
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
            self._thread = threading.Thread(target=self._run, name="mac-wechat-listener", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread:
            thread.join(timeout=5)
        self.service.update_listener_state(
            state="stopped", detail="监听服务已停止", last_probe_at=iso(now_utc())
        )
        return self.status()

    def _wal_files(self, probe: dict[str, Any]) -> list[Path]:
        paths: list[Path] = []
        for profile in probe["data"]["profiles"]:
            paths.extend(Path(profile["message_dir"]).glob("msg_*.db-wal"))
            paths.extend(Path(profile["message_dir"]).glob("message_*.db-wal"))
        return sorted(paths)

    @staticmethod
    def _signature(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    def _changed(self, paths: list[Path]) -> bool:
        changed = bool(paths and not self._signatures)
        current: dict[str, tuple[int, int]] = {}
        for path in paths:
            try:
                signature = self._signature(path)
            except FileNotFoundError:
                continue
            current[str(path)] = signature
            if self._signatures and self._signatures.get(str(path)) != signature:
                changed = True
        self._signatures = current
        return changed

    def _run(self) -> None:
        self.service.update_listener_state(state="probing", detail="正在探测 Mac 微信与消息分片")
        while not self._stop.is_set():
            if time.monotonic() >= self._next_cleanup_at:
                self.service.cleanup_expired()
                self._next_cleanup_at = time.monotonic() + 3600
            probe = self.probe.inspect()
            now = iso(now_utc())
            wal_changed = self._changed(self._wal_files(probe))
            state = self.service.listener_state()
            updates: dict[str, Any] = {"last_probe_at": now}
            if wal_changed:
                updates["last_wal_activity_at"] = now
                updates["wal_event_count"] = int(state["wal_event_count"]) + 1
            if not probe["can_observe_wal"]:
                updates |= {"state": "blocked", "detail": "未发现可观察的微信消息分片"}
            elif not probe["can_decode"]:
                updates |= {
                    "state": "observe_only",
                    "detail": "已监听真实 WAL 活动；解码适配器未通过兼容性门禁",
                }
            else:
                updates |= {"state": "listening", "detail": "WAL 监听与增量解码均已启用"}
                groups = tuple(self.service.get_settings()["groups"])
                pending_history = self.service.pending_history_groups(groups)
                history_groups = (
                    pending_history if pending_history and time.monotonic() >= self._history_retry_after else ()
                )
                if wal_changed or history_groups:
                    try:
                        if history_groups:
                            self.service.update_listener_state(
                                state="importing_history",
                                detail=f"正在首次导入 {len(history_groups)} 个指定群的本机历史消息",
                                last_probe_at=now,
                            )
                        retention_days = int(self.service.get_settings()["retention_days"])
                        messages = self.decoder.fetch(
                            groups,
                            history_groups,
                            retention_days,
                            high_water=self.service.message_high_water(groups),
                        )
                        retention_cutoff = now_utc().timestamp() - (
                            int(self.service.get_settings()["retention_days"]) * 86400
                        )
                        messages = [
                            message
                            for message in messages
                            if message.source_time.timestamp() >= retention_cutoff
                        ]
                        group_errors = self.decoder.last_meta.get("group_errors", {})
                        imported_total = 0
                        for group in groups:
                            group_messages = [message for message in messages if message.chat_name == group]
                            summary = self.service.ingest_many(group_messages)
                            imported_total += int(summary["inserted"])
                            if group in history_groups and group not in group_errors:
                                self.service.mark_history_imported(
                                    group, len(group_messages), int(summary["inserted"])
                                )
                        updates["last_decode_at"] = now
                        if history_groups:
                            updates["detail"] = (
                                f"最近 {retention_days} 天历史导入完成，"
                                f"本次新增 {imported_total} 条；WAL 增量监听已启用"
                            )
                            self._history_retry_after = 0.0
                    except Exception as exc:
                        updates["state"] = "decoder_error"
                        updates["detail"] = f"增量解码失败：{str(exc)[:240]}"
                        updates["decode_error_count"] = int(state["decode_error_count"]) + 1
                        if history_groups:
                            self._history_retry_after = time.monotonic() + 30
            self.service.update_listener_state(**updates)
            self._stop.wait(self.settings.poll_interval_seconds)
