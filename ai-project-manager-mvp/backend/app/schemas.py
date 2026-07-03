from pydantic import BaseModel, Field
from typing import Any


class ProjectBase(BaseModel):
    name: str = Field(min_length=1)
    customer: str = ""
    phase: str = ""
    status: str = ""
    contract_status: str = ""
    region: str = ""
    area: str = ""
    project_type: str = ""
    progress: int = 0
    days: str = ""
    tasks: int = 0
    risks: int = 0
    budget_usage: int = 0
    new_demands: int = 0
    health: int = 0
    budget: str = ""
    incurred_cost: str = ""
    payment_2025: str = ""
    manager: str = ""
    delivery: str = ""
    sales: str = ""
    start_date: str = ""
    pre_start_date: str = ""
    acceptance: str = ""
    end_date: str = ""
    spm: str = ""
    contract_no: str = ""
    background: str = ""
    plan: str = ""
    remark: str = ""
    dashboard: bool = True
    milestone_date: str = ""
    milestone_label: str = ""


class ProjectCreate(ProjectBase):
    key: str | None = None


class ProjectUpdate(ProjectBase):
    pass


class GanttRowsPayload(BaseModel):
    rows: list[dict[str, Any]] = []


class TaskBase(BaseModel):
    project_key: str
    status: str = "todo"
    title: str = Field(min_length=1)
    description: str = ""
    owner: str = ""
    start_date: str = ""
    due_date: str = ""
    progress: int = 0
    source_extraction_id: int | None = None
    demand_id: int | None = None


class TaskUpdate(BaseModel):
    project_key: str | None = None
    status: str | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    owner: str | None = None
    start_date: str | None = None
    due_date: str | None = None
    progress: int | None = None
    source_extraction_id: int | None = None
    demand_id: int | None = None


class RiskBase(BaseModel):
    project_key: str
    title: str = Field(min_length=1)
    description: str = ""
    probability: str = ""
    impact: str = "中"
    status: str = "跟进中"
    response: str = ""
    source_extraction_id: int | None = None


class RiskUpdate(BaseModel):
    project_key: str | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    probability: str | None = None
    impact: str | None = None
    status: str | None = None
    response: str | None = None
    source_extraction_id: int | None = None


class DemandBase(BaseModel):
    project_key: str
    title: str = Field(min_length=1)
    description: str = ""
    status: str = "待评估"
    scope_impact: str = ""
    source_extraction_id: int | None = None


class DemandUpdate(BaseModel):
    project_key: str | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: str | None = None
    scope_impact: str | None = None
    source_extraction_id: int | None = None


class MilestoneBase(BaseModel):
    project_key: str
    title: str = Field(min_length=1)
    date: str = ""
    status: str = "待开始"
    source_extraction_id: int | None = None


class MilestoneUpdate(BaseModel):
    project_key: str | None = None
    title: str | None = Field(default=None, min_length=1)
    date: str | None = None
    status: str | None = None
    source_extraction_id: int | None = None


class SnippetCreate(BaseModel):
    project_key: str
    source_type: str = "meeting"
    raw_text: str = Field(min_length=1)


class ExtractionUpdate(BaseModel):
    item_type: str | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    owner: str | None = None
    due_date: str | None = None
    probability: str | None = None
    impact: str | None = None
    response: str | None = None
    status: str | None = None


class DocumentGenerateRequest(BaseModel):
    project_key: str
    template_id: int
    title: str | None = None
    input_content: str = ""


class ModelOverride(BaseModel):
    capability: str
    label: str = ""
    mode: str = "inherit"
    provider: str = ""
    model: str = ""
    base_url: str = ""


class ModelConfig(BaseModel):
    provider: str = "mock"
    provider_label: str = "离线内置模型"
    model: str = "local-project-assistant"
    base_url: str = ""
    api_key: str = ""
    verify_ssl: bool = True
    temperature: float = 0.1
    status: str = "untested"
    status_message: str = "尚未测试连接。"
    last_tested_at: str = ""
    has_api_key: bool = False
    overrides: list[ModelOverride] = []


class AgentProfile(BaseModel):
    name: str = Field(default="小智", min_length=1)
    role: str = ""
    tone: str = ""
    responsibilities: list[str] = []
    forbidden: list[str] = []
    default_output_format: str = ""
    long_term_preferences: list[str] = []
    proactive_reminders: list[str] = []
    memory_policy: str = ""


class AssistantChatRequest(BaseModel):
    project_key: str
    view: str = "项目驾驶舱"
    message: str = Field(min_length=1)
