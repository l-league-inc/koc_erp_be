from datetime import datetime
from typing import Any, Optional

from ninja import Field, Schema


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
    """사이드바 데이터베이스. section_slug가 같으면 한 페이지입니다."""

    id: int
    workspace_id: int
    name: str = Field(description="데이터베이스 이름")
    slug: str = Field(description="데이터베이스 키")
    description: str = Field(description="설명")
    icon: str = Field(description="아이콘 키")
    section: str = Field(description="페이지 이름. 묶음이 없으면 빈 문자열입니다.")
    section_slug: str = Field(description="페이지 키. 묶음이 없으면 빈 문자열입니다.")
    position: int = Field(description="정렬 순서")
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
    """레코드. 통합관리대장에서는 database_slug와 database_name으로 영역을 구분합니다."""

    id: int
    database_id: int
    database_slug: str = Field(description="데이터베이스 키")
    database_name: str = Field(description="데이터베이스 이름")
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
