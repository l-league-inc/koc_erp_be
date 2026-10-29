from ninja import Field, FilterSchema, ModelSchema
from notice.models import Notice
from typing import Optional

from api.choices import enum_field


class NoticeCreateSchema(ModelSchema):
    class Meta:
        model = Notice
        exclude = (
            "id",
            "user",
            "view_count",
            "is_notification_sent",
            "created_at",
            "updated_at",
            "deleted_at",
        )


class NoticeUpdateSchema(ModelSchema):
    title: Optional[str] = Field(None, description="Title")
    content: Optional[str] = Field(None, description="Content")

    class Meta:
        model = Notice
        exclude = (
            "id",
            "user",
            "view_count",
            "is_notification_sent",
            "created_at",
            "updated_at",
            "deleted_at",
        )


class NoticeFilterSchema(FilterSchema):
    type: Optional[str] = enum_field(
        "공지 타입", Notice.TypeChoices, default=None, q="type"
    )
    render: Optional[str] = enum_field(
        "렌더링 방식", Notice.RenderChoices, default=None, q="render"
    )
    hidden: Optional[bool] = Field(None, q="hidden", description="비공개 여부")
