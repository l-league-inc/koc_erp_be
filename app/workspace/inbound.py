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
    workspace_id: int
    name: str
    slug: str
    description: str = ""
    icon: str = ""
    position: int = 0


class DatabaseUpdateSchema(Schema):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    position: Optional[int] = None


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
    database_slug: Optional[str] = None
    database_id: Optional[int] = None
    view_id: Optional[int] = None
    q: Optional[str] = None
    filters: list[RecordFilterSchema] = Field(default_factory=list)
    sorts: list[RecordSortSchema] = Field(default_factory=list)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


BlockWriteSchema.model_rebuild()
RecordCreateSchema.model_rebuild()
RecordUpdateSchema.model_rebuild()
TemplateWriteSchema.model_rebuild()
TemplateUpdateSchema.model_rebuild()
