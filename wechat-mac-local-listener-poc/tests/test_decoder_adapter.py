from __future__ import annotations

import json
from types import SimpleNamespace

from app.mac_probe import DecoderAdapter


def test_decoder_adapter_retries_transient_failure(monkeypatch, settings):
    calls = iter(
        [
            SimpleNamespace(returncode=1, stdout="", stderr="snapshot changed"),
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"messages": []}),
                stderr="",
            ),
        ]
    )
    monkeypatch.setattr("app.mac_probe.subprocess.run", lambda *args, **kwargs: next(calls))
    monkeypatch.setattr("app.mac_probe.time.sleep", lambda _: None)

    assert DecoderAdapter(settings).fetch() == []


def test_decoder_adapter_passes_multiple_groups(monkeypatch, settings):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["groups"] = json.loads(kwargs["env"]["WML_TARGET_GROUPS_JSON"])
        captured["high_water"] = json.loads(kwargs["env"]["WML_HIGH_WATER_JSON"])
        return SimpleNamespace(returncode=0, stdout=json.dumps({"messages": []}), stderr="")

    monkeypatch.setattr("app.mac_probe.subprocess.run", fake_run)
    assert DecoderAdapter(settings).fetch(
        ("小组长", "产品群"), high_water={"小组长": 1786500000}
    ) == []
    assert captured["groups"] == ["小组长", "产品群"]
    assert captured["high_water"] == {"小组长": 1786500000}


def test_decoder_adapter_history_bypasses_incremental_baseline(monkeypatch, settings):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["history_groups"] = json.loads(kwargs["env"]["WML_HISTORY_GROUPS_JSON"])
        captured["history_days"] = kwargs["env"]["WML_HISTORY_DAYS"]
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "messages": [
                        {
                            "source_id": "old-message",
                            "chat": "小组长",
                            "sender": "成员",
                            "content": "历史消息",
                            "timestamp": 1,
                            "is_group": True,
                        }
                    ],
                    "meta": {"group_errors": {}},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("app.mac_probe.subprocess.run", fake_run)
    items = DecoderAdapter(settings).fetch(("小组长",), ("小组长",), 7)
    assert captured["history_groups"] == ["小组长"]
    assert captured["history_days"] == "7"
    assert len(items) == 1
    assert items[0].source_kind == "mac-history"
