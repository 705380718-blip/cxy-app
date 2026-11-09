from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    fake_app = tmp_path / "WeChat.app"
    info_dir = fake_app / "Contents"
    info_dir.mkdir(parents=True)
    (info_dir / "Info.plist").write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<plist version="1.0"><dict>'
        b'<key>CFBundleShortVersionString</key><string>4.1.11</string>'
        b'<key>CFBundleVersion</key><string>269111</string>'
        b'</dict></plist>'
    )
    message_dir = tmp_path / "wechat-data" / "profile-a" / "Message"
    message_dir.mkdir(parents=True)
    (message_dir / "msg_0.db").write_bytes(b"encrypted")
    (message_dir / "msg_0.db-wal").write_bytes(b"wal")
    return Settings(
        host="127.0.0.1",
        port=8791,
        database_path=tmp_path / "poc.db",
        wechat_app_path=fake_app,
        wechat_data_root=tmp_path / "wechat-data",
        decoder_command=("missing-wechat-decoder", "new-messages"),
        decoder_baseline_epoch=0,
        max_verified_wechat_version="4.1.8.100",
        allow_unverified_decoder=False,
        poll_interval_seconds=0.1,
        initial_groups=("POC测试群",),
        initial_self_names=("测试助手",),
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings, start_analysis_worker=False), base_url="http://127.0.0.1:8791") as value:
        yield value
