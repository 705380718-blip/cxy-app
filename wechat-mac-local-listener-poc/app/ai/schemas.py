from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STRICT = ConfigDict(extra='forbid', strict=True)


class AISettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    provider: Literal['deepseek'] = 'deepseek'
    base_url: Literal['https://api.deepseek.com', 'https://api.deepseek.com/v1'] = 'https://api.deepseek.com'
    model: str = Field(default='deepseek-flash', min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9._-]+$')
    timeout_seconds: int = Field(default=60, ge=1, le=60)
    max_output_tokens: int = Field(default=4096, ge=128, le=8192)
    max_calls_per_day: int = Field(default=100, ge=1, le=1000)
    max_batch_messages: int = Field(default=80, ge=1, le=80)
    max_input_chars: int = Field(default=18000, ge=1000, le=30000)


class TaskBasis(BaseModel):
    model_config = STRICT
    kind: Literal['request','commitment']
    message_id: int = Field(ge=1)
    quote: str = Field(min_length=4,max_length=500)


class ItemCandidate(BaseModel):
    model_config = STRICT
    candidate_key: str = Field(min_length=1,max_length=100)
    target_item_id: int | None = Field(default=None,ge=1)
    type: Literal['issue','task','decision','risk']
    title: str = Field(min_length=1,max_length=200)
    task_basis: TaskBasis | None = None
    owner_ref: str | None = Field(default=None,max_length=100)
    due_text: str | None = Field(default=None,max_length=200)
    due_at: None = None  # Dates are resolved by local code using evidence timestamps.
    suggested_status: Literal['open','in_progress','waiting_confirmation','resolved'] = 'open'
    latest_progress: str | None = Field(default=None,max_length=2000)
    evidence_message_ids: list[int] = Field(min_length=1,max_length=100)
    field_evidence: dict[Literal['owner','deadline','progress'],list[int]] = Field(default_factory=dict)
    needs_confirmation: list[str] = Field(default_factory=list,max_length=20)

    @field_validator('owner_ref','due_text','latest_progress', mode='before')
    @classmethod
    def empty_means_unknown(cls, value):
        return None if isinstance(value,str) and not value.strip() else value

    @model_validator(mode='after')
    def check_field_evidence(self):
        evidence = set(self.evidence_message_ids)
        if len(evidence) != len(self.evidence_message_ids) or any(mid < 1 for mid in evidence):
            raise ValueError('duplicate or invalid evidence')
        for ids in self.field_evidence.values():
            if not ids or not set(ids).issubset(evidence):
                raise ValueError('field evidence must be a nonempty subset')
        for field,value in [('owner',self.owner_ref),('deadline',self.due_text),('progress',self.latest_progress)]:
            if value and not self.field_evidence.get(field):
                raise ValueError('field missing evidence')
        return self

    @field_validator('needs_confirmation')
    @classmethod
    def short_flags(cls, values):
        if any(len(s)>100 for s in values):
            raise ValueError('confirmation label too long')
        return values


class AnalysisResult(BaseModel):
    model_config = STRICT
    schema_version: Literal[1]
    items: list[ItemCandidate] = Field(max_length=80)

    def validate_scope(self, message_ids, person_refs, item_ids=()):
        keys = set()
        for item in self.items:
            if item.candidate_key in keys or not set(item.evidence_message_ids).issubset(message_ids):
                raise ValueError('candidate duplicate or evidence outside input')
            keys.add(item.candidate_key)
            if item.owner_ref and item.owner_ref not in person_refs:
                raise ValueError('unknown person')
            if item.target_item_id is not None and item.target_item_id not in item_ids:
                raise ValueError('target outside source')
            # No model response can close a business item.
            if item.suggested_status == 'resolved':
                item.suggested_status = 'waiting_confirmation'
                item.needs_confirmation.append('human_resolution_required')
        return self


def resolve_deadline(due_text: str | None, evidence_timestamp: str) -> str | None:
    if not due_text:
        return None
    match = re.fullmatch(r'(今天|明天|后天)\s*(\d{1,2}):(\d{2})',due_text.strip())
    if not match:
        return None
    hour, minute = int(match[2]),int(match[3])
    if hour>23 or minute>59:
        return None
    anchor = datetime.fromisoformat(evidence_timestamp)
    if anchor.tzinfo is None:
        raise ValueError('evidence timestamp requires timezone')
    from datetime import timezone
    anchor = anchor.astimezone(timezone(timedelta(hours=8)))
    days = {'今天':0,'明天':1,'后天':2}[match[1]]
    return (anchor+timedelta(days=days)).replace(hour=hour,minute=minute,second=0,microsecond=0).isoformat()
