from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from common.models import CommonModel


class DocumentSpace(CommonModel):
    """워크스페이스 안의 공유 문서함 또는 개인 문서함입니다."""

    class Kind(models.TextChoices):
        SHARED = ("shared", "공유")
        PERSONAL = ("personal", "개인")

    workspace = models.ForeignKey(
        "workspace.Workspace",
        on_delete=models.CASCADE,
        related_name="document_spaces",
        help_text="워크스페이스",
    )
    kind = models.CharField(
        max_length=10,
        choices=Kind.choices,
        help_text="공유 또는 개인",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="personal_document_spaces",
        help_text="개인 문서함 소유자",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(deleted_at__isnull=True, kind="shared"),
                name="unique_document_shared_space",
            ),
            models.UniqueConstraint(
                fields=["workspace", "owner"],
                condition=models.Q(deleted_at__isnull=True, kind="personal"),
                name="unique_document_personal_space",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="shared", owner__isnull=True)
                    | models.Q(kind="personal", owner__isnull=False)
                ),
                name="document_space_owner_matches_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.workspace_id}:{self.kind}:{self.owner_id or '-'}"


class DocumentFolder(CommonModel):
    """문서함 폴더입니다. 공간마다 루트 폴더가 하나 있습니다."""

    space = models.ForeignKey(
        DocumentSpace,
        on_delete=models.CASCADE,
        related_name="folders",
        help_text="문서함",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        help_text="상위 폴더",
    )
    name = models.CharField(max_length=255, blank=True, default="", help_text="이름")
    is_root = models.BooleanField(default=False, help_text="공간 루트 여부")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_document_folders",
        help_text="만든 사람",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["space"],
                condition=models.Q(deleted_at__isnull=True, is_root=True),
                name="unique_document_root_folder",
            ),
            models.UniqueConstraint(
                fields=["space", "parent", "name"],
                condition=models.Q(deleted_at__isnull=True, is_root=False),
                name="unique_document_folder_name",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_root=True, parent__isnull=True)
                    | models.Q(is_root=False, parent__isnull=False)
                ),
                name="document_folder_root_parent",
            ),
        ]

    def __str__(self) -> str:
        return self.name or f"root:{self.space_id}"


class DocumentFile(CommonModel):
    """S3에 올린 회사 문서의 메타데이터입니다."""

    folder = models.ForeignKey(
        DocumentFolder,
        on_delete=models.CASCADE,
        related_name="files",
        help_text="폴더",
    )
    original_filename = models.CharField(max_length=255, help_text="원본 파일명")
    object_key = models.CharField(max_length=500, help_text="S3 객체 키")
    content_type = models.CharField(max_length=100, help_text="콘텐츠 타입")
    size = models.PositiveIntegerField(help_text="바이트 크기")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents",
        help_text="올린 사람",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["object_key"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_document_object_key",
            )
        ]

    def __str__(self) -> str:
        return self.original_filename


class DocumentIndex(CommonModel):
    """문서 추출 본문과 검색용 요약입니다."""

    class Status(models.TextChoices):
        PENDING = ("pending", "대기")
        PROCESSING = ("processing", "처리 중")
        READY = ("ready", "완료")
        FAILED = ("failed", "실패")
        SKIPPED = ("skipped", "제외")

    class Source(models.TextChoices):
        LOCAL = ("local", "로컬")
        LLM = ("llm", "언어 모델")

    file = models.OneToOneField(
        DocumentFile,
        on_delete=models.CASCADE,
        related_name="index",
        help_text="문서",
    )
    extracted_text = models.TextField(blank=True, default="", help_text="추출 본문")
    description_ko = models.TextField(blank=True, default="", help_text="한국어 요약")
    tags_ko = models.TextField(blank=True, default="", help_text="한국어 태그")
    filename = models.CharField(max_length=255, blank=True, default="", help_text="검색용 파일명")
    search_vector = SearchVectorField(null=True, help_text="전문검색 벡터")
    index_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="색인 상태",
    )
    index_source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.LOCAL,
        help_text="색인 출처",
    )
    error = models.TextField(blank=True, default="", help_text="실패 사유")

    class Meta:
        indexes = [
            GinIndex(fields=["search_vector"], name="document_index_search_gin"),
        ]

    def __str__(self) -> str:
        return f"{self.file_id}:{self.index_status}"


class DocumentDownload(CommonModel):
    """문서 다운로드 URL을 만든 기록입니다."""

    class Source(models.TextChoices):
        USER = ("user", "사용자")
        MCP = ("mcp", "MCP")

    file = models.ForeignKey(
        DocumentFile,
        on_delete=models.CASCADE,
        related_name="downloads",
        help_text="문서",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_downloads",
        help_text="받은 사람",
    )
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.USER,
        help_text="요청 출처",
    )

    def __str__(self) -> str:
        return f"{self.file_id}:{self.user_id}:{self.source}"


class DocumentMailLog(CommonModel):
    """문서 메일 발송 이력입니다. 발송 기능은 이후에 이 행을 만듭니다."""

    class Status(models.TextChoices):
        PENDING = ("pending", "대기")
        SENT = ("sent", "발송")
        FAILED = ("failed", "실패")

    file = models.ForeignKey(
        DocumentFile,
        on_delete=models.CASCADE,
        related_name="mail_logs",
        help_text="문서",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_document_mails",
        help_text="보낸 사람",
    )
    recipients = models.JSONField(default=list, help_text="받는 사람 목록")
    subject = models.CharField(max_length=300, blank=True, default="", help_text="제목")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="발송 상태",
    )
    sent_at = models.DateTimeField(null=True, blank=True, help_text="발송 시각")
    error = models.TextField(blank=True, default="", help_text="실패 사유")

    def __str__(self) -> str:
        return f"{self.file_id}:{self.status}"
