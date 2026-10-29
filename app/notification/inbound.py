from ninja import FilterSchema, Field
from typing import Optional


class NotificationFilterSchema(FilterSchema):
    is_read: Optional[bool] = Field(None, q="is_read", description="읽음 여부")
    