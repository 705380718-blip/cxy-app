from __future__ import annotations

import ssl
import json
import re
from typing import Any
import urllib.request

from app.services.document_service import get_project_context
from app.services.extraction_service import extract_date, extract_owner
from app.services.settings_service import get_agent_profile, get_model_config


def item_line(item: dict, fields: tuple[str, ...]) -> str:
    parts = [str(item.get(field) or "") for field in fields if item.get(field)]
    return " | ".join(parts)


def project_snapshot(context: dict) -> str:
    project = context["project"]
    open_risks = [risk for risk in context["risks"] if risk.get("status") not in {"已关闭", "已解决"}]
    active_tasks = [task for task in context["tasks"] if task.get("status") != "done"]
    lines = [
        f"{project['name']} 当前处于{project['phase'] or '未标记阶段'}，进度 {project['progress']}%，健康分 {project['health']}。",
        f"任务 {len(context['tasks'])} 项，开放风险 {len(open_risks)} 项，新增需求 {len(context['demands'])} 项。",
    ]
    if project.get("milestone_label"):
        lines.append(f"下一节点是{project['milestone_label']}（{project.get('milestone_date') or '日期待定'}）。")
    if active_tasks:
        lines.append("优先推进：" + "；".join(item_line(task, ("title", "owner", "due_date")) for task in active_tasks[:3]))
    return "\n".join(lines)


def compact_context_for_model(context: dict) -> dict[str, Any]:
    project = context["project"]
    return {
        "project": {
            "name": project.get("name"),
            "customer": project.get("customer"),
            "phase": project.get("phase"),
            "status": project.get("status"),
            "progress": project.get("progress"),
            "health": project.get("health"),
            "background": project.get("background"),
            "plan": project.get("plan"),
            "milestone_date": project.get("milestone_date"),
            "milestone_label": project.get("milestone_label"),
        },
        "tasks": context["tasks"][:12],
        "risks": context["risks"][:12],
        "demands": context["demands"][:12],
        "milestones": context["milestones"][:12],
    }


def history_for_model(messages: list[dict]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for message in messages[-12:]:
        role = "assistant" if message.get("role") == "assistant" else "user"
        content = str(message.get("content") or "").strip()
        if content:
            history.append({"role": role, "content": content})
    return history


def build_model_messages(
    context: dict,
    message: str,
    view: str,
    action_type: str,
    action_payload: dict[str, Any],
    history: list[dict] | None = None,
    agent_profile: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    profile = agent_profile or get_agent_profile()
    action_note = ""
    if action_type == "pending_extraction":
        action_note = (
            "系统已经把用户请求生成了一条待确认任务，位置在信息归集页。"
            f"待确认任务标题：{action_payload.get('title') or '未命名任务'}。"
            "请在回复里自然告知用户可以去信息归集页确认落库。"
        )
    responsibilities = "；".join(profile.get("responsibilities") or [])
    forbidden = "；".join(profile.get("forbidden") or [])
    preferences = "；".join(profile.get("long_term_preferences") or [])
    proactive_reminders = "；".join(profile.get("proactive_reminders") or [])
    system_prompt = (
        f"你叫{profile.get('name') or '小智'}，不是通用聊天 AI，而是专门服务于项目管理的智能体。"
        f"角色定位：{profile.get('role') or '辅助项目经理完成项目管理'}。"
        f"语气风格：{profile.get('tone') or '理性、沉稳'}。"
        f"主要职责：{responsibilities or '项目进度跟进、风险提醒、文档辅助生成'}。"
        f"默认输出格式：{profile.get('default_output_format') or '飞书可展示的 Markdown 格式'}。"
        f"长期偏好：{preferences or '提醒和顾问型'}。"
        f"需要主动提醒的事项：{proactive_reminders or '项目风险、每日待办、任务进度逾期'}。"
        f"禁止事项：{forbidden or '篡改项目信息；泄露敏感信息'}。"
        f"记忆策略：{profile.get('memory_policy') or '智能体画像和项目记忆保存在本地系统中，与底层模型配置分离。'}"
        "你必须结合提供的项目上下文和同项目历史对话回答；没有数据就明确说缺少哪类信息，不要编造。"
        "如果用户说“上面”“刚才”“继续”等，请优先结合当前项目历史对话理解。"
        "你可以提出项目管理建议、生成文档草稿、提示风险和待办；但不得直接声称已篡改项目主数据。"
        "创建任务、风险、需求等动作必须进入信息归集待确认，由用户确认后再落库。"
        "如果用户问你使用的模型，可以说明底层模型可切换，但你的智能体身份、规则和本地记忆不会因换模型而改变；不要透露 API Key。"
        + action_note
    )
    context_text = json.dumps(compact_context_for_model(context), ensure_ascii=False, default=str)
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"当前页面：{view}\n项目上下文 JSON：{context_text}",
        },
        *history_for_model(history or []),
        {"role": "user", "content": message},
    ]


def call_configured_model(messages: list[dict[str, str]], config: dict[str, Any] | None = None) -> str | None:
    config = config or get_model_config()
    provider = str(config.get("provider") or "mock").lower()
    if provider == "mock":
        return None

    model = str(config.get("model") or "").strip()
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    api_key = str(config.get("api_key") or "").strip()
    if not model or not base_url:
        return None

    verify_ssl = bool(config.get("verify_ssl", True))
    context = None
    if base_url.startswith("https://") and not verify_ssl:
        context = ssl._create_unverified_context()

    if provider == "ollama":
        url = f"{base_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": float(config.get("temperature") or 0.1)},
        }
        headers = {"Content-Type": "application/json"}
    else:
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": float(config.get("temperature") or 0.1),
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        body = json.loads(response.read().decode("utf-8"))

    if provider == "ollama":
        content = ((body.get("message") or {}).get("content") or "").strip()
    else:
        choices = body.get("choices") or []
        content = (((choices[0] or {}).get("message") or {}).get("content") or "").strip() if choices else ""
    return content or None


def create_chat_message(
    connection,
    project_key: str,
    view: str,
    role: str,
    content: str,
    action_type: str = "",
    action_payload: dict[str, Any] | None = None,
) -> dict:
    cursor = connection.execute(
        """
        insert into chat_messages
          (project_key, view, role, content, action_type, action_payload)
        values (?, ?, ?, ?, ?, ?)
        """,
        [
            project_key,
            view,
            role,
            content,
            action_type,
            json.dumps(action_payload or {}, ensure_ascii=False),
        ],
    )
    row = connection.execute("select * from chat_messages where id = ?", [cursor.lastrowid]).fetchone()
    return dict(row)


def list_chat_messages(connection, project_key: str, limit: int = 20) -> list[dict]:
    rows = connection.execute(
        """
        select * from chat_messages
        where project_key = ?
        order by id desc
        limit ?
        """,
        [project_key, limit],
    ).fetchall()
    messages = [dict(row) for row in reversed(rows)]
    for message in messages:
        try:
            message["action_payload"] = json.loads(message["action_payload"] or "{}")
        except json.JSONDecodeError:
            message["action_payload"] = {}
    return messages


def looks_like_task_creation(message: str) -> bool:
    return any(keyword in message for keyword in ("创建", "新增", "添加", "生成")) and "任务" in message


def task_title_from_message(message: str) -> str:
    title = re.sub(r"(请|帮我|麻烦)?(创建|新增|添加|生成)(一个|一条)?", "", message)
    title = re.sub(r"(任务|待办)$", "", title).strip(" ：:，,。")
    return title or "待确认任务"


def create_pending_task_extraction(connection, project_key: str, message: str) -> dict:
    snippet_cursor = connection.execute(
        """
        insert into snippets (project_key, source_type, raw_text, extract_status)
        values (?, 'assistant', ?, 'extracted')
        """,
        [project_key, message],
    )
    extraction_cursor = connection.execute(
        """
        insert into extractions
          (snippet_id, project_key, item_type, title, description, owner, due_date, status)
        values (?, ?, 'task', ?, ?, ?, ?, 'pending')
        """,
        [
            snippet_cursor.lastrowid,
            project_key,
            task_title_from_message(message),
            message,
            extract_owner(message),
            extract_date(message),
        ],
    )
    row = connection.execute(
        "select * from extractions where id = ?",
        [extraction_cursor.lastrowid],
    ).fetchone()
    return dict(row)


def local_rule_answer(context: dict, message: str, action_type: str, action_payload: dict[str, Any]) -> str:
    project = context["project"]
    text = message.lower()
    open_risks = [risk for risk in context["risks"] if risk.get("status") not in {"已关闭", "已解决"}]

    if action_type == "pending_extraction":
        return (
            f"已把「{action_payload.get('title') or '待确认任务'}」生成一条待确认任务，"
            "请到信息归集页检查后再确认落库。"
        )
    if any(keyword in message for keyword in ("风险", "阻塞", "问题")):
        if not open_risks:
            answer = f"{project['name']} 当前没有开放风险。建议继续用信息归集页沉淀会议和群聊里的新风险。"
        else:
            high_risks = [risk for risk in open_risks if risk.get("impact") == "高"]
            risk = (high_risks or open_risks)[0]
            answer = (
                f"当前最需要关注的是「{risk['title']}」。"
                f"影响等级为{risk.get('impact') or '未标记'}，状态是{risk.get('status') or '未标记'}。"
                f"建议动作：{risk.get('response') or '尽快明确责任人、截止时间和缓解方案'}。"
            )
    elif any(keyword in message for keyword in ("进度", "延期", "任务", "排期")) or "progress" in text:
        todo = [task for task in context["tasks"] if task.get("status") in {"todo", "doing", "confirm"}]
        answer = (
            f"{project['name']} 当前项目进度 {project['progress']}%，"
            f"还有 {len(todo)} 个未完成任务。"
        )
        if todo:
            answer += " 建议优先处理：" + "；".join(item_line(task, ("title", "owner", "due_date")) for task in todo[:3]) + "。"
    elif any(keyword in message for keyword in ("周报", "汇报", "总结")):
        answer = (
            f"本周可汇报：{project['name']} 处于{project['phase']}，进度 {project['progress']}%。"
            f"本周重点围绕{project.get('milestone_label') or '项目计划'}推进；"
            f"风险侧有 {len(open_risks)} 项需跟踪，需求池有 {len(context['demands'])} 项待评估。"
        )
    elif any(keyword in message for keyword in ("需求", "范围", "变更")):
        demands = context["demands"]
        if demands:
            answer = "当前需求池重点是：" + "；".join(item_line(item, ("title", "status", "scope_impact")) for item in demands[:4]) + "。"
        else:
            answer = f"{project['name']} 暂无新增需求记录。"
    else:
        answer = project_snapshot(context)
    return answer


def answer_project_question(connection, project_key: str, message: str, view: str) -> dict[str, Any]:
    context = get_project_context(connection, project_key)
    model_config = get_model_config()
    agent_profile = get_agent_profile()
    recent_messages = list_chat_messages(connection, project_key, 12)
    action_type = ""
    action_payload: dict[str, Any] = {}

    create_chat_message(connection, project_key, view, "user", message)

    if looks_like_task_creation(message):
        extraction = create_pending_task_extraction(connection, project_key, message)
        action_type = "pending_extraction"
        action_payload = {
            "extraction_id": extraction["id"],
            "item_type": extraction["item_type"],
            "title": extraction["title"],
        }

    source = "local-project-context"
    try:
        model_answer = call_configured_model(
            build_model_messages(context, message, view, action_type, action_payload, recent_messages, agent_profile),
            model_config,
        )
    except Exception:
        model_answer = None
    if model_answer:
        answer = model_answer
        source = "configured-model"
    else:
        answer = local_rule_answer(context, message, action_type, action_payload)

    create_chat_message(connection, project_key, view, "assistant", answer, action_type, action_payload)
    connection.commit()
    return {
        "answer": answer,
        "project_key": project_key,
        "view": view,
        "source": source,
        "action_type": action_type,
        "action_payload": action_payload,
        "agent_name": agent_profile.get("name") or "小智",
    }
