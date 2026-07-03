from __future__ import annotations

import json
import os
import re
import ssl
from datetime import datetime
from typing import Any
import urllib.request

from app.services.settings_service import get_model_config


SYSTEM_PROMPT = """
你是项目经理的信息归集助手。请从原文中提取 task、risk、demand、milestone 四类事项。
只返回 JSON：{"items":[...]}。每个 item 包含 item_type、title、description、owner、due_date、probability、impact、response。
due_date 使用 YYYY-MM-DD；未知字段返回空字符串。
"""

DOCUMENT_SYSTEM_PROMPT = """
你是项目交付文档生成助手。请把系统提供的 Markdown 草稿优化为可交付文档正文。
必须只返回 Markdown，不要返回解释、代码块围栏或 JSON。
要求：
1. 严格以项目上下文为准，修正原始资料中的旧项目名、旧地点、旧客户和旧日期。
2. 不保留“待补充”“XXX”“示例”等模板痕迹；缺信息时写成可执行的待确认项。
3. 删除重复章节内容；父章节有子章节时只做概述，具体内容放到最匹配的子章节。
4. 保留 Markdown 表格，必要时拆分重复表格。
5. 若用户原始资料中已有表格，优先保留其中的业务数据，并只修正项目名、地点、客户、日期等上下文冲突信息。
6. 输出章节应贴合模板标题，不要随意新增与模板无关的大章节；模板父章节只写短概述，子章节承载明细。
7. 表格表头要稳定、语义清晰，便于后续导出阶段映射到 Word 模板表格。
8. 输出要适合项目经理直接导出 Word。
"""

MODEL_PROVIDERS = {
    "openai",
    "openai-compatible",
    "compatible",
    "deepseek",
    "dashscope",
    "moonshot",
    "zhipu",
    "volcengine",
    "qianfan",
    "hunyuan",
    "siliconflow",
    "lm-studio",
}


def normalize_items(payload: object) -> list[dict[str, str]]:
    if isinstance(payload, dict):
        items = payload.get("items", [])
    else:
        items = payload
    if not isinstance(items, list):
        return []
    normalized = []
    for item in items:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        normalized.append(
            {
                "item_type": normalize_item_type(str(item.get("item_type") or "task")),
                "title": str(item.get("title") or ""),
                "description": str(item.get("description") or ""),
                "owner": str(item.get("owner") or ""),
                "due_date": str(item.get("due_date") or ""),
                "probability": str(item.get("probability") or ""),
                "impact": str(item.get("impact") or ""),
                "response": str(item.get("response") or ""),
            }
        )
    return normalized


def normalize_item_type(value: str) -> str:
    lowered = value.strip().lower()
    mapping = {
        "task": "task",
        "任务": "task",
        "risk": "risk",
        "风险": "risk",
        "demand": "demand",
        "requirement": "demand",
        "需求": "demand",
        "milestone": "milestone",
        "里程碑": "milestone",
    }
    return mapping.get(lowered, "task")


def parse_json_content(content: str) -> object:
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.S | re.I)
    if fenced:
        cleaned = fenced.group(1).strip()
    return json.loads(cleaned)


def config_for_capability(config: dict[str, Any], capability: str) -> dict[str, Any]:
    merged = dict(config)
    for override in config.get("overrides") or []:
        if override.get("capability") != capability or override.get("mode") != "custom":
            continue
        for key in ("provider", "model", "base_url"):
            if override.get(key):
                merged[key] = override[key]
        break
    return merged


def post_json(url: str, payload: dict, headers: dict[str, str] | None = None, verify_ssl: bool = True) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    context = None
    if url.startswith("https://") and not verify_ssl:
        context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_with_openai_compatible(raw_text: str, config: dict[str, Any]) -> list[dict[str, str]]:
    base_url = str(config.get("base_url") or os.getenv("AI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
    model = str(config.get("model") or os.getenv("AI_MODEL", "gpt-4o-mini"))
    api_key = str(config.get("api_key") or os.getenv("AI_API_KEY", ""))
    current_date = datetime.now().date().isoformat()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    SYSTEM_PROMPT
                    + f"\n当前日期是 {current_date}。如果原文只写了月/日，默认使用 {current_date[:4]} 年。"
                ),
            },
            {"role": "user", "content": raw_text},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    result = post_json(
        f"{base_url}/chat/completions",
        payload,
        headers,
        verify_ssl=bool(config.get("verify_ssl", True)),
    )
    content = result["choices"][0]["message"]["content"]
    return normalize_items(parse_json_content(content))


def extract_with_ollama(raw_text: str, config: dict[str, Any]) -> list[dict[str, str]]:
    base_url = str(config.get("base_url") or os.getenv("AI_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
    model = str(config.get("model") or os.getenv("AI_MODEL", "qwen2.5:14b"))
    current_date = datetime.now().date().isoformat()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    SYSTEM_PROMPT
                    + f"\n当前日期是 {current_date}。如果原文只写了月/日，默认使用 {current_date[:4]} 年。"
                ),
            },
            {"role": "user", "content": raw_text},
        ],
        "format": "json",
        "stream": False,
    }
    result = post_json(f"{base_url}/api/chat", payload, verify_ssl=bool(config.get("verify_ssl", True)))
    return normalize_items(parse_json_content(result["message"]["content"]))


def extract_with_configured_model(raw_text: str, model_config: dict[str, Any] | None = None) -> list[dict[str, str]]:
    config = config_for_capability(model_config or get_model_config(), "extract")
    provider = str(config.get("provider") or os.getenv("AI_EXTRACTOR_PROVIDER", "mock")).lower()
    if provider in MODEL_PROVIDERS:
        return extract_with_openai_compatible(raw_text, config)
    if provider == "ollama":
        return extract_with_ollama(raw_text, config)
    return []


def strip_markdown_response(content: str) -> str:
    cleaned = content.strip()
    fenced = re.search(r"```(?:markdown|md)?\s*(.*?)```", cleaned, flags=re.S | re.I)
    if fenced:
        cleaned = fenced.group(1).strip()
    return cleaned


def generate_document_with_configured_model(
    context: dict,
    template: dict,
    title: str,
    input_content: str,
    draft_markdown: str,
    model_config: dict[str, Any] | None = None,
) -> str | None:
    config = config_for_capability(model_config or get_model_config(), "documents")
    provider = str(config.get("provider") or "mock").lower()
    if provider == "mock":
        return None

    model = str(config.get("model") or os.getenv("AI_MODEL", "")).strip()
    base_url = str(config.get("base_url") or os.getenv("AI_BASE_URL", "")).strip().rstrip("/")
    api_key = str(config.get("api_key") or os.getenv("AI_API_KEY", "")).strip()
    if not model or not base_url:
        return None

    compact_context = {
        "project": context.get("project", {}),
        "tasks": context.get("tasks", [])[:20],
        "risks": context.get("risks", [])[:20],
        "demands": context.get("demands", [])[:20],
        "milestones": context.get("milestones", [])[:20],
    }
    user_content = (
        f"文档标题：{title}\n"
        f"模板类型：{template.get('template_type') or ''}\n"
        f"模板名称：{template.get('name') or ''}\n"
        f"模板变量/结构提示：{template.get('variables') or ''}\n"
        f"项目上下文 JSON：{json.dumps(compact_context, ensure_ascii=False, default=str)}\n\n"
        f"用户/内容文件原始资料：\n{input_content[:12000]}\n\n"
        f"系统草稿 Markdown：\n{draft_markdown[:16000]}"
    )

    if provider == "ollama":
        result = post_json(
            f"{base_url}/api/chat",
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": DOCUMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "stream": False,
                "options": {"temperature": float(config.get("temperature") or 0.1)},
            },
            verify_ssl=bool(config.get("verify_ssl", True)),
        )
        return strip_markdown_response(result.get("message", {}).get("content", ""))

    if provider not in MODEL_PROVIDERS:
        return None
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    result = post_json(
        f"{base_url}/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": DOCUMENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": float(config.get("temperature") or 0.1),
            "stream": False,
        },
        headers,
        verify_ssl=bool(config.get("verify_ssl", True)),
    )
    choices = result.get("choices") or []
    content = (((choices[0] or {}).get("message") or {}).get("content") or "").strip() if choices else ""
    return strip_markdown_response(content) or None
