from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import DecoderMessage


def test_probe_reports_real_files_and_version_gate(client):
    response = client.get("/api/probe")
    assert response.status_code == 200
    payload = response.json()
    assert payload["wechat"]["version"] == "4.1.11"
    assert payload["data"]["database_count"] == 1
    assert payload["data"]["wal_count"] == 1
    assert payload["can_observe_wal"] is True
    assert payload["can_decode"] is False
    assert any("4.1.11" in blocker for blocker in payload["blockers"])


def test_settings_and_demo_flow(client):
    update = client.put(
        "/api/settings",
        json={
            "groups": ["POC测试群"],
            "self_names": ["测试助手"],
            "target_names": ["项目经理"],
            "keywords": ["延期", "投诉"],
            "require_at_me": False,
            "retention_days": 14,
        },
    )
    assert update.status_code == 200
    assert update.json()["retention_days"] == 14
    assert update.json()["target_names"] == ["项目经理"]

    demo = client.post("/api/demo/messages", json={})
    assert demo.status_code == 200
    assert demo.json()["accepted"] == 4
    messages = client.get("/api/messages?page=1&page_size=20").json()
    questions = client.get("/api/questions?status=pending").json()["items"]
    assert messages["total"] == 4
    assert len(questions) == 3


def test_review_and_report(client):
    client.post("/api/demo/messages", json={})
    question = client.get("/api/questions?status=pending").json()["items"][0]
    reviewed = client.patch(
        f"/api/questions/{question['id']}",
        json={"status": "confirmed", "expected_version": question["version"]},
    )
    assert reviewed.status_code == 200
    report = client.post("/api/reports/generate", json={})
    assert report.status_code == 200
    assert "微信群聊问题报告" in report.json()["content"]
    assert "原消息 #" in report.json()["content"]
    assert report.json()["period_start"] == report.json()["period_end"]


def test_report_supports_inclusive_date_range(client):
    client.post("/api/demo/messages", json={})
    cst = timezone(timedelta(hours=8))
    today = datetime.now(cst).date()
    start = (today - timedelta(days=1)).isoformat()
    end = today.isoformat()

    report = client.post(
        "/api/reports/generate",
        json={"start_date": start, "end_date": end},
    )

    assert report.status_code == 200
    payload = report.json()
    assert payload["period_start"] == start
    assert payload["period_end"] == end
    assert payload["report_key"] == f"R:{start}:{end}"
    assert f"# {start} 至 {end} 微信群聊问题汇总报告" in payload["content"]
    assert payload["question_count"] == 3

    deleted = client.delete(f"/api/reports/id/{payload['id']}")
    assert deleted.status_code == 204


def test_report_rejects_invalid_date_ranges(client):
    today = datetime.now(timezone(timedelta(hours=8))).date()
    yesterday = today - timedelta(days=1)
    reversed_range = client.post(
        "/api/reports/generate",
        json={"start_date": today.isoformat(), "end_date": yesterday.isoformat()},
    )
    incomplete_range = client.post(
        "/api/reports/generate",
        json={"start_date": yesterday.isoformat()},
    )

    assert reversed_range.status_code == 422
    assert incomplete_range.status_code == 422


def test_report_delete(client):
    client.post("/api/demo/messages", json={})
    report = client.post("/api/reports/generate", json={}).json()
    deleted = client.delete(f"/api/reports/{report['report_date']}")
    assert deleted.status_code == 204
    assert client.get("/api/reports").json()["items"] == []
    assert client.delete(f"/api/reports/{report['report_date']}").status_code == 404


def test_refresh_button_has_visible_progress_and_result_feedback(client):
    script = client.get("/static/app.js")
    styles = client.get("/static/styles.css")

    assert script.status_code == 200
    assert styles.status_code == 200
    assert 'button.textContent = "刷新中…"' in script.text
    assert 'showToast("数据已刷新")' in script.text
    assert 'button.setAttribute("aria-busy", "true")' in script.text
    assert ".refresh.is-refreshing::before" in styles.text


def test_frontend_renders_quote_card_and_actionable_disconnect_error(client):
    script = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text

    assert 'item.content_kind === "quote"' in script
    assert "引用原消息" in script
    assert "无法连接本地服务" in script
    assert "2-启动服务" in script
    assert ".message-quote" in styles


def test_followup_report_ui_has_explicit_start_and_end_dates(client):
    page = client.get("/").text
    script = client.get("/static/followup-reports.js").text
    assert 'id="followup-start"' in page
    assert 'id="followup-end"' in page
    assert "生成跟进报告与导出" in page
    assert "start_date:$('followup-start').value,end_date:$('followup-end').value" in script


def test_message_search_and_pagination(client):
    client.post("/api/demo/messages", json={})
    result = client.get("/api/messages?page=1&page_size=10&search=投诉").json()
    assert result["total"] == 1
    assert "投诉" in result["items"][0]["content"]


def test_message_api_does_not_expose_raw_transport_content(client):
    client.post("/api/demo/messages", json={})
    item = client.get("/api/messages?page=1&page_size=10").json()["items"][0]

    assert "raw_content" not in item


def test_quote_message_is_searchable_and_returned_as_structured_content(client):
    service = client.app.state.service
    quote_xml = """<msg><appmsg><title>嗯</title><type>57</type><refermsg>
      <content>@Danni. 研发的时间点要盯一下哈</content>
      <displayname>红旗下的鸭蛋</displayname><type>1</type></refermsg></appmsg></msg>"""
    service.ingest(
        DecoderMessage(
            source_id="quote-message",
            chat_name="POC测试群",
            sender="成员",
            content=quote_xml,
            message_type="244813135921",
            source_time=datetime.now(timezone.utc),
        )
    )

    item = client.get("/api/messages?page=1&page_size=10&search=研发的时间点").json()["items"][0]
    assert item["content_kind"] == "quote"
    assert item["content_text"] == "嗯"
    assert item["quote_sender"] == "红旗下的鸭蛋"
    assert item["quote_content"] == "@Danni. 研发的时间点要盯一下哈"
    assert "<appmsg" not in item["content"]


def test_non_text_metadata_does_not_create_question(client):
    settings = client.get("/api/settings").json()
    response = client.put(
        "/api/settings",
        json={
            "groups": settings["groups"],
            "self_names": settings["self_names"],
            "target_names": ["项目经理"],
            "keywords": settings["keywords"],
            "require_at_me": settings["require_at_me"],
            "retention_days": settings["retention_days"],
        },
    )
    assert response.status_code == 200
    service = client.app.state.service
    from datetime import datetime, timezone
    from app.models import DecoderMessage

    result = service.ingest(
        DecoderMessage(
            source_id="image-metadata",
            chat_name="POC测试群",
            sender="成员",
            content="<msg><title>@项目经理 请问怎么处理？</title></msg>",
            message_type="3",
            source_time=datetime.now(timezone.utc),
        )
    )
    assert result["accepted"] is True
    assert result["question_id"] is None
    messages = client.get("/api/messages?page=1&page_size=10").json()["items"]
    assert messages[0]["content"] == "此内容为图片，不支持展示"


def test_history_import_marker_is_per_group_and_audited(client):
    service = client.app.state.service
    assert service.pending_history_groups(("POC测试群", "新增群")) == ("POC测试群", "新增群")

    service.mark_history_imported("POC测试群", 120, 118)

    assert service.pending_history_groups(("POC测试群", "新增群")) == ("新增群",)
    with service.database.connection() as conn:
        row = conn.execute(
            "SELECT source_message_count, inserted_message_count FROM group_history_sync WHERE group_name=?",
            ("POC测试群",),
        ).fetchone()
        audit = conn.execute(
            "SELECT action FROM audit_log WHERE action='history_import' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert tuple(row) == (120, 118)
    assert audit["action"] == "history_import"


def test_default_retention_is_seven_days(client):
    assert client.get("/api/settings").json()["retention_days"] == 7


def test_dashboard_persists_group_high_water_from_business_messages(client):
    client.post("/api/demo/messages", json={})
    payload = client.get("/api/dashboard").json()
    assert "POC测试群" in payload["high_water"]
    assert isinstance(payload["high_water"]["POC测试群"], int)


def test_retention_setting_prunes_old_messages_and_questions(client):
    service = client.app.state.service
    old = datetime.now(timezone.utc) - timedelta(days=8)
    service.ingest(
        DecoderMessage(
            source_id="old-question",
            chat_name="POC测试群",
            sender="成员",
            content="请问这个问题如何处理？",
            message_type="text",
            source_time=old,
        )
    )
    settings = client.get("/api/settings").json()
    payload = {key: settings[key] for key in ("groups", "self_names", "target_names", "keywords", "require_at_me", "retention_days")}
    assert client.put("/api/settings", json=payload).status_code == 200
    assert client.get("/api/messages?page=1&page_size=10").json()["total"] == 0
    assert client.get("/api/questions?status=pending").json()["total"] == 0


def test_questions_are_paginated_and_batch_reviewed(client):
    service = client.app.state.service
    now = datetime.now(timezone.utc)
    for index in range(12):
        service.ingest(
            DecoderMessage(
                source_id=f"batch-{index}",
                chat_name="POC测试群",
                sender="成员",
                content=f"请问问题 {index} 如何处理？",
                message_type="text",
                source_time=now,
            )
        )
    first_page = client.get("/api/questions?status=pending&page=1&page_size=10").json()
    second_page = client.get("/api/questions?status=pending&page=2&page_size=10").json()
    assert first_page["total"] == 12
    assert first_page["pages"] == 2
    assert len(first_page["items"]) == 10
    assert len(second_page["items"]) == 2

    selected = first_page["items"][:2]
    response = client.post(
        "/api/questions/batch-review",
        json={
            "status": "ignored",
            "items": [
                {"id": item["id"], "expected_version": item["version"]} for item in selected
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["updated"] == 2
    assert client.get("/api/questions?status=pending").json()["total"] == 10


def test_environment_diagnostics_tab_is_hidden(client):
    html = client.get("/").text
    assert 'data-tab="diagnostics"' not in html
    assert 'id="tab-diagnostics"' not in html
    assert 'class="listener-details"' in html


def test_batch_review_ui_is_present(client):
    html = client.get("/").text
    script = client.get("/static/app.js").text
    assert 'id="question-select-all"' in html
    assert 'id="question-batch-confirm"' in html
    assert 'id="question-batch-ignore"' in html
    assert 'id="question-pagination"' in html
    assert "/api/questions/batch-review" in script


def test_local_security_headers_and_origin_gate(client):
    response = client.get("/api/dashboard")
    assert "default-src 'self'" in response.headers["content-security-policy"]
    blocked = client.put(
        "/api/settings",
        headers={"Origin": "https://example.invalid"},
        json={
            "groups": ["POC测试群"],
            "self_names": ["测试助手"],
            "target_names": [],
            "keywords": [],
            "require_at_me": False,
            "retention_days": 30,
        },
    )
    assert blocked.status_code == 403


def test_local_origin_allowlist_has_no_test_hostname_exception(client):
    for origin in ('http://testserver', 'null', 'http://127.0.0.1:9999'):
        response = client.post('/api/projects', headers={'Origin': origin}, json={'name':'构造跨域请求'})
        assert response.status_code == 403
    assert client.get('/api/projects').json()['items'] == []
    for origin in ('http://127.0.0.1:8791', 'http://localhost:8791'):
        response = client.post('/api/projects', headers={'Origin': origin}, json={'name':origin})
        assert response.status_code == 201
    assert client.get('/api/health').json()['version'] == '0.5.7'
