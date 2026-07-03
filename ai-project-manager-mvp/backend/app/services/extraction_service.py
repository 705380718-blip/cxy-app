from __future__ import annotations

import logging
import re
from typing import Any

from app.services.ai_adapter import extract_with_configured_model


ExtractionDraft = dict[str, str]
logger = logging.getLogger(__name__)


TASK_KEYWORDS = ("任务", "完成", "跟进", "联系", "补齐", "确认", "准备", "输出", "提交", "整理")
RISK_KEYWORDS = ("风险", "可能", "影响", "延期", "阻塞", "未到位", "不足", "超出", "异常")
DEMAND_KEYWORDS = ("需求", "新增", "希望", "增加", "调整", "变更", "诉求")
MILESTONE_KEYWORDS = ("里程碑", "会议", "评审", "验收", "上线", "交付", "联调")


def split_lines(raw_text: str) -> list[str]:
    lines = []
    for line in re.split(r"[\n。；;]", raw_text):
        cleaned = re.sub(r"^[\s\-*•·]+", "", line).strip()
        cleaned = re.sub(r"^\d+[.、]\s*", "", cleaned)
        if cleaned:
            lines.append(cleaned)
    return lines


def extract_date(text: str) -> str:
    iso_match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if iso_match:
        year, month, day = iso_match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    short_match = re.search(r"(\d{1,2})[/-](\d{1,2})", text)
    if short_match:
        month, day = short_match.groups()
        return f"2026-{int(month):02d}-{int(day):02d}"
    chinese_match = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if chinese_match:
        month, day = chinese_match.groups()
        return f"2026-{int(month):02d}-{int(day):02d}"
    return ""


def extract_owner(text: str) -> str:
    owner_match = re.search(r"(?:责任人|负责人|owner|Owner)[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9_-]{2,8})", text)
    if owner_match:
        return owner_match.group(1)
    mention_match = re.search(r"@([\u4e00-\u9fa5A-Za-z0-9_-]{2,8})", text)
    return mention_match.group(1) if mention_match else ""


def clean_title(text: str) -> str:
    title = re.sub(r"(?:责任人|负责人)[:：]?\s*[\u4e00-\u9fa5A-Za-z0-9_-]{2,8}", "", text)
    title = re.sub(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", "", title)
    title = re.sub(r"\d{1,2}[/-]\d{1,2}", "", title)
    title = re.sub(r"\d{1,2}月\d{1,2}日", "", title)
    title = re.sub(r"\s+", " ", title).strip(" ，,：:")
    return title[:42] or text[:42]


def classify(text: str) -> str:
    if any(keyword in text for keyword in RISK_KEYWORDS):
        return "risk"
    if any(keyword in text for keyword in DEMAND_KEYWORDS):
        return "demand"
    if any(keyword in text for keyword in TASK_KEYWORDS):
        return "task"
    if any(keyword in text for keyword in MILESTONE_KEYWORDS) and extract_date(text):
        return "milestone"
    return "task"


def draft_from_line(text: str) -> ExtractionDraft:
    item_type = classify(text)
    due_date = extract_date(text)
    owner = extract_owner(text)
    draft: ExtractionDraft = {
        "item_type": item_type,
        "title": clean_title(text),
        "description": text,
        "owner": owner,
        "due_date": due_date,
        "probability": "",
        "impact": "",
        "response": "",
    }
    if item_type == "risk":
        draft["probability"] = "60%" if "可能" in text or "风险" in text else "40%"
        draft["impact"] = "高" if "延期" in text or "阻塞" in text or "不足" in text else "中"
        draft["response"] = "请确认责任人和应对方案"
    if item_type == "demand":
        draft["response"] = "进入需求池评估范围和排期"
    if item_type == "milestone":
        draft["response"] = "同步到里程碑计划"
    return draft


def extract_structured_items(raw_text: str, model_config: dict[str, Any] | None = None) -> list[ExtractionDraft]:
    try:
        model_items = extract_with_configured_model(raw_text, model_config)
        if model_items:
            return model_items
    except Exception as exc:
        logger.warning("AI extraction failed, falling back to rule extraction: %s", exc)

    drafts: list[ExtractionDraft] = []
    seen: set[tuple[str, str]] = set()
    for line in split_lines(raw_text):
        draft = draft_from_line(line)
        key = (draft["item_type"], draft["title"])
        if key not in seen:
            drafts.append(draft)
            seen.add(key)
    return drafts
