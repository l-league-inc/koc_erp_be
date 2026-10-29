from django.db import models
from common.models import CommonModel


class Notice(CommonModel):
    """Notice Model Definition"""

    class TypeChoices(models.TextChoices):
        notice = ("notice", "공지")
        event = ("event", "이벤트")
        urgent = ("urgent", "긴급공지")

    class RenderChoices(models.TextChoices):
        editor = ("editor", "에디터")
        url = ("url", "URL")

    title = models.CharField(max_length=300, help_text="제목")
    content = models.TextField(help_text="내용 또는 url")
    user = models.ForeignKey(
        "user.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="작성자",
    )
    hidden = models.BooleanField(default=False, help_text="비공개 여부")
    type = models.CharField(
        max_length=10,
        choices=TypeChoices.choices,
        default=TypeChoices.notice,
        help_text="공지 타입",
    )
    render = models.CharField(
        max_length=10,
        choices=RenderChoices.choices,
        default=RenderChoices.editor,
        help_text="렌더링 방식",
    )
    view_count = models.PositiveIntegerField(default=0, help_text="조회수")
    is_notification_sent = models.BooleanField(
        default=False, help_text="알림 전송 여부"
    )

    def __str__(self):
        return f"{self.type} - {self.title}"
