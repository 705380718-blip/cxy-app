from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path | None = None) -> None:
    configured_path = os.getenv("WML_ENV_FILE", "").strip()
    env_path = path or (
        Path(configured_path).expanduser()
        if configured_path
        else PROJECT_ROOT / ".env"
    )
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def csv_values(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def bool_value(value: str, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    database_path: Path
    wechat_app_path: Path
    wechat_data_root: Path
    decoder_command: tuple[str, ...]
    decoder_baseline_epoch: int
    max_verified_wechat_version: str
    allow_unverified_decoder: bool
    poll_interval_seconds: float
    initial_groups: tuple[str, ...]
    initial_self_names: tuple[str, ...]
    runtime_platform: str = "macos"
    windows_profiles_path: Path | None = None
    windows_key_store_path: Path | None = None
    windows_snapshot_root: Path | None = None
    windows_account_id: str = ""

    @staticmethod
    def _default_wechat_root(user_home: Path) -> Path:
        return user_home / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"

    @staticmethod
    def _default_decoder_command(user_home: Path, wechat_root: Path) -> tuple[str, ...]:
        project_decoder = PROJECT_ROOT / "scripts/local_vault_decoder.py"
        keys_file = user_home / ".config/wechat-keys.json"
        vault = user_home / "Library/Application Support/wechat-group-organizer/private/live"
        db_candidates = sorted(wechat_root.glob("*/db_storage"))
        if not (project_decoder.exists() and keys_file.exists() and len(db_candidates) == 1):
            return ()
        return (
            os.getenv("WML_PYTHON", "python3"), str(project_decoder), "new-messages",
            "--db-base", str(db_candidates[0]), "--keys", str(keys_file),
            "--vault", str(vault), "--limit", "200",
        )

    @staticmethod
    def _windows_app_data(user_home: Path) -> Path:
        return Path(
            os.getenv(
                "LOCALAPPDATA",
                str(user_home / "AppData/Local"),
            )
        ) / "GroupChatOrganizer"

    @staticmethod
    def _default_windows_executable() -> Path:
        candidates = (
            Path(os.getenv("ProgramFiles", "C:/Program Files"))
            / "Tencent/WeChat/WeChat.exe",
            Path(os.getenv("ProgramFiles", "C:/Program Files"))
            / "Tencent/Weixin/Weixin.exe",
            Path(os.getenv("LOCALAPPDATA", "C:/Users/Public/AppData/Local"))
            / "Tencent/WeChat/WeChat.exe",
        )
        return next((path for path in candidates if path.exists()), candidates[0])

    @staticmethod
    def _default_windows_decoder_command(
        python_command: str,
        wechat_root: Path,
        profiles_path: Path,
        key_store_path: Path,
        snapshot_root: Path,
    ) -> tuple[str, ...]:
        decoder = PROJECT_ROOT / "scripts/windows_vault_decoder.py"
        if not decoder.exists():
            return ()
        return (
            python_command,
            str(decoder),
            "new-messages",
            "--wechat-root",
            str(wechat_root),
            "--profiles",
            str(profiles_path),
            "--keys",
            str(key_store_path),
            "--vault",
            str(snapshot_root),
            "--limit",
            "200",
        )

    @classmethod
    def from_env(cls) -> "Settings":
        load_env()
        user_home = Path.home()
        runtime_platform = os.getenv(
            "WML_PLATFORM", "windows" if sys.platform == "win32" else "macos"
        ).strip().lower()
        if runtime_platform not in {"macos", "windows"}:
            raise ValueError("WML_PLATFORM 仅支持 macos 或 windows")
        windows_app_data = cls._windows_app_data(user_home)
        windows_profiles_path = Path(
            os.getenv(
                "WML_WINDOWS_PROFILES_PATH",
                str(PROJECT_ROOT / "config/windows-decoder-profiles.json"),
            )
        ).expanduser()
        windows_key_store_path = Path(
            os.getenv(
                "WML_WINDOWS_KEY_STORE_PATH",
                str(windows_app_data / "private/keys.dpapi"),
            )
        ).expanduser()
        windows_snapshot_root = Path(
            os.getenv(
                "WML_WINDOWS_SNAPSHOT_ROOT",
                str(windows_app_data / "private/snapshots"),
            )
        ).expanduser()
        raw_db = Path(
            os.getenv(
                "WML_DATABASE_PATH",
                str(
                    windows_app_data / "data/listener.db"
                    if runtime_platform == "windows"
                    else user_home
                    / "Library/Application Support/群聊问题整理/data/mac-listener.db"
                ),
            )
        ).expanduser()
        default_wechat_root = (
            user_home / "Documents/xwechat_files"
            if runtime_platform == "windows"
            else cls._default_wechat_root(user_home)
        )
        wechat_data_root = Path(os.getenv("WML_WECHAT_DATA_ROOT", str(default_wechat_root)))
        raw_command = os.getenv("WML_DECODER_COMMAND")
        if raw_command is not None:
            try:
                command = tuple(str(item) for item in json.loads(raw_command))
            except (json.JSONDecodeError, TypeError):
                command = ()
        else:
            command = (
                cls._default_windows_decoder_command(
                    os.getenv("WML_PYTHON", sys.executable or "python"),
                    wechat_data_root,
                    windows_profiles_path,
                    windows_key_store_path,
                    windows_snapshot_root,
                )
                if runtime_platform == "windows"
                else cls._default_decoder_command(user_home, wechat_data_root)
            )
        settings = cls(
            host=os.getenv("WML_HOST", "127.0.0.1").strip(),
            port=int(os.getenv("WML_PORT", "8791")),
            database_path=raw_db if raw_db.is_absolute() else PROJECT_ROOT / raw_db,
            wechat_app_path=Path(
                os.getenv(
                    "WML_WECHAT_APP",
                    str(cls._default_windows_executable())
                    if runtime_platform == "windows"
                    else "/Applications/WeChat.app",
                )
            ),
            wechat_data_root=wechat_data_root,
            decoder_command=command,
            decoder_baseline_epoch=int(os.getenv("WML_DECODER_BASELINE_EPOCH", "0")),
            max_verified_wechat_version=os.getenv(
                "WML_MAX_VERIFIED_WECHAT_VERSION", "4.1.12"
            ).strip(),
            allow_unverified_decoder=bool_value(
                os.getenv("WML_ALLOW_UNVERIFIED_DECODER", "false")
            ),
            poll_interval_seconds=float(os.getenv("WML_POLL_INTERVAL", "0.5")),
            initial_groups=csv_values(os.getenv("WML_GROUPS", "请在后台填写群名")),
            initial_self_names=csv_values(os.getenv("WML_SELF_NAMES", "我")),
            runtime_platform=runtime_platform,
            windows_profiles_path=windows_profiles_path,
            windows_key_store_path=windows_key_store_path,
            windows_snapshot_root=windows_snapshot_root,
            windows_account_id=os.getenv("WML_WINDOWS_ACCOUNT_ID", "").strip(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("POC 仅允许绑定本机回环地址")
        if not 1 <= self.port <= 65535:
            raise ValueError("WML_PORT 必须是有效端口")
        if not 0.1 <= self.poll_interval_seconds <= 60:
            raise ValueError("WML_POLL_INTERVAL 必须为 0.1-60 秒")
        if self.runtime_platform not in {"macos", "windows"}:
            raise ValueError("runtime_platform 仅支持 macos 或 windows")
        if self.runtime_platform == "windows":
            app_root = self._windows_app_data(Path.home()).resolve()
            writable_paths = [
                self.database_path,
                self.windows_key_store_path,
                self.windows_snapshot_root,
            ]
            for path in writable_paths:
                if path is None:
                    raise ValueError("Windows 私有写入路径不能为空")
                resolved = path.resolve()
                if resolved != app_root and app_root not in resolved.parents:
                    raise ValueError("Windows 运行数据只能写入 GroupChatOrganizer 私有目录")
            wechat_root = self.wechat_data_root.resolve()
            if wechat_root == app_root or wechat_root in app_root.parents or app_root in wechat_root.parents:
                raise ValueError("工具私有目录不得与微信数据目录重叠")
            if self.wechat_data_root.is_symlink():
                raise ValueError("微信数据根目录不能是符号链接或重解析入口")


def ai_defaults() -> dict:
    """Non-secret model defaults; key is loaded only by the private backend store."""
    return {
        'enabled': bool_value(os.getenv('WML_AI_ENABLED', 'false')),
        'provider': os.getenv('WML_AI_PROVIDER', 'deepseek'),
        'base_url': os.getenv('WML_AI_BASE_URL', 'https://api.deepseek.com'),
        'model': os.getenv('WML_AI_MODEL', 'deepseek-flash'),
        'timeout_seconds': int(os.getenv('WML_AI_TIMEOUT_SECONDS', '60')),
        'max_output_tokens': int(os.getenv('WML_AI_MAX_OUTPUT_TOKENS', '4096')),
        'max_calls_per_day': int(os.getenv('WML_AI_MAX_CALLS_PER_DAY', '100')),
        'max_batch_messages': int(os.getenv('WML_AI_MAX_BATCH_MESSAGES', '80')),
        'max_input_chars': int(os.getenv('WML_AI_MAX_INPUT_CHARS', '18000')),
    }
