from ninja import ModelSchema, Schema, FilterSchema
from user.models import User
from ninja.errors import HttpError
from pydantic import field_validator, model_validator
from pydantic.fields import Field
from typing import Optional
import re

from api.choices import enum_field


class UserSignupSchema(Schema):
    email: str
    password: str
    password2: str
    phone_number: str = Field(
        description="전화번호",
    )
    marketing_agree: Optional[bool] = Field(
        False,
        description="마케팅 수신 동의",
    )
    type: Optional[str] = enum_field(
        "유저 타입",
        User.UserTypeChoices,
        default=User.UserTypeChoices.MEMBER,
    )
    phone_hash: str = Field(
        description="전화번호 해시",
    )

    @field_validator("email")
    def validate_email(cls, v):
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, v):
            raise HttpError(400, "유효하지 않은 이메일 형식입니다.")
        return v

    @field_validator("phone_number")
    def validate_phone_number(cls, v):
        pattern = r"^\d{10,12}$"
        if v and not re.match(pattern, v):
            raise HttpError(400, "유효하지 않은 전화번호 형식입니다.")
        return v

    @field_validator("password")
    def password_length(cls, v):
        if len(v) < 8:
            raise HttpError(400, "비밀번호는 8자 이상이어야 합니다.")
        if not re.search(r"[a-z]", v):
            raise HttpError(400, "비밀번호는 최소 하나의 소문자를 포함해야 합니다.")
        if not re.search(r"\d", v):
            raise HttpError(400, "비밀번호는 최소 하나의 숫자를 포함해야 합니다.")
        # if not re.search(r"[A-Z]", v):
        #     raise HttpError(400, "비밀번호는 최소 하나의 대문자를 포함해야 합니다.")
        # if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
        #     raise HttpError(400, "비밀번호는 최소 하나의 특수문자를 포함해야 합니다.")
        return v

    @field_validator("password2")
    def passwords_match(cls, v, values):
        values = values.data
        if "password" in values and v != values["password"]:
            raise HttpError(400, "비밀번호가 일치하지 않습니다.")
        return v

    @field_validator("type")
    def user_type_check(cls, v, values):
        if v not in User.UserTypeChoices.values:
            raise HttpError(400, "유저 타입이 올바르지 않습니다.")
        return v


class UserLoginSchema(Schema):
    email: str
    password: str


class LogoutSchema(Schema):
    refresh: Optional[str] = Field(None, description="Refresh Token")


class TokenRefreshSchema(Schema):
    refresh: Optional[str] = Field(None, description="Refresh Token")


class UserUpdateSchema(ModelSchema):
    class Meta:
        model = User
        exclude = (
            "id",
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
            "email",
        )

    @field_validator("type", check_fields=False)
    def user_type_check(cls, value: str):
        if value not in User.UserTypeChoices.values:
            raise HttpError(400, "올바르지 않은 유저 타입입니다.")
        return value


class AdminUserUpdateSchema(ModelSchema):
    class Meta:
        model = User
        fields = (
            "phone_number",
            "status",
            "withdraw_reason",
        )
        optional_fields = (
            "phone_number",
            "status",
            "withdraw_reason",
        )

    @field_validator("status", check_fields=False)
    def user_status_check(cls, value: str):
        if value not in User.UserStatusChoice.values:
            raise HttpError(400, "올바르지 않은 유저 상태입니다.")
        return value


class CheckUsernameSchema(Schema):
    username: str


class ChangePasswordSchema(Schema):
    password: str
    new_password: str
    new_password_confirm: str

    @field_validator("new_password")
    def password_length(cls, v, values):
        if len(v) < 8:
            raise HttpError(400, "비밀번호는 8자 이상이어야 합니다.")
        return v

    @field_validator("new_password_confirm")
    def passwords_match(cls, v, values):
        values = values.data
        if "new_password" in values and v != values["new_password"]:
            raise HttpError(400, "새 비밀번호가 일치하지 않습니다.")
        return v


class UserListFilterSchema(FilterSchema):
    type: Optional[str] = enum_field(
        "유저 타입", User.UserTypeChoices, default=None, q="type"
    )
    status: Optional[str] = enum_field(
        "유저 상태", User.UserStatusChoice, default=None, q="status"
    )
    name: str = Field(None, q="name", description="이름")
    email: str = Field(None, q="email", description="이메일")
    phone_number: str = Field(None, q="phone_number", description="전화번호")
    search: str = Field(
        None,
        q=[
            "name__icontains",
            "email__icontains",
            "phone_number__icontains",
        ],
    )


class VerifyEmailRequestSchema(Schema):
    email: str


class ResetPasswordSchema(Schema):
    new_password: str
    new_password_confirm: str

    @model_validator(mode="after")
    def password_confirm(cls, values):
        if values.new_password != values.new_password_confirm:
            raise HttpError(400, "비밀번호가 일치하지 않아요.")
        return values


class UserWithdrawSchema(Schema):
    password: str
    withdraw_reason: Optional[str] = None


# 토스 로그인 스키마
class TossLoginRequestSchema(Schema):
    """토스 로그인 요청 스키마"""

    authorizationCode: str = Field(description="토스 인가 코드")
    referrer: str = Field(description="토스 referrer (sandbox 또는 DEFAULT)")


class TossLoginResponseSchema(Schema):
    """토스 로그인 응답 스키마"""

    access: str = Field(description="JWT Access Token")
    refresh: str = Field(description="JWT Refresh Token")
    status: str = Field(description="유저 상태")
    user_id: int = Field(description="유저 ID")


class TossUserInfoSchema(Schema):
    """토스 사용자 정보 스키마"""

    userKey: int
    name: Optional[str] = None
    phone: Optional[str] = None
    birthday: Optional[str] = None
    ci: Optional[str] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    email: Optional[str] = None
    scope: str
    agreedTerms: list


class TossRevokeRequestSchema(Schema):
    """토스 로그인 연결 끊기 요청 스키마"""

    userKey: Optional[int] = Field(None, description="토스 사용자 키 (선택)")


class TossCallbackSchema(Schema):
    """토스 로그인 연결 끊기 콜백 스키마"""

    userKey: Optional[int] = Field(None, description="토스 사용자 키")
    referrer: Optional[str] = Field(
        "UNLINK",
        description="연결 끊기 경로 (UNLINK, WITHDRAWAL_TERMS, WITHDRAWAL_TOSS)",
    )


class TossRefreshTokenRequestSchema(Schema):
    """토스 AccessToken 재발급 요청 스키마"""

    pass  # 현재 로그인한 사용자의 refresh_token을 사용


class TossRefreshTokenResponseSchema(Schema):
    """토스 AccessToken 재발급 응답 스키마"""

    tokenType: str = Field(description="토큰 타입 (Bearer)")
    accessToken: str = Field(description="새로 발급된 AccessToken")
    refreshToken: str = Field(description="새로 발급된 RefreshToken")
    expiresIn: int = Field(description="만료 시간(초)")
    scope: str = Field(description="인가된 scope")
