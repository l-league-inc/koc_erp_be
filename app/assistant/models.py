from django.conf import settings
from django.db import models

from common.models import CommonModel


class AgentSession(CommonModel):
    """앱 안 업무 대화입니다."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_sessions",
        help_text="사용자",
    )
    workspace = models.ForeignKey(
        "workspace.Workspace",
        on_delete=models.CASCADE,
        related_name="agent_sessions",
        help_text="워크스페이스",
    )
    database_slug = models.SlugField(
        max_length=50,
        blank=True,
        default="",
        help_text="비어 있으면 전체 영역",
    )

    def __str__(self) -> str:
        return f"{self.user_id}:{self.workspace_id}"


class AgentMessage(CommonModel):
    """대화 메시지입니다."""

    class Role(models.TextChoices):
        USER = ("user", "사용자")
        ASSISTANT = ("assistant", "도우미")

    session = models.ForeignKey(
        AgentSession,
        on_delete=models.CASCADE,
        related_name="messages",
        help_text="대화",
    )
    role = models.CharField(max_length=20, choices=Role.choices, help_text="역할")
    content = models.TextField(help_text="본문")

    def __str__(self) -> str:
        return f"{self.session_id}:{self.role}"


class ProposedAction(CommonModel):
    """확정 전에 멈춰 둔 레코드·스킬 생성·수정입니다."""

    class Kind(models.TextChoices):
        CREATE_RECORD = ("create_record", "레코드 생성")
        UPDATE_RECORD = ("update_record", "레코드 수정")
        CREATE_SKILL = ("create_skill", "스킬 생성")
        UPDATE_SKILL = ("update_skill", "스킬 수정")

    class Status(models.TextChoices):
        PENDING = ("pending", "대기")
        CONFIRMED = ("confirmed", "확정")
        REJECTED = ("rejected", "거절")

    session = models.ForeignKey(
        AgentSession,
        on_delete=models.CASCADE,
        related_name="proposed_actions",
        help_text="대화",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, help_text="동작")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="상태",
    )
    payload = models.JSONField(default=dict, help_text="적용할 내용")
    result = models.JSONField(default=dict, blank=True, help_text="확정 결과")

    def __str__(self) -> str:
        return f"{self.session_id}:{self.kind}:{self.status}"


class Skill(CommonModel):
    """워크스페이스 업무 대화 스킬입니다. 고정 스킬은 파일이며 이 테이블에 없습니다."""

    workspace = models.ForeignKey(
        "workspace.Workspace",
        on_delete=models.CASCADE,
        related_name="skills",
        help_text="워크스페이스",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="skills",
        help_text="만든 사용자",
    )
    name = models.SlugField(max_length=50, help_text="이름")
    description = models.CharField(max_length=300, help_text="설명")
    body = models.TextField(help_text="절차")
    enabled = models.BooleanField(default=True, help_text="활성")

    class Meta(CommonModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_skill_name",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Workbot(CommonModel):
    """저장된 지시로 반복 실행하는 워크봇입니다."""

    workspace = models.ForeignKey(
        "workspace.Workspace",
        on_delete=models.CASCADE,
        related_name="workbots",
        help_text="워크스페이스",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workbots",
        help_text="만든 사용자",
    )
    name = models.CharField(max_length=100, help_text="이름")
    description = models.TextField(blank=True, default="", help_text="설명")
    instruction = models.TextField(blank=True, default="", help_text="원문 지시")
    spec = models.JSONField(default=dict, help_text="실행 명세")
    schedule = models.CharField(max_length=100, help_text="크론 일정")
    enabled = models.BooleanField(default=True, help_text="활성")
    database_slug = models.SlugField(max_length=50, help_text="대상 영역")
    estimated_minutes = models.PositiveIntegerField(default=0, help_text="1회 예상 분")
    next_run_at = models.DateTimeField(null=True, blank=True, help_text="다음 실행")
    last_run_at = models.DateTimeField(null=True, blank=True, help_text="마지막 실행")

    class Meta(CommonModel.Meta):
        indexes = [
            models.Index(fields=["enabled", "next_run_at"], name="workbot_due_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class WorkbotRun(CommonModel):
    """워크봇 실행 결과입니다."""

    class Status(models.TextChoices):
        SUCCESS = ("success", "성공")
        WAITING = ("waiting", "확인 대기")
        FAILED = ("failed", "실패")

    workbot = models.ForeignKey(
        Workbot,
        on_delete=models.CASCADE,
        related_name="runs",
        help_text="워크봇",
    )
    status = models.CharField(max_length=20, choices=Status.choices, help_text="상태")
    summary = models.TextField(blank=True, default="", help_text="요약")
    record_ids = models.JSONField(default=list, help_text="연결된 레코드")
    payload = models.JSONField(default=dict, blank=True, help_text="확인 대기 내용")

    def __str__(self) -> str:
        return f"{self.workbot_id}:{self.status}"
