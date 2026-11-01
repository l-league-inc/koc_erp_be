import csv
import hashlib
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.db import transaction
from ninja.errors import HttpError

from workspace.models import Database, Property, Record, View, Workspace, WorkspaceMember
from workspace.seed import ensure_koc_workspace
from workspace.utils import apply_values

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "koc"
KOREAN_DATE = re.compile(
    r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일"
    r"(?:\s*(오전|오후)\s*(\d{1,2}):(\d{2}))?"
)
TRUE_TOKENS = {"yes", "y", "true", "1", "예"}
FALSE_TOKENS = {"no", "n", "false", "0", "아니오"}
OPTION_COLORS = {
    "재직": "green",
    "정상": "green",
    "선정": "green",
    "완료": "green",
    "승인": "green",
    "종결": "green",
    "진행 중": "blue",
    "검토중": "blue",
    "작성중": "blue",
    "접수": "blue",
    "접수완료": "blue",
    "예정": "blue",
    "미선정": "red",
    "반려": "red",
    "기밀": "red",
    "확인필요": "yellow",
}


def col(
    header: str,
    slug: str,
    prop_type: str,
    *,
    relation: str = "",
    defaults: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "header": header,
        "slug": slug,
        "type": prop_type,
        "relation": relation,
        "defaults": defaults,
    }


PAGES: tuple[dict[str, Any], ...] = (
    {
        "page_slug": "hr",
        "page_name": "인사 / 근태 관리",
        "slug": "employees",
        "name": "임직원",
        "description": "임직원 명부입니다.",
        "icon": "users",
        "csv": "employees.csv",
        "columns": (
            col("이름", "title", Property.Type.TITLE),
            col("담당업무", "duty", Property.Type.TEXT),
            col("부서", "department", Property.Type.TEXT),
            col("사내 이메일", "email", Property.Type.EMAIL),
            col("사번", "employee_no", Property.Type.TEXT),
            col("연락처", "phone", Property.Type.PHONE),
            col("위치", "location", Property.Type.TEXT),
            col("입사일", "hired_on", Property.Type.DATE),
            col("재직상태", "employment_status", Property.Type.STATUS),
            col("직급", "rank", Property.Type.SELECT),
            col("직무", "job", Property.Type.TEXT),
            col("퇴사일", "left_on", Property.Type.DATE),
        ),
    },
    {
        "page_slug": "hr",
        "page_name": "인사 / 근태 관리",
        "slug": "attendance",
        "name": "근무 기록",
        "description": "출근과 퇴근 기록입니다.",
        "icon": "clock",
        "csv": "attendance.csv",
        "title_from": ("근무일",),
        "title_suffix": "출근",
        "columns": (
            col("근무기록명", "title", Property.Type.TITLE),
            col("근무메모", "memo", Property.Type.TEXT),
            col("근무일", "work_date", Property.Type.DATE),
            col("근무형태", "work_type", Property.Type.SELECT),
            col("근태상태", "attendance_status", Property.Type.STATUS),
            col("등록시각(자동)", "registered_at", Property.Type.DATE),
            col("임직원", "employee", Property.Type.RELATION, relation="employees"),
            col("출근시각", "check_in", Property.Type.DATE),
            col("퇴근시각", "check_out", Property.Type.DATE),
            col("확인담당", "confirmed_by", Property.Type.RELATION, relation="employees"),
        ),
    },
    {
        "page_slug": "hr",
        "page_name": "인사 / 근태 관리",
        "slug": "leave",
        "name": "휴가",
        "description": "휴가 신청입니다.",
        "icon": "calendar",
        "csv": "leave.csv",
        "columns": (
            col("휴가신청명", "title", Property.Type.TITLE),
            col("사용일수", "days", Property.Type.NUMBER),
            col(
                "승인상태",
                "approval_status",
                Property.Type.STATUS,
                defaults=("대기", "승인", "반려"),
            ),
            col("승인자", "approver", Property.Type.RELATION, relation="employees"),
            col("시작일", "start_date", Property.Type.DATE),
            col("임직원", "employee", Property.Type.RELATION, relation="employees"),
            col("종료일", "end_date", Property.Type.DATE),
            col("휴가사유", "reason", Property.Type.TEXT),
            col("휴가유형", "leave_type", Property.Type.SELECT),
        ),
    },
    {
        "page_slug": "hr",
        "page_name": "인사 / 근태 관리",
        "slug": "trip",
        "name": "출장",
        "description": "출장 신청입니다.",
        "icon": "map",
        "csv": "trip.csv",
        "columns": (
            col("출장 건명", "title", Property.Type.TITLE),
            col("기안 첨부자료", "attachment", Property.Type.TEXT),
            col("신청자", "applicant", Property.Type.RELATION, relation="employees"),
            col("예상 경비", "estimated_cost", Property.Type.NUMBER),
            col("접수일시(자동)", "submitted_at", Property.Type.DATE),
            col("출장 목적", "purpose", Property.Type.TEXT),
            col("출장기간", "period", Property.Type.DATE),
            col("출장지", "destination", Property.Type.TEXT),
        ),
    },
    {
        "page_slug": "daily",
        "page_name": "일일 업무 관리",
        "slug": "tasks",
        "name": "일일 업무",
        "description": "하루 업무와 진행 상태입니다.",
        "icon": "check",
        "csv": "tasks.csv",
        "columns": (
            col("업무명", "title", Property.Type.TITLE),
            col("결과링크", "result_url", Property.Type.URL),
            col("관련 거래처", "client", Property.Type.RELATION, relation="clients"),
            col("관련 정부과제", "project", Property.Type.RELATION, relation="projects"),
            col("담당 임직원", "owner", Property.Type.RELATION, relation="employees"),
            col("마감일", "due_date", Property.Type.DATE),
            col("업무내용", "body", Property.Type.TEXT),
            col("업무유형", "task_type", Property.Type.SELECT),
            col("업무일", "work_date", Property.Type.DATE),
            col("완료", "done", Property.Type.CHECKBOX),
            col("우선순위", "priority", Property.Type.SELECT),
            col("진행상태", "status", Property.Type.STATUS),
        ),
    },
    {
        "page_slug": "gov",
        "page_name": "정부과제 및 거래처",
        "slug": "projects",
        "name": "정부과제",
        "description": "정부과제와 협약 일정입니다.",
        "icon": "building",
        "csv": "projects.csv",
        "columns": (
            col("사업명", "title", Property.Type.TITLE),
            col("공고/협약 링크", "notice_url", Property.Type.URL),
            col("공고일", "announced_on", Property.Type.DATE),
            col("담당 임직원", "owner", Property.Type.RELATION, relation="employees"),
            col("비고", "memo", Property.Type.TEXT),
            col("원본 관리번호", "source_no", Property.Type.TEXT),
            col("자부담금", "self_fund", Property.Type.NUMBER),
            col("접수마감일", "deadline", Property.Type.DATE),
            col("주관기관", "agency", Property.Type.TEXT),
            col("중간보고일", "interim_on", Property.Type.DATE),
            col("지원금액", "grant_amount", Property.Type.NUMBER),
            col("진행상태", "status", Property.Type.STATUS),
            col("최종 결과물", "deliverable", Property.Type.TEXT),
            col("최종보고일", "final_on", Property.Type.DATE),
            col("협약시작일", "contract_start", Property.Type.DATE),
            col("협약종료일", "contract_end", Property.Type.DATE),
        ),
    },
    {
        "page_slug": "gov",
        "page_name": "정부과제 및 거래처",
        "slug": "expenses",
        "name": "과제 지출",
        "description": "정부과제 집행 지출입니다.",
        "icon": "receipt",
        "csv": "expenses.csv",
        "columns": (
            col("지출명", "title", Property.Type.TITLE),
            col("견적서 링크", "quote_url", Property.Type.URL),
            col("공급가액", "supply_amount", Property.Type.NUMBER),
            col("관련 과제", "project", Property.Type.RELATION, relation="projects"),
            col("부가세", "vat", Property.Type.NUMBER),
            col("비고", "memo", Property.Type.TEXT),
            col("비교견적서 링크", "compare_url", Property.Type.URL),
            col("세금계산서 링크", "tax_url", Property.Type.URL),
            col("지출 거래처", "client", Property.Type.RELATION, relation="clients"),
            col("지출구분", "expense_kind", Property.Type.SELECT, defaults=("확인필요",)),
            col("지출일", "spent_on", Property.Type.DATE),
            col("지출합계", "total", Property.Type.NUMBER),
            col(
                "집행상태",
                "execution_status",
                Property.Type.STATUS,
                defaults=("대기", "진행 중", "완료"),
            ),
            col("집행증빙 링크", "proof_url", Property.Type.URL),
            col("집행항목", "item", Property.Type.TEXT),
        ),
    },
    {
        "page_slug": "gov",
        "page_name": "정부과제 및 거래처",
        "slug": "clients",
        "name": "거래처",
        "description": "거래처 정보입니다.",
        "icon": "briefcase",
        "csv": "clients.csv",
        "columns": (
            col("업체명", "title", Property.Type.TITLE),
            col(
                "거래상태",
                "account_status",
                Property.Type.STATUS,
                defaults=("거래중", "중단"),
            ),
            col("거래유형", "account_type", Property.Type.SELECT),
            col("거래처번호", "client_no", Property.Type.TEXT),
            col("계약서 링크", "contract_url", Property.Type.URL),
            col("내부담당", "owner", Property.Type.RELATION, relation="employees"),
            col("담당자명", "contact_name", Property.Type.TEXT),
            col("대표자", "ceo", Property.Type.TEXT),
            col("비고", "memo", Property.Type.TEXT),
            col("사업자등록번호", "business_no", Property.Type.TEXT),
            col("사업자등록증 링크", "license_url", Property.Type.URL),
            col("연락처", "phone", Property.Type.PHONE),
            col("이메일", "email", Property.Type.EMAIL),
            col("주소", "address", Property.Type.TEXT),
        ),
    },
    {
        "page_slug": "purchase",
        "page_name": "구매 / 발주 / 재고",
        "slug": "inventory",
        "name": "재고",
        "description": "품목과 현재고입니다.",
        "icon": "package",
        "csv": "inventory.csv",
        "columns": (
            col("품목명", "title", Property.Type.TITLE),
            col("단위", "unit", Property.Type.SELECT),
            col("보관위치", "location", Property.Type.TEXT),
            col("분류", "category", Property.Type.SELECT),
            col("비고", "memo", Property.Type.TEXT),
            col("안전재고", "safety_stock", Property.Type.NUMBER),
            col("재고경고", "stock_alert", Property.Type.STATUS),
            col("재고담당", "owner", Property.Type.RELATION, relation="employees"),
            col("최근 발주", "latest_order", Property.Type.TEXT),
            col("최근입고일", "received_on", Property.Type.DATE),
            col("품목코드", "item_code", Property.Type.TEXT),
            col("현재고", "quantity", Property.Type.NUMBER),
        ),
    },
    {
        "page_slug": "sales",
        "page_name": "영업 / 견적 / A/S",
        "slug": "quotes",
        "name": "견적",
        "description": "견적서입니다.",
        "icon": "file",
        "csv": "quotes.csv",
        "columns": (
            col("견적명", "title", Property.Type.TITLE),
            col("견적 거래처", "client", Property.Type.RELATION, relation="clients"),
            col("견적번호", "quote_no", Property.Type.TEXT),
            col("견적상태", "status", Property.Type.STATUS),
            col("견적서 Drive 링크", "drive_url", Property.Type.URL),
            col("공급가액", "supply_amount", Property.Type.NUMBER),
            col("공임", "labor_cost", Property.Type.NUMBER),
            col("담당자", "contact", Property.Type.TEXT),
            col("발행일", "issued_on", Property.Type.DATE),
            col("부가세", "vat", Property.Type.NUMBER),
            col("부품비", "parts_cost", Property.Type.NUMBER),
            col("비고", "memo", Property.Type.TEXT),
            col("운영팀", "team", Property.Type.SELECT),
            col("원본 견적 ID", "source_id", Property.Type.TEXT),
            col("원본 파일명", "source_file", Property.Type.TEXT),
            col("유효기간", "valid_until", Property.Type.DATE),
            col("접수대수", "unit_count", Property.Type.NUMBER),
            col("택배비", "shipping_cost", Property.Type.NUMBER),
            col("합계금액", "total", Property.Type.NUMBER),
        ),
    },
    {
        "page_slug": "sales",
        "page_name": "영업 / 견적 / A/S",
        "slug": "after_service",
        "name": "A/S",
        "description": "A/S 접수와 처리입니다.",
        "icon": "wrench",
        "csv": "after_service.csv",
        "columns": (
            col("접수건명", "title", Property.Type.TITLE),
            col("관련 거래처", "client", Property.Type.RELATION, relation="clients"),
            col("담당 임직원", "owner", Property.Type.RELATION, relation="employees"),
            col("비용구분", "cost_type", Property.Type.SELECT),
            col("서비스/제품", "product", Property.Type.SELECT),
            col("수리대수", "unit_count", Property.Type.NUMBER),
            col(
                "심각도",
                "severity",
                Property.Type.SELECT,
                defaults=("낮음", "보통", "높음"),
            ),
            col("완료일", "completed_on", Property.Type.DATE),
            col("운영팀", "team", Property.Type.SELECT),
            col("원본 문서번호", "source_no", Property.Type.TEXT),
            col("원본 파일명", "source_file", Property.Type.TEXT),
            col("장비 일련번호", "serial_no", Property.Type.TEXT),
            col("접수내용", "body", Property.Type.TEXT),
            col("접수번호", "ticket_no", Property.Type.TEXT),
            col("접수일", "received_on", Property.Type.DATE),
            col("조치결과", "result", Property.Type.TEXT),
            col("증빙링크", "proof_url", Property.Type.URL),
            col("처리 보고", "report", Property.Type.TEXT),
            col("처리기한", "due_date", Property.Type.DATE),
            col("처리담당", "handler", Property.Type.RELATION, relation="employees"),
            col("처리상태", "status", Property.Type.STATUS),
            col("청구금액", "amount", Property.Type.NUMBER),
        ),
    },
    {
        "page_slug": "docs",
        "page_name": "문서 및 사내규정",
        "slug": "company_docs",
        "name": "회사 문서",
        "description": "회사 문서와 드라이브 링크입니다.",
        "icon": "file",
        "csv": "company_docs.csv",
        "columns": (
            col("문서명", "title", Property.Type.TITLE),
            col("Google Drive 링크", "drive_url", Property.Type.URL),
            col("관련 거래처", "client", Property.Type.RELATION, relation="clients"),
            col("관련 정부과제", "project", Property.Type.RELATION, relation="projects"),
            col("담당 임직원", "owner", Property.Type.RELATION, relation="employees"),
            col("담당자", "contact", Property.Type.TEXT),
            col("발행일", "issued_on", Property.Type.DATE),
            col("버전", "version", Property.Type.TEXT),
            col("보안등급", "security", Property.Type.SELECT),
            col("분류", "category", Property.Type.SELECT),
            col("비고", "memo", Property.Type.TEXT),
            col("유효기한", "expires_on", Property.Type.DATE),
        ),
    },
    {
        "page_slug": "docs",
        "page_name": "문서 및 사내규정",
        "slug": "policies",
        "name": "사내규정",
        "description": "사내 규정과 양식입니다.",
        "icon": "book",
        "csv": "policies.csv",
        "columns": (
            col("문서명", "title", Property.Type.TITLE),
            col("Google Drive 링크", "drive_url", Property.Type.URL),
            col("개정내용", "change_note", Property.Type.TEXT),
            col("개정일", "revised_on", Property.Type.DATE),
            col("문서담당", "owner", Property.Type.RELATION, relation="employees"),
            col("문서상태", "status", Property.Type.STATUS),
            col("버전", "version", Property.Type.TEXT),
            col("분류", "category", Property.Type.SELECT),
            col("승인자", "approver", Property.Type.RELATION, relation="employees"),
            col("열람대상", "audience", Property.Type.TEXT),
            col("적용일", "effective_on", Property.Type.DATE),
        ),
    },
)


def _option_id(name: str, used: set[str]) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    candidate = f"o_{digest}"
    number = 2
    while candidate in used:
        candidate = f"o_{digest}_{number}"
        number += 1
    used.add(candidate)
    return candidate


def _build_options(names: list[str]) -> dict[str, Any]:
    options: list[dict[str, str]] = []
    used: set[str] = set()
    for name in names:
        options.append(
            {
                "id": _option_id(name, used),
                "name": name,
                "color": OPTION_COLORS.get(name, "gray"),
            }
        )
        used.add(name)
    return {"options": options}


def _merge_options(prop: Property, names: list[str]) -> None:
    options = list((prop.config or {}).get("options") or [])
    existing = {str(item.get("name")) for item in options}
    used = existing | {str(item.get("id")) for item in options}
    changed = False
    for name in names:
        if name in existing:
            continue
        options.append(
            {
                "id": _option_id(name, used),
                "name": name,
                "color": OPTION_COLORS.get(name, "gray"),
            }
        )
        existing.add(name)
        changed = True
    if changed:
        prop.config = {"options": options}
        prop.save(update_fields=["config", "updated_at"])


def _option_names(rows: list[dict[str, str]], column: dict[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        value = row.get(column["header"], "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        names.append(value)
    if names:
        return names
    if column["defaults"]:
        return list(column["defaults"])
    return ["미정"]


def _read_csv(filename: str) -> list[dict[str, str]]:
    path = FIXTURE_DIR / filename
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, str]] = []
        for raw in reader:
            row = {str(key): (value or "").strip() for key, value in raw.items() if key}
            if any(row.values()):
                rows.append(row)
        return rows


def _relation_names(raw: str) -> list[str]:
    """Notion CSV 관계 값 `이름 (파일.csv)`에서 이름을 뽑습니다."""
    names: list[str] = []
    rest = raw.strip()
    while rest:
        marker = rest.find(" (")
        if marker == -1 or ".csv)" not in rest[marker:]:
            if names:
                break
            return [part.strip() for part in raw.split(",") if part.strip()]
        name = rest[:marker].strip().strip(",")
        if name:
            names.append(name)
        end = rest.find(".csv)", marker)
        rest = rest[end + len(".csv)") :].strip().lstrip(",").strip()
    return names


def _clock(ampm: str, hour: int) -> int:
    if ampm == "오전":
        return 0 if hour == 12 else hour
    if ampm == "오후":
        return hour if hour == 12 else hour + 12
    return hour


def _korean_point(text: str) -> str:
    cleaned = text.replace("(GMT+9)", "").strip()
    match = KOREAN_DATE.search(cleaned)
    if match is None:
        raise ValueError(f"날짜 형식이 올바르지 않습니다: {text}")
    year, month, day, ampm, hour, minute = match.groups()
    date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    if hour is None:
        return date
    clock = _clock(ampm, int(hour))
    return f"{date}T{clock:02d}:{int(minute):02d}:00"


def _korean_date(text: str) -> str | dict[str, str]:
    cleaned = text.replace("(GMT+9)", "").strip()
    if "→" in cleaned:
        start, end = [part.strip() for part in cleaned.split("→", 1)]
        return {"start": _korean_point(start), "end": _korean_point(end)}
    return _korean_point(cleaned)


def _number(text: str) -> str:
    cleaned = text.replace("₩", "").replace(",", "").replace("원", "").strip()
    try:
        Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"숫자 형식이 올바르지 않습니다: {text}") from exc
    return cleaned


def _checkbox(text: str) -> bool:
    token = text.strip().lower()
    if token in TRUE_TOKENS:
        return True
    if token in FALSE_TOKENS:
        return False
    raise ValueError(f"체크박스 값이 올바르지 않습니다: {text}")


def _cell_value(column: dict[str, Any], raw: str) -> Any:
    prop_type = column["type"]
    if prop_type == Property.Type.NUMBER:
        return _number(raw)
    if prop_type == Property.Type.DATE:
        return _korean_date(raw)
    if prop_type == Property.Type.CHECKBOX:
        return _checkbox(raw)
    if prop_type == Property.Type.URL and not raw.startswith(("http://", "https://")):
        raise ValueError(f"URL은 http:// 또는 https://로 시작해야 합니다: {raw}")
    return raw


def _row_title(row: dict[str, str], spec: dict[str, Any], header: str) -> str:
    title = row.get(header, "").strip()
    if not title:
        parts: list[str] = []
        for key in spec.get("title_from", ()):
            value = row.get(key, "").strip()
            if not value:
                continue
            if "(" in value and ".csv" in value:
                names = _relation_names(value)
                value = names[0] if names else value
            parts.append(value)
        title = " ".join(parts)
        suffix = str(spec.get("title_suffix") or "")
        if suffix and suffix not in title:
            title = f"{title} {suffix}".strip()
    return title[:300]


def _suffixed(title: str, count: int) -> str:
    suffix = f" ({count})"
    return f"{title[: 300 - len(suffix)]}{suffix}"


def _apply(record: Record, values: dict[str, Any], label: str) -> None:
    try:
        apply_values(record, values)
    except HttpError as exc:
        message = getattr(exc, "message", None) or str(exc)
        raise ValueError(f"{label}: {message}") from exc


def _ensure_database(workspace: Workspace, spec: dict[str, Any], position: int) -> Database:
    database = workspace.databases.filter(slug=spec["slug"]).first()
    if database is None:
        database = Database.objects.create(
            workspace=workspace,
            name=spec["name"],
            slug=spec["slug"],
            description=spec["description"],
            icon=spec["icon"],
            section=spec["page_name"],
            section_slug=spec["page_slug"],
            position=position,
        )
    elif not database.section:
        database.section = spec["page_name"]
        database.section_slug = spec["page_slug"]
        database.save(update_fields=["section", "section_slug", "updated_at"])
    if not database.views.filter(name="전체").exists():
        View.objects.create(
            database=database,
            name="전체",
            type=View.Type.TABLE,
            filters=[],
            sorts=[],
            position=0,
        )
    return database


def _ensure_properties(
    database: Database,
    spec: dict[str, Any],
    databases: dict[str, Database],
    rows: list[dict[str, str]],
) -> None:
    for position, column in enumerate(spec["columns"]):
        prop = database.properties.filter(slug=column["slug"]).first()
        if column["type"] == Property.Type.TITLE:
            prop = database.properties.filter(type=Property.Type.TITLE).first()
        config: dict[str, Any] = {}
        if column["type"] in {Property.Type.SELECT, Property.Type.STATUS}:
            config = _build_options(_option_names(rows, column))
        elif column["type"] == Property.Type.RELATION:
            config = {"database_id": databases[column["relation"]].id}
        if prop is None:
            Property.objects.create(
                database=database,
                name=column["header"],
                slug=column["slug"],
                type=column["type"],
                config=config,
                position=position,
            )
            continue
        if column["type"] in {Property.Type.SELECT, Property.Type.STATUS}:
            _merge_options(prop, _option_names(rows, column))
        if column["type"] == Property.Type.RELATION and not (prop.config or {}).get("database_id"):
            prop.config = config
            prop.save(update_fields=["config", "updated_at"])


def _import_rows(
    database: Database,
    spec: dict[str, Any],
    actor,
    rows: list[dict[str, str]],
) -> tuple[int, list[tuple[Record, str, list[str]]]]:
    title_header = next(
        column["header"] for column in spec["columns"] if column["type"] == Property.Type.TITLE
    )
    seen: dict[str, int] = {}
    created = 0
    jobs: list[tuple[Record, str, list[str]]] = []
    for row in rows:
        base = _row_title(row, spec, title_header)
        if not base:
            continue
        seen[base] = seen.get(base, 0) + 1
        title = base if seen[base] == 1 else _suffixed(base, seen[base])
        if database.records.filter(title=title).exists():
            continue
        values: dict[str, Any] = {}
        relations: list[tuple[str, list[str]]] = []
        for column in spec["columns"]:
            if column["type"] == Property.Type.TITLE:
                values[column["slug"]] = title
                continue
            raw = row.get(column["header"], "").strip()
            if not raw:
                continue
            if column["type"] == Property.Type.RELATION:
                relations.append((column["slug"], _relation_names(raw)))
                continue
            try:
                values[column["slug"]] = _cell_value(column, raw)
            except ValueError as exc:
                raise ValueError(f"{database.slug}/{title}: {exc}") from exc
        record = Record.objects.create(
            database=database,
            title=title,
            created_by=actor,
            last_edited_by=actor,
        )
        _apply(record, values, f"{database.slug}/{title}")
        record.save(update_fields=["title", "updated_at"])
        created += 1
        for slug, names in relations:
            jobs.append((record, slug, names))
    return created, jobs


def _link_relations(
    jobs: list[tuple[Record, str, list[str]]],
    warnings: list[str],
) -> None:
    for record, slug, names in jobs:
        prop = record.database.properties.get(slug=slug)
        target_id = (prop.config or {}).get("database_id")
        ids: list[int] = []
        for name in names:
            target = Record.objects.filter(database_id=target_id, title=name).first()
            if target is None:
                warnings.append(f"{record.database.slug}/{record.title}: '{name}' 연결 대상을 찾지 못했습니다.")
                continue
            if target.id not in ids:
                ids.append(target.id)
        if not ids:
            continue
        _apply(record, {slug: ids}, f"{record.database.slug}/{record.title}/{slug}")


@transaction.atomic
def seed_koc_pages() -> dict[str, Any]:
    """KOC 페이지 묶음, 데이터베이스, CSV 레코드를 없으면 만듭니다."""
    workspace = ensure_koc_workspace()
    owner = (
        workspace.members.filter(role=WorkspaceMember.Role.OWNER).select_related("user").first()
    )
    actor = owner.user if owner else None
    loaded = {spec["slug"]: _read_csv(spec["csv"]) for spec in PAGES}
    databases: dict[str, Database] = {}
    for position, spec in enumerate(PAGES):
        databases[spec["slug"]] = _ensure_database(workspace, spec, position)
    for spec in PAGES:
        _ensure_properties(databases[spec["slug"]], spec, databases, loaded[spec["slug"]])
    created = 0
    jobs: list[tuple[Record, str, list[str]]] = []
    warnings: list[str] = []
    for spec in PAGES:
        made, pending = _import_rows(databases[spec["slug"]], spec, actor, loaded[spec["slug"]])
        created += made
        jobs.extend(pending)
    _link_relations(jobs, warnings)
    return {
        "workspace": workspace,
        "database_count": len(PAGES),
        "record_count": Record.objects.filter(
            database__workspace=workspace,
            database__slug__in=list(databases),
        ).count(),
        "created_count": created,
        "warnings": warnings,
    }
