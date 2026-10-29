from ninja import ModelSchema, Schema
from notification.models import Notification


class NotificationResponseSchema(ModelSchema):
    class Meta:
        model = Notification
        exclude = [
            "updated_at",
            "deleted_at",
        ]


class UnreadCountResponseSchema(Schema):
    unread_count: int


class TodoDigestResponseSchema(Schema):
    message: str
    sent_count: int
    target_count: int