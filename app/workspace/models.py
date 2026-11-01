from django.conf import settings
from django.db import models

from common.models import CommonModel


class Workspace(CommonModel):
    """회사 단위 Notion형 워크스페이스입니다."""

    name = models.CharField(max_length=100, help_text="이름")
    slug = models.SlugField(max_length=50, help_text="슬러그")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_workspace_slug",
            )
        ]

    def __str__(self) -> str:
        return self.name


class WorkspaceMember(CommonModel):
    """워크스페이스 멤버입니다."""

    class Role(models.TextChoices):
        OWNER = ("owner", "소유자")
        ADMIN = ("admin", "관리자")
        MEMBER = ("member", "멤버")

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="members",
        help_text="워크스페이스",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
        help_text="사용자",
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.MEMBER,
        help_text="역할",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_workspace_member",
            )
        ]

    def __str__(self) -> str:
        return f"{self.workspace_id}:{self.user_id}"


class Database(CommonModel):
    """Notion 데이터베이스입니다. 레코드 스키마의 컨테이너입니다."""

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="databases",
        help_text="워크스페이스",
    )
    name = models.CharField(max_length=100, help_text="이름")
    slug = models.SlugField(max_length=50, help_text="영역 키")
    description = models.TextField(blank=True, default="", help_text="설명")
    icon = models.CharField(max_length=50, blank=True, default="", help_text="아이콘")
    position = models.PositiveIntegerField(default=0, help_text="정렬 순서")

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "slug"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_database_slug",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Property(CommonModel):
    """데이터베이스 컬럼 정의입니다."""

    class Type(models.TextChoices):
        TITLE = ("title", "제목")
        TEXT = ("text", "텍스트")
        NUMBER = ("number", "숫자")
        SELECT = ("select", "선택")
        MULTI_SELECT = ("multi_select", "다중 선택")
        STATUS = ("status", "상태")
        DATE = ("date", "날짜")
        CHECKBOX = ("checkbox", "체크박스")
        URL = ("url", "URL")
        EMAIL = ("email", "이메일")
        PHONE = ("phone", "전화")
        PEOPLE = ("people", "사람")
        FILES = ("files", "파일")
        RELATION = ("relation", "관계")

    database = models.ForeignKey(
        Database,
        on_delete=models.CASCADE,
        related_name="properties",
        help_text="데이터베이스",
    )
    name = models.CharField(max_length=100, help_text="이름")
    slug = models.SlugField(max_length=50, help_text="속성 키")
    type = models.CharField(max_length=20, choices=Type.choices, help_text="타입")
    config = models.JSONField(default=dict, help_text="옵션·관계 대상")
    position = models.PositiveIntegerField(default=0, help_text="정렬 순서")

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["database", "slug"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_property_slug",
            ),
            models.UniqueConstraint(
                fields=["database"],
                condition=models.Q(deleted_at__isnull=True, type="title"),
                name="unique_database_title_property",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.database_id}:{self.slug}"


class Record(CommonModel):
    """데이터베이스 행이자 페이지입니다."""

    database = models.ForeignKey(
        Database,
        on_delete=models.CASCADE,
        related_name="records",
        help_text="데이터베이스",
    )
    title = models.CharField(max_length=300, help_text="제목")
    icon = models.CharField(max_length=50, blank=True, default="", help_text="아이콘")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_workspace_records",
        help_text="작성자",
    )
    last_edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edited_workspace_records",
        help_text="마지막 수정자",
    )

    def __str__(self) -> str:
        return self.title


class PropertyValue(CommonModel):
    """레코드의 속성 값입니다. 타입에 맞는 컬럼만 채웁니다."""

    record = models.ForeignKey(
        Record,
        on_delete=models.CASCADE,
        related_name="values",
        help_text="레코드",
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="record_values",
        help_text="속성",
    )
    text_value = models.TextField(blank=True, default="", help_text="텍스트 값")
    number_value = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="숫자 값",
    )
    date_start = models.DateTimeField(null=True, blank=True, help_text="시작 일시")
    date_end = models.DateTimeField(null=True, blank=True, help_text="종료 일시")
    checkbox_value = models.BooleanField(null=True, blank=True, help_text="체크 값")
    json_value = models.JSONField(null=True, blank=True, help_text="복합 값")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["record", "property"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_record_property_value",
            )
        ]


class RelationLink(CommonModel):
    """relation 속성의 레코드 연결입니다."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="links",
        help_text="관계 속성",
    )
    from_record = models.ForeignKey(
        Record,
        on_delete=models.CASCADE,
        related_name="outgoing_links",
        help_text="출발 레코드",
    )
    to_record = models.ForeignKey(
        Record,
        on_delete=models.CASCADE,
        related_name="incoming_links",
        help_text="대상 레코드",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["property", "from_record", "to_record"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_relation_link",
            )
        ]


class Block(CommonModel):
    """페이지 본문 블록입니다."""

    class Type(models.TextChoices):
        PARAGRAPH = ("paragraph", "문단")
        HEADING_1 = ("heading_1", "제목 1")
        HEADING_2 = ("heading_2", "제목 2")
        HEADING_3 = ("heading_3", "제목 3")
        BULLETED_LIST = ("bulleted_list", "글머리 목록")
        NUMBERED_LIST = ("numbered_list", "번호 목록")
        TO_DO = ("to_do", "할 일")
        QUOTE = ("quote", "인용")
        DIVIDER = ("divider", "구분선")
        TOGGLE = ("toggle", "토글")
        CALLOUT = ("callout", "콜아웃")
        CODE = ("code", "코드")
        IMAGE = ("image", "이미지")

    record = models.ForeignKey(
        Record,
        on_delete=models.CASCADE,
        related_name="blocks",
        help_text="레코드",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        help_text="부모 블록",
    )
    type = models.CharField(max_length=20, choices=Type.choices, help_text="블록 타입")
    content = models.JSONField(default=dict, help_text="블록 내용")
    position = models.PositiveIntegerField(default=0, help_text="정렬 순서")

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.record_id}:{self.type}"


class View(CommonModel):
    """데이터베이스 보기입니다."""

    class Type(models.TextChoices):
        TABLE = ("table", "표")
        BOARD = ("board", "보드")
        LIST = ("list", "목록")
        CALENDAR = ("calendar", "캘린더")
        GALLERY = ("gallery", "갤러리")

    database = models.ForeignKey(
        Database,
        on_delete=models.CASCADE,
        related_name="views",
        help_text="데이터베이스",
    )
    name = models.CharField(max_length=100, help_text="이름")
    type = models.CharField(
        max_length=10,
        choices=Type.choices,
        default=Type.TABLE,
        help_text="보기 타입",
    )
    filters = models.JSONField(default=list, help_text="필터")
    sorts = models.JSONField(default=list, help_text="정렬")
    config = models.JSONField(default=dict, help_text="보기 설정")
    position = models.PositiveIntegerField(default=0, help_text="정렬 순서")

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return self.name


class RecordActivity(CommonModel):
    """레코드 생성·수정 스냅샷입니다."""

    class Action(models.TextChoices):
        CREATED = ("created", "생성")
        UPDATED = ("updated", "수정")

    class Source(models.TextChoices):
        USER = ("user", "사용자")
        MCP = ("mcp", "MCP")
        AGENT = ("agent", "에이전트")

    record = models.ForeignKey(
        Record,
        on_delete=models.CASCADE,
        related_name="activities",
        help_text="레코드",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_record_activities",
        help_text="실행한 사용자",
    )
    action = models.CharField(max_length=20, choices=Action.choices, help_text="동작")
    changes = models.JSONField(default=dict, help_text="변경 스냅샷")
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.USER,
        help_text="호출 출처",
    )


class RecordComment(CommonModel):
    """레코드 댓글입니다. 답글은 한 단계만 둡니다."""

    record = models.ForeignKey(
        Record,
        on_delete=models.CASCADE,
        related_name="comments",
        help_text="레코드",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_record_comments",
        help_text="작성자",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
        help_text="부모 댓글",
    )
    body = models.TextField(help_text="본문")

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.record_id}:{self.id}"


class DatabaseTemplate(CommonModel):
    """새 레코드에 복사할 값과 블록입니다."""

    database = models.ForeignKey(
        Database,
        on_delete=models.CASCADE,
        related_name="templates",
        help_text="데이터베이스",
    )
    name = models.CharField(max_length=100, help_text="이름")
    title = models.CharField(max_length=300, blank=True, default="", help_text="기본 제목")
    values = models.JSONField(default=dict, help_text="속성 값")
    blocks = models.JSONField(default=list, help_text="블록")
    position = models.PositiveIntegerField(default=0, help_text="정렬 순서")

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return self.name
