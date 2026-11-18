from django.db import models, transaction

from common.models import CommonModel


class DriveRelease(CommonModel):
    """사용자가 받는 KOC Drive 설치 파일입니다."""

    version = models.CharField(max_length=32, help_text="예: 1.1.0")
    notes = models.TextField(blank=True, default="", help_text="사용자에게 보여줄 변경 내용")
    object_key = models.CharField(max_length=500, help_text="S3 객체 키")
    sha256 = models.CharField(max_length=64, help_text="설치 파일 SHA-256")
    size = models.PositiveBigIntegerField(default=0, help_text="바이트")
    is_current = models.BooleanField(default=True, help_text="이 버전을 사용자에게 배포")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Drive 릴리스"
        verbose_name_plural = "Drive 릴리스"

    def __str__(self) -> str:
        state = "현재" if self.is_current else "이전"
        return f"{self.version} ({state})"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.is_current and self.deleted_at is None:
                DriveRelease.objects.exclude(pk=self.pk).filter(is_current=True).update(is_current=False)
