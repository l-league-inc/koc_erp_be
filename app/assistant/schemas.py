from datetime import datetime
from typing import Any, Optional

from ninja import Schema


class SessionCreateSchema(Schema):
    workspace_id: int
    database_slug: str = ""


class SessionResponseSchema(Schema):
    id: int
    workspace_id: int
    database_slug: str
    created_at: datetime
    updated_at: datetime


class SessionListItemSchema(SessionResponseSchema):
    preview: str


class MessageCreateSchema(Schema):
    content: str


class MessageResponseSchema(Schema):
    id: int
    role: str
    content: str
    created_at: datetime


class ProposedActionResponseSchema(Schema):
    id: int
    kind: str
    status: str
    payload: dict
    result: dict


class SessionDetailSchema(SessionResponseSchema):
    messages: list[MessageResponseSchema]
    proposed_actions: list[ProposedActionResponseSchema]


class MessageResultSchema(Schema):
    message: MessageResponseSchema
    proposed_actions: list[ProposedActionResponseSchema]


class ConfirmSchema(Schema):
    action_ids: list[int]


class ConfirmedRecordSchema(Schema):
    action_id: int
    record_id: int
    title: str


class ConfirmResultSchema(Schema):
    proposed_actions: list[ProposedActionResponseSchema]
    records: list[ConfirmedRecordSchema]


class WorkbotWriteSchema(Schema):
    workspace_id: int
    name: str
    description: str = ""
    instruction: str = ""
    spec: dict
    schedule: str
    enabled: bool = True
    database_slug: str
    estimated_minutes: int = 0


class WorkbotUpdateSchema(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    instruction: Optional[str] = None
    spec: Optional[dict] = None
    schedule: Optional[str] = None
    enabled: Optional[bool] = None
    database_slug: Optional[str] = None
    estimated_minutes: Optional[int] = None


class WorkbotResponseSchema(Schema):
    id: int
    workspace_id: int
    owner_id: int
    name: str
    description: str
    instruction: str
    spec: dict
    schedule: str
    enabled: bool
    database_slug: str
    estimated_minutes: int
    next_run_at: Optional[datetime]
    last_run_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class WorkbotDraftSchema(Schema):
    workspace_id: int
    instruction: str


class WorkbotDraftResponseSchema(Schema):
    name: str
    description: str
    instruction: str
    database_slug: str
    schedule: str
    estimated_minutes: int
    spec: dict[str, Any]


class WorkbotRunResponseSchema(Schema):
    id: int
    workbot_id: int
    status: str
    summary: str
    record_ids: list
    payload: dict
    created_at: datetime


class WorkbotStatsResponseSchema(Schema):
    active_count: int
    month_run_count: int
    success_rate: float
    saved_minutes: int
