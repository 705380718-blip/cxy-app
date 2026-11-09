from __future__ import annotations

from pathlib import Path

from app.config import Settings, load_env


def test_load_env_uses_writable_runtime_file(monkeypatch, tmp_path: Path):
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("WML_PORT=18891\n", encoding="utf-8")
    monkeypatch.setenv("WML_ENV_FILE", str(runtime_env))
    monkeypatch.delenv("WML_PORT", raising=False)

    load_env()

    assert __import__("os").environ["WML_PORT"] == "18891"


def test_default_database_is_outside_app_bundle(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for name in (
        "WML_ENV_FILE",
        "WML_DATABASE_PATH",
        "WML_DECODER_COMMAND",
        "WML_PORT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.database_path == (
        tmp_path / "Library/Application Support/群聊问题整理/data/mac-listener.db"
    )
