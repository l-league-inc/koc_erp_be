from ninja import ModelSchema
from notice.models import Notice


class NoticeResponseSchema(ModelSchema):
    class Meta:
        model = Notice
        fields = "__all__"
