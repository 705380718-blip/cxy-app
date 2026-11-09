from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


STRICT = ConfigDict(str_strip_whitespace=True, extra="forbid")


class RuleSettingsUpdate(BaseModel):
    model_config = STRICT
    groups: list[str] = Field(min_length=1, max_length=30)
    self_names: list[str] = Field(min_length=1, max_length=10)
    target_names: list[str] = Field(default_factory=list, max_length=30)
    keywords: list[str] = Field(default_factory=list, max_length=80)
    require_at_me: bool = False
    retention_days: int = Field(default=7, ge=1, le=365)

    @field_validator("groups", "self_names", "target_names", "keywords")
    @classmethod
    def clean_values(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            item = value.strip().lstrip("@＠").strip()
            if not item or len(item) > 100 or any(c in item for c in ("\n", "\r", "=")):
                raise ValueError("规则项格式不合法")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned


class ReviewUpdate(BaseModel):
    model_config = STRICT
    status: Literal["pending", "confirmed", "ignored"]
    expected_version: int = Field(ge=1)


class BatchReviewItem(BaseModel):
    model_config = STRICT
    id: int = Field(ge=1)
    expected_version: int = Field(ge=1)


class BatchReviewUpdate(BaseModel):
    model_config = STRICT
    status: Literal["confirmed", "ignored"]
    items: list[BatchReviewItem] = Field(min_length=1, max_length=200)

    @field_validator("items")
    @classmethod
    def unique_items(cls, values: list[BatchReviewItem]) -> list[BatchReviewItem]:
        if len({item.id for item in values}) != len(values):
            raise ValueError("问题 ID 不能重复")
        return values


class ReportRequest(BaseModel):
    model_config = STRICT
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("date", "start_date", "end_date")
    @classmethod
    def valid_date(cls, value: str | None) -> str | None:
        if value:
            date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def valid_range(self) -> "ReportRequest":
        if self.date and (self.start_date or self.end_date):
            raise ValueError("date 不能与 start_date/end_date 同时使用")
        if bool(self.start_date) != bool(self.end_date):
            raise ValueError("开始日期和结束日期必须同时填写")
        start_value = self.start_date or self.date
        end_value = self.end_date or self.date
        if not start_value:
            return self
        start = date.fromisoformat(start_value)
        end = date.fromisoformat(end_value)
        if start > end:
            raise ValueError("开始日期不能晚于结束日期")
        if end > date.today():
            raise ValueError("结束日期不能晚于今天")
        if (end - start).days > 364:
            raise ValueError("汇总时间最多为 365 天")
        return self


class DecoderMessage(BaseModel):
    model_config = STRICT
    source_id: str | None = Field(default=None, max_length=240)
    chat_name: str = Field(min_length=1, max_length=200)
    sender: str = Field(default="未知成员", max_length=200)
    content: str = Field(default="", max_length=20_000)
    message_type: str = Field(default="text", max_length=80)
    source_time: datetime
    is_group: bool = True
    is_at_me: bool = False
    source_kind: str = Field(default="decoder", max_length=40)


class ProjectCreate(BaseModel):
    model_config = STRICT
    name: str = Field(min_length=1, max_length=100)


class SourceBind(BaseModel):
    model_config = STRICT
    source_kind: Literal['import', 'decoder']
    source_key: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    auto_analysis_enabled: Literal[False] = False  # Enable separately with an explicit future-message scope.


class ImportPreview(BaseModel):
    model_config = STRICT
    project_source_id: int = Field(ge=1)
    format: Literal['txt', 'csv', 'paste']
    content: str = Field(min_length=1, max_length=2_097_152)
    default_sender: str | None = Field(default=None, min_length=1, max_length=200)
    default_timestamp: datetime | None = None


class ImportCommit(BaseModel):
    model_config = STRICT
    accept_valid_rows: bool = False


class WorkItemCreate(BaseModel):
    model_config = STRICT
    project_source_id: int = Field(ge=1)
    type: Literal['issue', 'task', 'decision', 'risk']
    title: str = Field(min_length=1, max_length=200)
    evidence_message_ids: list[int] = Field(min_length=1, max_length=100)


class WorkItemUpdate(BaseModel):
    model_config = STRICT
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    review_status: Literal['pending', 'confirmed', 'ignored'] | None = None
    work_status: Literal['open', 'in_progress', 'waiting_confirmation', 'resolved'] | None = None
    owner: str | None = Field(default=None, max_length=200)
    due_at: datetime | None = None
    due_text: str | None = Field(default=None, max_length=200)
    latest_progress: str | None = Field(default=None, max_length=2000)


class AnalysisPreview(BaseModel):
    model_config = STRICT
    project_source_id: int = Field(ge=1)
    after_message_id: int = Field(default=0, ge=0)
    through_message_id: int | None = Field(default=None, ge=1)


class AnalysisEnqueue(BaseModel):
    model_config = STRICT
    preview_token: str = Field(min_length=1, max_length=100)
    consent: Literal[True]


class AutomationUpdate(BaseModel):
    model_config = STRICT
    enabled: bool
    consent: bool = False


class ProposalApply(BaseModel):
    model_config = STRICT
    expected_version: int | None = Field(default=None, ge=1)
    target_item_id: int | None = Field(default=None, ge=1)


class BatchProposalItem(BaseModel):
    model_config = STRICT
    id: int = Field(ge=1)
    expected_version: int | None = Field(default=None, ge=1)


class BatchProposalAction(BaseModel):
    model_config = STRICT
    project_id: int = Field(ge=1)
    action: Literal['apply', 'dismiss']
    items: list[BatchProposalItem] = Field(min_length=1, max_length=100)

    @field_validator('items')
    @classmethod
    def unique_items(cls, items):
        if len({item.id for item in items}) != len(items):
            raise ValueError('建议不能重复选择')
        return items


class ItemLifecycle(BaseModel):
    model_config = STRICT
    expected_version: int = Field(ge=1)


class ItemMerge(BaseModel):
    model_config = STRICT
    target_item_id: int = Field(ge=1)
    expected_version: int = Field(ge=1)
    target_version: int = Field(ge=1)


class FollowupReportRequest(BaseModel):
    model_config = STRICT
    project_id: int = Field(ge=1)
    start_date: date
    end_date: date

    @model_validator(mode='after')
    def period(self):
        if self.start_date>self.end_date or (self.end_date-self.start_date).days>364:
            raise ValueError('区间须按时间顺序且不超过 365 天')
        from datetime import datetime, timedelta, timezone
        if self.end_date>datetime.now(timezone(timedelta(hours=8))).date():
            raise ValueError('结束日期不能晚于北京时间今天')
        return self


class EvaluationLabel(BaseModel):
    model_config = STRICT
    id: str = Field(min_length=1,max_length=100)
    type: Literal['issue','task','decision','risk']
    title: str = Field(min_length=1,max_length=200)
    evidence_message_ids: list[int] = Field(min_length=1,max_length=100)


class PredictionReview(BaseModel):
    model_config = STRICT
    prediction_id: int = Field(ge=1)
    label_id: str | None = Field(default=None,max_length=100)
    field_evidence_verified: bool | None = None


class EvaluationTimings(BaseModel):
    model_config = {**STRICT, 'allow_inf_nan': False}
    rule_seconds: float | None = Field(default=None,ge=0,le=86400)
    ai_wait_seconds: float | None = Field(default=None,ge=0,le=86400)
    ai_review_seconds: float | None = Field(default=None,ge=0,le=86400)
    export_seconds: float | None = Field(default=None,ge=0,le=86400)


class EvaluationRequest(BaseModel):
    model_config = STRICT
    project_id: int = Field(ge=1)
    dataset_label: str = Field(min_length=1,max_length=100)
    mode: Literal['simulated','replay','work_trial'] = 'simulated'
    data_origin: Literal['constructed','deidentified_work'] = 'constructed'
    scope_message_ids: list[int] = Field(min_length=1,max_length=2000)
    labels: list[EvaluationLabel] = Field(max_length=500)
    rule_reviews: list[PredictionReview] = Field(default_factory=list,max_length=2000)
    ai_reviews: list[PredictionReview] = Field(default_factory=list,max_length=2000)
    timings: EvaluationTimings = Field(default_factory=EvaluationTimings)
    reviewer_label: str = Field(min_length=1,max_length=100)
    familiarity_note: str = Field(default='',max_length=500)
    attested: Literal[True]

    @model_validator(mode='after')
    def truthful_mode(self):
        if self.mode=='work_trial' and self.data_origin!='deidentified_work':
            raise ValueError('岗位试用必须标明脱敏工作样本')
        if self.mode=='simulated' and self.data_origin!='constructed':
            raise ValueError('模拟评测仅用于构造样例')
        return self
