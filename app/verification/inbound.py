from ninja import Schema
from ninja.errors import HttpError
from pydantic import field_validator
import re


class PhoneVerificationRequestSchema(Schema):
    phone_number: str


class PhoneVerificationCheckRequestSchema(Schema):
    code: str
    phone_number: str


class PasswordPhoneVerificationRequestSchema(Schema):
    email: str
    phone_number: str


class PasswordPhoneVerificationCheckRequestSchema(Schema):
    code: str
    email: str
    phone_number: str


class PasswordPhoneVerificationChangeRequestSchema(Schema):
    phone_number: str
    phone_hash: str
    new_password: str
    new_password_confirm: str

    @field_validator("new_password")
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

    @field_validator("new_password_confirm")
    def passwords_match(cls, v, values):
        values = values.data
        if "new_password" in values and v != values["new_password"]:
            raise HttpError(400, "비밀번호가 일치하지 않습니다.")
        return v
