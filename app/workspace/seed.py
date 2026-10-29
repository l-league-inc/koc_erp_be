from django.contrib.auth import get_user_model
from django.db import transaction

from workspace.models import Database, Property, View, Workspace, WorkspaceMember

User = get_user_model()

WORKSPACE_SLUG = "koc"
WORKSPACE_NAME = "KOC"


def _options(*pairs: tuple[str, str]) -> dict:
    return {
        "options": [
            {"id": option_id, "name": name, "color": "gray"}
            for option_id, name in pairs
        ]
    }


STATUS_BASE = (
    ("waiting", "대기"),
    ("in_progress", "진행 중"),
    ("done", "완료"),
)
STATUS_WITH_RECEIVED = (
    ("waiting", "대기"),
    ("in_progress", "진행 중"),
    ("received", "접수"),
    ("done", "완료"),
)

DEFAULT_VIEWS = (
    ("전체", []),
    ("진행중", [{"property": "status", "op": "eq", "value": "진행 중"}]),
    ("내 담당", [{"property": "owner", "op": "eq", "value": "me"}]),
    ("완료", [{"property": "status", "op": "eq", "value": "완료"}]),
)

DATABASES = (
    {
        "slug": "hr",
        "name": "인사 / 근태관리",
        "description": "출근, 휴가, 출장을 기록합니다.",
        "icon": "users",
        "properties": (
            ("title", "제목", Property.Type.TITLE, {}),
            (
                "status",
                "상태",
                Property.Type.STATUS,
                _options(
                    ("waiting", "대기"),
                    ("in_progress", "진행 중"),
                    ("done", "완료"),
                    ("check_in", "출근"),
                    ("check_out", "퇴근"),
                    ("leave", "휴가"),
                    ("trip", "출장"),
                ),
            ),
            ("kind", "구분", Property.Type.SELECT, _options(("check_in", "출근"), ("leave", "휴가"), ("trip", "출장"))),
            ("due_date", "일자", Property.Type.DATE, {}),
            ("owner", "담당", Property.Type.PEOPLE, {}),
            ("memo", "메모", Property.Type.TEXT, {}),
        ),
    },
    {
        "slug": "daily",
        "name": "일일 업무 관리",
        "description": "하루 업무와 진행 상태를 기록합니다.",
        "icon": "check",
        "properties": (
            ("title", "제목", Property.Type.TITLE, {}),
            ("status", "상태", Property.Type.STATUS, _options(*STATUS_BASE)),
            ("owner", "담당", Property.Type.PEOPLE, {}),
            ("due_date", "일자", Property.Type.DATE, {}),
            ("memo", "메모", Property.Type.TEXT, {}),
        ),
    },
    {
        "slug": "gov",
        "name": "정부과제 및 거래처",
        "description": "과제와 거래처 업무를 기록합니다.",
        "icon": "building",
        "properties": (
            ("title", "제목", Property.Type.TITLE, {}),
            ("status", "상태", Property.Type.STATUS, _options(*STATUS_BASE)),
            ("kind", "구분", Property.Type.SELECT, _options(("project", "과제"), ("client", "거래처"))),
            ("owner", "담당", Property.Type.PEOPLE, {}),
            ("due_date", "일자", Property.Type.DATE, {}),
            ("memo", "메모", Property.Type.TEXT, {}),
        ),
    },
    {
        "slug": "purchase",
        "name": "구매 / 발주 / 재고",
        "description": "품목, 수량, 안전재고를 기록합니다.",
        "icon": "package",
        "properties": (
            ("title", "품목", Property.Type.TITLE, {}),
            ("quantity", "수량", Property.Type.NUMBER, {}),
            ("safety_stock", "안전재고", Property.Type.NUMBER, {}),
            (
                "status",
                "상태",
                Property.Type.STATUS,
                _options(
                    ("waiting", "대기"),
                    ("in_progress", "진행 중"),
                    ("review", "검토 필요"),
                    ("done", "완료"),
                ),
            ),
            ("owner", "담당", Property.Type.PEOPLE, {}),
            ("due_date", "일자", Property.Type.DATE, {}),
        ),
    },
    {
        "slug": "sales",
        "name": "영업 / 견적 / A/S",
        "description": "견적과 A/S 접수를 기록합니다.",
        "icon": "briefcase",
        "properties": (
            ("title", "제목", Property.Type.TITLE, {}),
            ("kind", "구분", Property.Type.SELECT, _options(("quote", "견적"), ("as", "A/S"))),
            (
                "status",
                "상태",
                Property.Type.STATUS,
                _options(("received", "접수"), ("in_progress", "진행 중"), ("done", "완료")),
            ),
            ("owner", "담당", Property.Type.PEOPLE, {}),
            ("due_date", "일자", Property.Type.DATE, {}),
            ("amount", "금액", Property.Type.NUMBER, {}),
        ),
    },
    {
        "slug": "docs",
        "name": "문서 및 사내규정",
        "description": "사내 문서와 규정 페이지를 보관합니다.",
        "icon": "file",
        "properties": (
            ("title", "제목", Property.Type.TITLE, {}),
            ("status", "상태", Property.Type.STATUS, _options(*STATUS_WITH_RECEIVED)),
            (
                "category",
                "분류",
                Property.Type.SELECT,
                _options(
                    ("sample", "샘플/기획"),
                    ("purchase", "구매/발주"),
                    ("sales_as", "영업 A/S"),
                    ("policy", "사내규정"),
                ),
            ),
            ("owner", "담당", Property.Type.PEOPLE, {}),
            ("due_date", "일자", Property.Type.DATE, {}),
        ),
    },
)


def _ensure_properties(database: Database, properties: tuple) -> None:
    for position, (slug, name, prop_type, config) in enumerate(properties):
        if database.properties.filter(slug=slug).exists():
            continue
        Property.objects.create(
            database=database,
            name=name,
            slug=slug,
            type=prop_type,
            config=config,
            position=position,
        )


def _ensure_views(database: Database) -> None:
    for position, (name, filters) in enumerate(DEFAULT_VIEWS):
        if database.views.filter(name=name).exists():
            continue
        View.objects.create(
            database=database,
            name=name,
            type=View.Type.TABLE,
            filters=filters,
            sorts=[],
            position=position,
        )


def _ensure_members(workspace: Workspace) -> None:
    has_owner = workspace.members.filter(role=WorkspaceMember.Role.OWNER).exists()
    active_users = User.objects.filter(status=User.UserStatusChoice.ACTIVE).order_by("id")
    for user in active_users:
        if workspace.members.filter(user=user).exists():
            continue
        role = WorkspaceMember.Role.MEMBER
        if not has_owner:
            role = WorkspaceMember.Role.OWNER
            has_owner = True
        WorkspaceMember.objects.create(workspace=workspace, user=user, role=role)


@transaction.atomic
def seed_koc_workspace() -> Workspace:
    """KOC 워크스페이스와 여섯 업무 데이터베이스를 없으면 만듭니다."""
    workspace = Workspace.objects.filter(slug=WORKSPACE_SLUG).first()
    if workspace is None:
        workspace = Workspace.objects.create(name=WORKSPACE_NAME, slug=WORKSPACE_SLUG)

    for position, spec in enumerate(DATABASES):
        database = workspace.databases.filter(slug=spec["slug"]).first()
        if database is None:
            database = Database.objects.create(
                workspace=workspace,
                name=spec["name"],
                slug=spec["slug"],
                description=spec["description"],
                icon=spec["icon"],
                position=position,
            )
        _ensure_properties(database, spec["properties"])
        _ensure_views(database)
    _ensure_members(workspace)
    return workspace
