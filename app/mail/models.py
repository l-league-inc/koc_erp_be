from django.conf import settings
from django.db import models

from common.models import CommonModel


class UserMailAccount(CommonModel):
    """유저별 Daum IMAP/SMTP 로그인 정보입니다."""

    class Provider(models.TextChoices):
        DAUM = ("daum", "Daum")

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mail_account",
        help_text="사용자",
    )
    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        default=Provider.DAUM,
        help_text="메일 제공자",
    )
    username = models.CharField(max_length=255, help_text="Daum 로그인 아이디")
    password_encrypted = models.TextField(help_text="암호화된 앱 비밀번호")
    is_verified = models.BooleanField(default=False, help_text="연결 테스트 성공 여부")
    last_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="마지막 연결 확인 시각",
    )
    last_error = models.TextField(blank=True, default="", help_text="마지막 연결 오류")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_user_mail_account",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.provider}:{self.username}"
