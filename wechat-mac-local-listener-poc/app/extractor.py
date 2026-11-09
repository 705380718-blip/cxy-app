from __future__ import annotations

import re
from dataclasses import dataclass


QUESTION_WORDS = (
    "请问", "怎么", "如何", "为什么", "哪里", "什么时候", "能否", "是否", "有没有",
    "谁负责", "怎么办", "可以吗", "进展如何", "还没好吗",
)
FOLLOW_UP_WORDS = (
    "请确认", "麻烦确认", "请处理", "麻烦处理", "请跟进", "麻烦跟进", "请答复", "麻烦答复",
)
NOISE = re.compile(r"^(收到|好的|好嘞|谢谢|感谢|辛苦了|ok|OK|嗯嗯|哈哈)[！!。.]?$")


@dataclass(frozen=True)
class Match:
    title: str
    category: str
    confidence: float
    rules: tuple[str, ...]


def extract(
    content: str,
    keywords: tuple[str, ...],
    is_at_me: bool,
    target_names: tuple[str, ...] = (),
) -> Match | None:
    text = re.sub(r"\s+", " ", content).strip()
    if len(text) < 2 or NOISE.fullmatch(text):
        return None
    matched: list[str] = []
    category = "keyword"
    confidence = 0.82
    if is_at_me:
        matched.append("@我")
        category, confidence = "mention", 0.91
    mentioned_targets = [
        name
        for name in target_names
        if f"@{name}" in text or f"＠{name}" in text
    ]
    if mentioned_targets:
        matched.extend(f"@{name}" for name in mentioned_targets)
        if category == "keyword":
            category, confidence = "target_mention", 0.90
    if "?" in text or "？" in text or any(word in text for word in QUESTION_WORDS):
        matched.append("问题表达")
        category, confidence = "question", 0.94
    if any(word in text for word in FOLLOW_UP_WORDS):
        matched.append("跟进表达")
        if category == "keyword":
            category, confidence = "follow_up", 0.87
    for keyword in keywords:
        if keyword in text:
            matched.append(keyword)
    if not matched:
        return None
    title = text if len(text) <= 160 else f"{text[:157]}..."
    return Match(title, category, confidence, tuple(dict.fromkeys(matched)))
