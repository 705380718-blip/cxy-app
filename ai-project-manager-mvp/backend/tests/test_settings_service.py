import ssl
import urllib.error
import json

from fastapi.testclient import TestClient

from app.main import app
from app.db import get_connection
from app.services import assistant_service
from app.services import ai_adapter
from app.services import settings_service


def test_model_connectivity_ssl_error_has_actionable_message(monkeypatch):
    def raise_ssl_error(*args, **kwargs):
        raise urllib.error.URLError(
            ssl.SSLCertVerificationError("certificate verify failed: self-signed certificate in certificate chain")
        )

    monkeypatch.setattr(settings_service.urllib.request, "urlopen", raise_ssl_error)

    result = settings_service.test_model_config(
        {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "api_key": "test-key",
            "verify_ssl": True,
        }
    )

    assert result["status"] == "failed"
    assert "HTTPS 证书链校验失败" in result["status_message"]
    assert "关闭“校验 HTTPS 证书”" in result["status_message"]


def test_model_connectivity_can_skip_ssl_verification(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout=0, context=None):
        captured["context"] = context
        return FakeResponse()

    monkeypatch.setattr(settings_service.urllib.request, "urlopen", fake_urlopen)

    result = settings_service.test_model_config(
        {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "api_key": "test-key",
            "verify_ssl": False,
        }
    )

    assert result["status"] == "connected"
    assert captured["context"] is not None
    assert "已跳过 HTTPS 证书校验" in result["status_message"]


def test_assistant_uses_configured_openai_compatible_model(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "这是来自模型的自然回复，已结合项目上下文。"}}]},
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(request, timeout=0, context=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(assistant_service.urllib.request, "urlopen", fake_urlopen)
    settings_service.save_agent_profile(
        {
            "name": "小智",
            "role": "辅助项目经理完成项目管理，减轻重复工作量，辅助决策，主动提示风险",
            "tone": "理性，沉稳",
            "responsibilities": ["项目进度跟进", "及时提醒项目风险、进度等问题"],
            "forbidden": ["篡改项目信息", "将项目信息和人物信息发布到互联网"],
            "default_output_format": "飞书可展示的 Markdown 格式",
            "long_term_preferences": ["提醒和顾问型"],
            "proactive_reminders": ["项目风险", "每日待办", "任务进度逾期"],
            "memory_policy": "智能体画像与模型配置分离。",
        }
    )
    settings_service.save_model_config(
        {
            "provider": "deepseek",
            "provider_label": "DeepSeek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
            "api_key": "test-key",
            "verify_ssl": False,
            "temperature": 0.2,
        }
    )

    with get_connection() as connection:
        assistant_service.create_chat_message(connection, "gov", "项目驾驶舱", "user", "上一轮我说调研计划要输出为 Markdown")
        assistant_service.create_chat_message(connection, "gov", "项目驾驶舱", "assistant", "好的，我会记住这个输出格式要求。")
        connection.commit()
        result = assistant_service.answer_project_question(connection, "gov", "你好，你是什么模型？", "项目驾驶舱")

    assert result["source"] == "configured-model"
    assert result["answer"] == "这是来自模型的自然回复，已结合项目上下文。"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "deepseek-chat"
    message_text = "\n".join(item["content"] for item in captured["body"]["messages"])
    assert "你叫小智" in message_text
    assert "不是通用聊天 AI" in message_text
    assert "飞书可展示的 Markdown 格式" in message_text
    assert "上一轮我说调研计划要输出为 Markdown" in message_text


def test_agent_profile_persists_when_model_changes():
    client = TestClient(app)

    saved_agent = client.put(
        "/settings/agent-profile",
        json={
            "name": "小智",
            "role": "辅助项目经理完成项目管理",
            "tone": "理性，沉稳",
            "responsibilities": ["项目进度跟进", "辅助文档生成"],
            "forbidden": ["篡改项目信息", "将项目信息和人物信息发布到互联网"],
            "default_output_format": "飞书可展示的 Markdown 格式",
            "long_term_preferences": ["提醒和顾问型"],
            "proactive_reminders": ["项目风险", "每日待办", "任务进度逾期"],
            "memory_policy": "智能体画像、项目历史对话和项目数据保存在本地 SQLite 中，与底层模型配置分离。",
        },
    )
    assert saved_agent.status_code == 200

    config = client.get("/settings/model-config").json()
    config.update(
        {
            "provider": "deepseek",
            "provider_label": "DeepSeek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
            "api_key": "deepseek-secret",
        }
    )
    assert client.put("/settings/model-config", json=config).status_code == 200

    config = client.get("/settings/model-config").json()
    config.update(
        {
            "provider": "mock",
            "provider_label": "离线内置模型",
            "model": "local-project-assistant",
            "base_url": "",
            "api_key": "",
        }
    )
    assert client.put("/settings/model-config", json=config).status_code == 200

    agent = client.get("/settings/agent-profile")
    assert agent.status_code == 200
    payload = agent.json()
    assert payload["name"] == "小智"
    assert "项目进度跟进" in payload["responsibilities"]
    assert payload["default_output_format"] == "飞书可展示的 Markdown 格式"


def test_extraction_uses_saved_model_config(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "items": [
                                            {
                                                "item_type": "risk",
                                                "title": "供应商文档未到位",
                                                "description": "短信供应商文档未到位，可能影响评审。",
                                                "probability": "60%",
                                                "impact": "中",
                                                "response": "确认供应商交付时间",
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(request, timeout=0, context=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["context"] = context
        return FakeResponse()

    monkeypatch.setattr(ai_adapter.urllib.request, "urlopen", fake_urlopen)
    settings_service.save_model_config(
        {
            "provider": "deepseek",
            "provider_label": "DeepSeek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
            "api_key": "test-key",
            "verify_ssl": False,
            "temperature": 0.1,
        }
    )

    try:
        items = ai_adapter.extract_with_configured_model("风险：短信供应商文档未到位，可能影响评审。")
    finally:
        settings_service.save_model_config(
            {
                "provider": "mock",
                "provider_label": "离线内置模型",
                "model": "local-project-assistant",
                "base_url": "",
                "api_key": "",
                "verify_ssl": True,
                "temperature": 0.1,
            }
        )

    assert items[0]["item_type"] == "risk"
    assert items[0]["title"] == "供应商文档未到位"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "deepseek-chat"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["context"] is not None
