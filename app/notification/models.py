from django.db import models
from common.models import CommonModel


class Notification(CommonModel):
    # type = models.CharField(max_length=50)
    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )
    message = models.CharField(max_length=200)
    is_read = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta(CommonModel.Meta):
        indexes = [
            # 안 읽은 알림 목록 조회: filter(user=..., is_read=False).order_by('-created_at')
            models.Index(fields=["user", "is_read", "created_at"], name="notif_user_read_created_idx"),
        ]

    def __str__(self):
        return f"Notification to {self.user} ({self.id})"

