from datetime import datetime
from typing import Any, Optional

from ninja import Schema


class WorkspaceResponseSchema(Schema):
    id: int
    name: str
    slug: str
    role: str
    created_at: datetime
    updated_at: datetime


class WorkspaceMemberResponseSchema(Schema):
    user_id: int
    name: str
    role: str


class PropertyResponseSchema(Schema):
    id: int
    database_id: int
    name: str
    slug: str
    type: str
    config: dict
    position: int
    created_at: datetime
    updated_at: datetime


class ViewResponseSchema(Schema):
    id: int
    database_id: int
    name: str
    type: str
    filters: list
    sorts: list
    config: dict
    position: int
    created_at: datetime
    updated_at: datetime


class DatabaseResponseSchema(Schema):
    id: int
    workspace_id: int
    name: str
    slug: str
    description: str
    icon: str
    section: str
    section_slug: str
    position: int
    created_at: datetime
    updated_at: datetime


class DatabaseDetailResponseSchema(DatabaseResponseSchema):
    properties: list[PropertyResponseSchema]
    views: list[ViewResponseSchema]


class BlockResponseSchema(Schema):
    id: int
    record_id: int
    parent_id: Optional[int]
    type: str
    content: dict
    position: int
    created_at: datetime
    updated_at: datetime


class RecordResponseSchema(Schema):
    id: int
    database_id: int
    database_slug: str
    database_name: str
    title: str
    icon: str
    values: dict[str, Any]
    created_by_id: Optional[int]
    last_edited_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class RecordDetailResponseSchema(RecordResponseSchema):
    blocks: list[BlockResponseSchema]


class RecordQueryResponseSchema(Schema):
    count: int
    page: int
    page_size: int
    data: list[RecordResponseSchema]


class ActivityResponseSchema(Schema):
    id: int
    action: str
    source: str
    actor_id: Optional[int]
    actor_name: str
    changes: dict
    created_at: datetime


class CommentResponseSchema(Schema):
    id: int
    record_id: int
    parent_id: Optional[int]
    author_id: Optional[int]
    author_name: str
    body: str
    created_at: datetime
    updated_at: datetime


class TemplateResponseSchema(Schema):
    id: int
    database_id: int
    name: str
    title: str
    values: dict
    blocks: list
    position: int
    created_at: datetime
    updated_at: datetime


class TrashRecordResponseSchema(Schema):
    id: int
    title: str
    icon: str
    database_id: int
    database_slug: str
    database_name: str
    deleted_at: datetime
