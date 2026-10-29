import re
from api.exceptions import CustomValidationError
from django.contrib.auth import get_user_model


User = get_user_model()


class UsernameValidator:
    def __call__(self, value):
        pattern = re.compile("^(?=.*[A-Za-z])[A-Za-z\d]{6,}$")
        if not pattern.match(value):
            raise CustomValidationError({"username": "아이디 형식이 올바르지 않습니다."})

        if User.objects.filter(username=value).exists():
            raise CustomValidationError({"username": "이미 사용중인 아이디입니다."})


class PasswordValidator:
    def __call__(self, value):
        pattern = re.compile(
            r"^(?=.*[A-Za-z])(?=.*\d)(?=.*[!@#$%^&*(),.?\":{}|<>])[A-Za-z\d!@#$%^&*(),.?\":{}|<>]{8,16}$"
        )
        if not pattern.match(value):
            raise CustomValidationError({"password": "비밀번호 형식이 올바르지 않습니다."})
