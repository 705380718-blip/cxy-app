from __future__ import annotations

from datetime import datetime, timezone
import json
import ssl
from typing import Any
import urllib.error
import urllib.request

from app.db import DEFAULT_AGENT_PROFILE, DEFAULT_MODEL_CONFIG, get_connection, init_db


PROVIDER_LABELS = {
    "mock": "离线内置模型",
    "openai-compatible": "OpenAI Compatible",
    "openai": "OpenAI Compatible",
    "compatible": "OpenAI Compatible",
    "dashscope": "阿里百炼 / 通义千问",
    "deepseek": "DeepSeek",
    "moonshot": "Kimi / Moonshot",
    "zhipu": "智谱 GLM",
    "volcengine": "火山方舟 / 豆包",
    "qianfan": "百度千帆",
    "hunyuan": "腾讯混元",
    "siliconflow": "硅基流动",
    "lm-studio": "本地 LM Studio",
    "ollama": "本地 Ollama",
}

SECRET_PLACEHOLDER = "********"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def merged_model_config(value: dict[str, Any] | None = None) -> dict[str, Any]:
    config = {**DEFAULT_MODEL_CONFIG, **(value or {})}
    provider = str(config.get("provider") or "mock").lower()
    config["provider"] = provider
    config["provider_label"] = PROVIDER_LABELS.get(provider, str(config.get("provider_label") or provider))
    default_overrides = {
        item["capability"]: item for item in DEFAULT_MODEL_CONFIG["overrides"]
    }
    merged_overrides = []
    for item in config.get("overrides") or []:
        capability = item.get("capability", "")
        merged_overrides.append({**default_overrides.get(capability, {}), **item})
    seen = {item.get("capability") for item in merged_overrides}
    for capability, item in default_overrides.items():
        if capability not in seen:
            merged_overrides.append(item)
    config["overrides"] = merged_overrides
    config["has_api_key"] = bool(config.get("api_key"))
    return config


def get_model_config() -> dict[str, Any]:
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            "select value from app_meta where key = 'ai_model_config'"
        ).fetchone()
    if not row:
        return merged_model_config()
    try:
        return merged_model_config(json.loads(row["value"]))
    except json.JSONDecodeError:
        return merged_model_config()


def public_model_config(config: dict[str, Any]) -> dict[str, Any]:
    payload = merged_model_config(config)
    payload["api_key"] = SECRET_PLACEHOLDER if payload.get("api_key") else ""
    payload["has_api_key"] = bool(config.get("api_key"))
    return payload


def resolve_secret_for_save(incoming: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(incoming)
    api_key = str(payload.get("api_key") or "")
    if api_key == SECRET_PLACEHOLDER:
        payload["api_key"] = (current or {}).get("api_key", "")
    return payload


def save_model_config(config: dict[str, Any]) -> dict[str, Any]:
    init_db()
    current = get_model_config()
    payload = merged_model_config(resolve_secret_for_save(config, current))
    with get_connection() as connection:
        connection.execute(
            """
            insert into app_meta (key, value)
            values ('ai_model_config', ?)
            on conflict(key) do update set value = excluded.value
            """,
            [json.dumps(payload, ensure_ascii=False)],
        )
        connection.commit()
    return payload


def merged_agent_profile(value: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {**DEFAULT_AGENT_PROFILE, **(value or {})}
    for key in ("responsibilities", "forbidden", "long_term_preferences", "proactive_reminders"):
        items = payload.get(key) or []
        if not isinstance(items, list):
            items = [str(items)]
        payload[key] = [str(item).strip() for item in items if str(item).strip()]
    for key in ("name", "role", "tone", "default_output_format", "memory_policy"):
        payload[key] = str(payload.get(key) or DEFAULT_AGENT_PROFILE.get(key) or "").strip()
    return payload


def get_agent_profile() -> dict[str, Any]:
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            "select value from app_meta where key = 'agent_profile'"
        ).fetchone()
    if not row:
        return merged_agent_profile()
    try:
        return merged_agent_profile(json.loads(row["value"]))
    except json.JSONDecodeError:
        return merged_agent_profile()


def save_agent_profile(profile: dict[str, Any]) -> dict[str, Any]:
    init_db()
    payload = merged_agent_profile(profile)
    with get_connection() as connection:
        connection.execute(
            """
            insert into app_meta (key, value)
            values ('agent_profile', ?)
            on conflict(key) do update set value = excluded.value
            """,
            [json.dumps(payload, ensure_ascii=False)],
        )
        connection.commit()
    return payload


def test_model_config(config: dict[str, Any]) -> dict[str, Any]:
    provider = str(config.get("provider") or "mock").lower()
    model = str(config.get("model") or "").strip()
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    api_key = str(config.get("api_key") or "").strip()
    verify_ssl = bool(config.get("verify_ssl", True))

    if provider == "mock":
        return {
            "status": "connected",
            "status_message": "离线内置模型已就绪，可用于本地上下文问答和规则抽取。",
            "last_tested_at": utc_now(),
        }
    if not model:
        return {
            "status": "failed",
            "status_message": "缺少模型名称。",
            "last_tested_at": utc_now(),
        }
    if provider == "ollama":
        if not base_url:
            base_url = "http://127.0.0.1:11434"
        request = urllib.request.Request(f"{base_url}/api/tags", method="GET")
    else:
        if not base_url:
            return {
                "status": "failed",
                "status_message": "缺少 OpenAI Compatible API 地址。",
                "last_tested_at": utc_now(),
            }
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        request = urllib.request.Request(f"{base_url}/models", headers=headers, method="GET")

    try:
        context = None
        if request.full_url.startswith("https://") and not verify_ssl:
            context = ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=8, context=context) as response:
            if response.status >= 400:
                raise urllib.error.HTTPError(
                    request.full_url,
                    response.status,
                    "模型服务返回错误",
                    response.headers,
                    None,
                )
        return {
            "status": "connected",
            "status_message": f"{model} 连通性测试通过。" + ("（已跳过 HTTPS 证书校验）" if context else ""),
            "last_tested_at": utc_now(),
        }
    except Exception as exc:
        message = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in message or "certificate verify failed" in message:
            message = (
                "连接失败：HTTPS 证书链校验失败。通常是公司网络代理、抓包工具或本机 Python 未信任根证书导致；"
                "可先安装/信任代理根证书，或在本地测试时关闭“校验 HTTPS 证书”。"
            )
        else:
            message = f"连接失败：{exc}"
        return {
            "status": "failed",
            "status_message": message,
            "last_tested_at": utc_now(),
        }
