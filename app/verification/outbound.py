from ninja import Schema


class PhoneVerificationSuccessResponseSchema(Schema):
    message: str
    phone_hash: str


class UsernamePhoneVerificationResponseSchema(Schema):
    email: str
    phone_number: str
    message: str
    login_method: str


class PasswordPhoneVerificationResponseSchema(Schema):
    email: str
    phone_number: str
    message: str
    phone_hash: str
