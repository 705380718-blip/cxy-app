import sqlite3
from pathlib import Path

from app.config import Settings
from app.content import IMAGE_PLACEHOLDER, normalize_message_content, parse_message_content
from app.db import Database
from app.service import OrganizerService


def test_wechat_sender_prefix_is_removed():
    assert normalize_message_content("hyv5478: 我的微信号是这个呀", "1") == "我的微信号是这个呀"
    assert normalize_message_content("wxid_example:\n请问怎么处理？", "1") == "请问怎么处理？"


def test_normal_colon_text_is_preserved():
    assert normalize_message_content("说明：这是正常正文", "1") == "说明：这是正常正文"


def test_image_xml_uses_placeholder():
    assert normalize_message_content("wxid_example:\n<?xml version='1.0'?><msg><img /></msg>", "3") == IMAGE_PLACEHOLDER
    assert normalize_message_content("<?xml version='1.0'?><msg><img /></msg>", "text") == IMAGE_PLACEHOLDER


def test_quote_xml_is_converted_to_readable_structure():
    content = """<?xml version="1.0"?><msg><appmsg><title>嗯</title><type>57</type>
      <refermsg><content>@Danni. 研发的时间点要盯一下哈</content>
      <displayname>红旗下的鸭蛋</displayname><type>1</type></refermsg></appmsg></msg>"""
    display = parse_message_content(content, "244813135921")

    assert display.kind == "quote"
    assert display.text == "嗯"
    assert display.quote_sender == "红旗下的鸭蛋"
    assert display.quote_content == "@Danni. 研发的时间点要盯一下哈"
    assert "<appmsg" not in display.storage_text


def test_image_inside_quote_uses_placeholder():
    content = """<msg><appmsg><title>看下这张图</title><type>57</type><refermsg>
      <content>&lt;msg&gt;&lt;img aeskey="x" /&gt;&lt;/msg&gt;</content>
      <displayname>项目经理</displayname><type>3</type></refermsg></appmsg></msg>"""
    display = parse_message_content(content, "244813135921")

    assert display.kind == "quote"
    assert display.quote_kind == "image"
    assert display.quote_content == IMAGE_PLACEHOLDER


def test_existing_quote_xml_is_migrated_without_losing_raw_content(tmp_path):
    path = tmp_path / "legacy.db"
    database = Database(path)
    database.initialize()
    quote_xml = """<msg><appmsg><title>这个问题什么时候能完成？</title><type>57</type><refermsg>
      <content>请问这个问题如何处理？</content><displayname>项目经理</displayname>
      <type>1</type></refermsg></appmsg></msg>"""
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO messages(source_id, chat_name, sender, content, message_type, source_time,
                observed_at, is_at_me, matched_rules_json, source_kind, content_text, raw_content)
            VALUES ('legacy-quote', '测试群', '成员', ?, '244813135921', '2026-08-13T01:00:00+00:00',
                '2026-08-13T01:00:00+00:00', 0, '[]', 'decoder', '', '')
            """,
            (quote_xml,),
        )

    database.initialize()

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT content, content_kind, content_text, quote_sender, quote_content, raw_content FROM messages"
        ).fetchone()
    assert row["content_kind"] == "quote"
    assert row["content_text"] == "这个问题什么时候能完成？"
    assert row["quote_sender"] == "项目经理"
    assert row["quote_content"] == "请问这个问题如何处理？"
    assert "<appmsg" not in row["content"]
    assert row["raw_content"] == quote_xml

    settings = Settings(
        host="127.0.0.1",
        port=8791,
        database_path=path,
        wechat_app_path=Path("/Applications/WeChat.app"),
        wechat_data_root=tmp_path / "wechat-data",
        decoder_command=(),
        decoder_baseline_epoch=0,
        max_verified_wechat_version="4.1.12",
        allow_unverified_decoder=False,
        poll_interval_seconds=0.5,
        initial_groups=("测试群",),
        initial_self_names=("我",),
    )
    OrganizerService(database, settings)
    with sqlite3.connect(path) as connection:
        question = connection.execute(
            "SELECT title FROM questions WHERE message_id=(SELECT id FROM messages LIMIT 1)"
        ).fetchone()
    assert question[0] == "这个问题什么时候能完成？"
