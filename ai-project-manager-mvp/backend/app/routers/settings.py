from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db import get_connection, init_db
from app.schemas import AgentProfile, AssistantChatRequest, ModelConfig
from app.services.assistant_service import answer_project_question, list_chat_messages
from app.services.settings_service import (
    get_agent_profile,
    get_model_config,
    public_model_config,
    resolve_secret_for_save,
    save_agent_profile,
    save_model_config,
    test_model_config,
)


router = APIRouter(tags=["settings"])


@router.get("/settings/model-config")
def read_model_config() -> dict:
    return public_model_config(get_model_config())


@router.put("/settings/model-config")
def update_model_config(config: ModelConfig) -> dict:
    payload = resolve_secret_for_save(config.model_dump(), get_model_config())
    payload["status"] = payload.get("status") or "untested"
    payload["status_message"] = payload.get("status_message") or "配置已保存，尚未测试连接。"
    return public_model_config(save_model_config(payload))


@router.post("/settings/model-config/test")
def test_default_model(config: ModelConfig | None = None) -> dict:
    payload = resolve_secret_for_save(config.model_dump(), get_model_config()) if config else get_model_config()
    result = test_model_config(payload)
    payload.update(result)
    saved = save_model_config(payload)
    return {
        "status": saved["status"],
        "status_message": saved["status_message"],
        "last_tested_at": saved["last_tested_at"],
        "config": public_model_config(saved),
    }


@router.get("/settings/agent-profile")
def read_agent_profile() -> dict:
    return get_agent_profile()


@router.put("/settings/agent-profile")
def update_agent_profile(profile: AgentProfile) -> dict:
    return save_agent_profile(profile.model_dump())


@router.post("/assistant/chat")
def chat_with_assistant(request: AssistantChatRequest) -> dict:
    init_db()
    with get_connection() as connection:
        try:
            return answer_project_question(connection, request.project_key, request.message, request.view)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/assistant/messages")
def read_assistant_messages(project_key: str, limit: int = 20) -> list[dict]:
    init_db()
    with get_connection() as connection:
        return list_chat_messages(connection, project_key, limit)
