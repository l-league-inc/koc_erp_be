from typing import Any, Optional

from ninja import Field, ModelSchema, Schema

from workspace.models import Property


class WorkspaceCreateSchema(Schema):
    name: str
    slug: str


class WorkspaceUpdateSchema(Schema):
    name: Optional[str] = None
    slug: Optional[str] = None


class DatabaseCreateSchema(Schema):
    """데이터베이스를 만듭니다. section이 같으면 한 사이드바 페이지입니다."""

    workspace_id: int = Field(description="워크스페이스 id")
    name: str = Field(description="데이터베이스 이름")
    slug: str = Field(description="데이터베이스 키. 영문 소문자로 시작하고 숫자와 _만 씁니다.")
    description: str = Field("", description="설명")
    icon: str = Field("", description="아이콘 키")
    section: str = Field("", description="페이지 이름. 사이드바 묶음 제목입니다.")
    section_slug: str = Field(
        "",
        description="페이지 키. 비우거나, 영문 소문자로 시작하고 숫자와 _만 씁니다.",
    )
    position: int = Field(0, description="같은 페이지 안에서의 정렬 순서")


class DatabaseUpdateSchema(Schema):
    """보낸 키만 바꿉니다. section_slug를 빈 문자열로 보내면 페이지 묶음을 해제합니다."""

    name: Optional[str] = Field(None, description="데이터베이스 이름")
    slug: Optional[str] = Field(None, description="데이터베이스 키")
    description: Optional[str] = Field(None, description="설명")
    icon: Optional[str] = Field(None, description="아이콘 키")
    section: Optional[str] = Field(None, description="페이지 이름")
    section_slug: Optional[str] = Field(None, description="페이지 키. 빈 문자열이면 묶음이 없습니다.")
    position: Optional[int] = Field(None, description="정렬 순서")


class PropertyCreateSchema(ModelSchema):
    config: dict = Field(default_factory=dict)
    position: int = 0

    class Meta:
        model = Property
        fields = ["name", "slug", "type", "config", "position"]


class PropertyUpdateSchema(Schema):
    name: Optional[str] = None
    slug: Optional[str] = None
    type: Optional[str] = None
    config: Optional[dict] = None
    position: Optional[int] = None


class ViewWriteSchema(Schema):
    name: str
    type: str = "table"
    filters: list[dict] = Field(default_factory=list)
    sorts: list[dict] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    position: int = 0


class ViewUpdateSchema(Schema):
    name: Optional[str] = None
    type: Optional[str] = None
    filters: Optional[list[dict]] = None
    sorts: Optional[list[dict]] = None
    config: Optional[dict] = None
    position: Optional[int] = None


class BlockWriteSchema(Schema):
    type: str
    content: dict = Field(default_factory=dict)
    position: int = 0
    children: list["BlockWriteSchema"] = Field(default_factory=list)


class BlockCreateSchema(Schema):
    type: str
    content: dict = Field(default_factory=dict)
    position: int = 0
    parent_id: Optional[int] = None


class BlockUpdateSchema(Schema):
    type: Optional[str] = None
    content: Optional[dict] = None
    position: Optional[int] = None
    parent_id: Optional[int] = None


class RecordCreateSchema(Schema):
    title: Optional[str] = None
    icon: str = ""
    template_id: Optional[int] = None
    values: dict[str, Any] = Field(default_factory=dict)
    blocks: list[BlockWriteSchema] = Field(default_factory=list)


class RecordUpdateSchema(Schema):
    title: Optional[str] = None
    icon: Optional[str] = None
    values: Optional[dict[str, Any]] = None
    blocks: Optional[list[BlockWriteSchema]] = None


class CommentCreateSchema(Schema):
    body: str
    parent_id: Optional[int] = None


class TemplateWriteSchema(Schema):
    name: str
    title: str = ""
    values: dict[str, Any] = Field(default_factory=dict)
    blocks: list[BlockWriteSchema] = Field(default_factory=list)
    position: int = 0


class TemplateUpdateSchema(Schema):
    name: Optional[str] = None
    title: Optional[str] = None
    values: Optional[dict[str, Any]] = None
    blocks: Optional[list[BlockWriteSchema]] = None
    position: Optional[int] = None


class RecordFilterSchema(Schema):
    property: str
    op: str
    value: Any = None


class RecordSortSchema(Schema):
    property: str
    direction: str = "asc"


class RecordQuerySchema(Schema):
    """레코드 조회. database_slug, database_id, view_id를 모두 비우면 통합관리대장입니다."""

    database_slug: Optional[str] = Field(
        None,
        description="데이터베이스 키. 비우면 멤버인 모든 데이터베이스를 조회합니다.",
    )
    database_id: Optional[int] = Field(
        None,
        description="데이터베이스 id. database_slug 대신 쓸 수 있습니다.",
    )
    view_id: Optional[int] = Field(
        None,
        description="보기 id. 이 보기의 필터를 요청 필터보다 먼저 적용합니다.",
    )
    q: Optional[str] = Field(None, description="제목 검색어")
    filters: list[RecordFilterSchema] = Field(default_factory=list, description="속성 필터")
    sorts: list[RecordSortSchema] = Field(default_factory=list, description="정렬")
    page: int = Field(1, ge=1, description="페이지 번호")
    page_size: int = Field(20, ge=1, le=100, description="페이지 크기. 상한은 100입니다.")


BlockWriteSchema.model_rebuild()
RecordCreateSchema.model_rebuild()
RecordUpdateSchema.model_rebuild()
TemplateWriteSchema.model_rebuild()
TemplateUpdateSchema.model_rebuild()
