from typing import Any

from ninja import ModelSchema, Schema
from pydantic import ValidationInfo, model_validator
from pydantic.fields import Field
from pydantic.functional_validators import ModelWrapValidatorHandler

from user.models import User


class UserLoginResponseSchema(Schema):
    access: str
    refresh: str
    status: str
    is_flutter: bool


class UserUpdateResponseSchema(ModelSchema):
    class Meta:
        model = User
        exclude = (
            "id",
            "type",
            "status",
            "password",
            "last_login",
            "is_active",
            "is_staff",
            "is_superuser",
            "date_joined",
            "first_name",
            "last_name",
            "groups",
            "user_permissions",
        )


class UserTinyResponseSchema(ModelSchema):
    class Meta:
        model = User
        fields = [
            "id",
            "nickname",
            "email",
            "social_email",
            "login_method",
            "status",
            "name",
            "phone_number",
            "type",
            "profile_image",
        ]
        fields_optional = ["email"]

    @model_validator(mode="wrap")
    @classmethod
    def _allow_none_user(
        cls,
        values: Any,
        handler: ModelWrapValidatorHandler,
        info: ValidationInfo,
    ) -> Any:
        # FK가 None이면 Schema wrap validator가 DjangoGetter(None)을 만들어
        # email 등 필수 필드 검증이 실패한다. null 유저는 None으로 통과시킨다.
        if values is None:
            return None
        nested = getattr(values, "_obj", values)
        if nested is None:
            return None
        return handler(values)


class UserDetailResponseSchema(ModelSchema):
    class Meta:
        model = User
        exclude = (
            "password",
            "is_active",
            "is_staff",
            "is_superuser",
            "first_name",
            "last_name",
            "groups",
            "user_permissions",
        )
        fields_optional = ["email"]


class UserMeResponseSchema(ModelSchema):
    unread_notification_count: int = Field(0, description="읽지 않은 알림 개수")

    class Meta:
        model = User
        exclude = (
            "password",
            "is_active",
            "is_staff",
            "is_superuser",
            "first_name",
            "last_name",
            "groups",
            "user_permissions",
        )
        fields_optional = ["email"]

    @staticmethod
    def resolve_unread_notification_count(obj: Any) -> int:
        return int(getattr(obj, "unread_notification_count", 0) or 0)
