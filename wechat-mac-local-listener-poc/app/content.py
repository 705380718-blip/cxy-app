from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass


IMAGE_PLACEHOLDER = "此内容为图片，不支持展示"
SPECIAL_MESSAGE_PLACEHOLDER = "此内容为微信特殊消息，暂不支持展示"
IMAGE_TYPES = {"3", "image", "图片"}
WECHAT_SENDER_PREFIX = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.-]{2,127}:(?:\r?\n|\s+)(?P<body>[\s\S]*)$"
)


@dataclass(frozen=True)
class MessageDisplay:
    kind: str
    text: str
    quote_sender: str = ""
    quote_content: str = ""
    quote_kind: str = ""

    @property
    def storage_text(self) -> str:
        if self.kind != "quote":
            return self.text
        label = f"引用 {self.quote_sender}" if self.quote_sender else "引用原消息"
        parts = [self.text, f"{label}：{self.quote_content}" if self.quote_content else label]
        return "\n".join(part for part in parts if part).strip()


def _without_sender_prefix(content: str) -> str:
    text = str(content or "").strip()
    match = WECHAT_SENDER_PREFIX.match(text)
    return match.group("body").strip() if match else text


def _xml_text(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    value = node.findtext(path, default="")
    return html.unescape(str(value or "")).strip()


def _quoted_content(content: str, message_type: str) -> tuple[str, str]:
    text = _without_sender_prefix(html.unescape(str(content or ""))).strip()
    kind = str(message_type or "").strip().lower()
    lowered = text.lower()
    if kind in IMAGE_TYPES or "<img" in lowered or "&lt;img" in lowered:
        return IMAGE_PLACEHOLDER, "image"
    if lowered.startswith("<?xml") or lowered.startswith("<msg"):
        try:
            nested = ET.fromstring(text)
        except ET.ParseError:
            return SPECIAL_MESSAGE_PLACEHOLDER, "unsupported"
        if nested.find(".//img") is not None:
            return IMAGE_PLACEHOLDER, "image"
        title = _xml_text(nested, ".//appmsg/title")
        return (title or SPECIAL_MESSAGE_PLACEHOLDER), ("text" if title else "unsupported")
    return text or "原消息内容为空", "text"


def parse_message_content(content: str, message_type: str) -> MessageDisplay:
    """Parse WeChat transport XML into a safe, readable display model."""
    kind = str(message_type or "").strip().lower()
    text = _without_sender_prefix(content)
    if kind in IMAGE_TYPES:
        return MessageDisplay("image", IMAGE_PLACEHOLDER)

    lowered = text.lower()
    looks_like_xml = lowered.startswith("<?xml") or lowered.startswith("<msg")
    if not looks_like_xml:
        return MessageDisplay("text", text)

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        if "<img" in lowered:
            return MessageDisplay("image", IMAGE_PLACEHOLDER)
        return MessageDisplay("unsupported", SPECIAL_MESSAGE_PLACEHOLDER)

    appmsg = root.find("appmsg")
    if appmsg is None:
        appmsg = root.find(".//appmsg")
    refermsg = root.find(".//refermsg")
    app_type = _xml_text(appmsg, "type")
    if refermsg is not None or app_type == "57":
        body = _xml_text(appmsg, "title") or _xml_text(appmsg, "des")
        quote_sender = _xml_text(refermsg, "displayname")
        quote_raw = _xml_text(refermsg, "content")
        quote_type = _xml_text(refermsg, "type")
        quote_content, quote_kind = _quoted_content(quote_raw, quote_type)
        return MessageDisplay(
            "quote",
            body or "回复了一条引用消息",
            quote_sender,
            quote_content,
            quote_kind,
        )

    if root.find(".//img") is not None:
        return MessageDisplay("image", IMAGE_PLACEHOLDER)
    title = _xml_text(appmsg, "title") or _xml_text(appmsg, "des")
    if title:
        return MessageDisplay("text", title)
    return MessageDisplay("unsupported", SPECIAL_MESSAGE_PLACEHOLDER)


def normalize_message_content(content: str, message_type: str) -> str:
    """Return searchable user-facing text without WeChat transport metadata."""
    return parse_message_content(content, message_type).storage_text
