from django.db import models
import random
import string


class PhonenumberVerification(models.Model):
    phone_number = models.CharField(max_length=20, help_text="휴대폰 번호")
    code = models.CharField(max_length=6, editable=False, help_text="인증 코드")
    is_verified = models.BooleanField(default=False, help_text="인증 여부")
    request_at = models.DateTimeField(auto_now_add=True, help_text="요청 시각")
    hash = models.CharField(max_length=100, null=True, blank=True, help_text="해시")

    def save(self, *args, **kwargs):
        if not self.id and not self.code:
            self.code = "".join(random.choices(string.digits, k=6))
        super().save(*args, **kwargs)

    def refresh(self):
        self.code = "".join(random.choices(string.digits, k=6))
        self.is_verified = False
        self.hash = None
        self.save()

    def __str__(self):
        return f"{self.phone_number} 휴대폰 인증"


class UsernamePhoneVerification(models.Model):
    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="username_phone_verifications",
    )
    code = models.CharField(max_length=6, editable=False, help_text="인증 코드")
    is_verified = models.BooleanField(default=False, help_text="인증 여부")
    request_at = models.DateTimeField(auto_now_add=True, help_text="요청 시각")

    def save(self, *args, **kwargs):
        if not self.id and not self.code:
            self.code = "".join(random.choices(string.digits, k=6))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} 아이디 찾기 휴대폰 인증"


class PasswordPhoneVerification(models.Model):
    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="password_phone_verifications",
    )
    code = models.CharField(max_length=6, editable=False, help_text="인증 코드")
    is_verified = models.BooleanField(default=False, help_text="인증 여부")
    request_at = models.DateTimeField(auto_now_add=True, help_text="요청 시각")
    hash = models.CharField(max_length=100, null=True, blank=True, help_text="해시")
    is_used = models.BooleanField(default=False, help_text="비밀번호 변경 사용 여부")

    def save(self, *args, **kwargs):
        if not self.id and not self.code:
            self.code = "".join(random.choices(string.digits, k=6))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} 비밀번호 찾기 휴대폰 인증"
