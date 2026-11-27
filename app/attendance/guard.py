"""근무 기록의 시각 수정과 야근 신청을 제한합니다.

출근·퇴근 시각은 출퇴근 처리만 넣습니다. 관리자는 표에서 시각을 고칠 수 있습니다.
야근 시간은 본인 행에 신청하면 대기가 되고, 관리자가 승인하기 전에는 수정이 잠깁니다.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone
from ninja.errors import HttpError

from workspace.models import Property, PropertyValue, Record, RecordActivity, WorkspaceMember

_CLOCK_SLUGS = ("check_in", "check_out", "registered_at")
_OVERTIME_SLUGS = ("overtime_minutes", "overtime_reason", "overtime_status")
_MAX_MINUTES = 12 * 60
_STATUS_OPTIONS = (
    {"id": "waiting", "name": "대기", "color": "gray"},
    {"id": "approved", "name": "승인", "color": "green"},
    {"id": "rejected", "name": "반려", "color": "red"},
)


def ensure_overtime_properties(database) -> None:
    """야근 시간·사유·승인 속성이 없으면 추가합니다."""
    specs = (
        ("overtime_minutes", "야근시간(분)", Property.Type.NUMBER, {}),
        ("overtime_reason", "야근사유", Property.Type.TEXT, {}),
        ("overtime_status", "야근승인", Property.Type.STATUS, {"options": list(_STATUS_OPTIONS)}),
    )
    position = database.properties.order_by("-position").values_list("position", flat=True).first() or 0
    for slug, name, prop_type, config in specs:
        prop = database.properties.filter(slug=slug).first()
        if prop is None:
            position += 1
            Property.objects.create(
                database=database,
                name=name,
                slug=slug,
                type=prop_type,
                config=config,
                position=position,
            )
            continue
        if slug != "overtime_status":
            continue
        options = list((prop.config or {}).get("options") or [])
        names = {str(item.get("name")) for item in options if isinstance(item, dict)}
        changed = False
        for option in _STATUS_OPTIONS:
            if option["name"] in names:
                continue
            options.append(dict(option))
            changed = True
        if changed:
            prop.config = {**(prop.config or {}), "options": options}
            prop.save(update_fields=["config", "updated_at"])


def guard_attendance_write(
    user,
    database,
    values: dict[str, Any],
    record: Record | None = None,
    *,
    clock: bool = False,
    source: str = "",
) -> None:
    """멤버가 시각을 바꾸거나 야근을 승인된 것처럼 저장하지 못하게 합니다."""
    if clock or database.slug != "attendance" or not values:
        return
    may_correct = _is_manager(user, database.workspace_id) and source == RecordActivity.Source.USER
    _reject_clock_changes(record, values, may_correct)
    _reject_identity_changes(user, database.workspace_id, record, values, may_correct)
    if not any(slug in values for slug in _OVERTIME_SLUGS):
        return
    ensure_overtime_properties(database)
    _apply_overtime(user, database.workspace_id, record, values, may_correct)


def reject_member_attendance_delete(user, record: Record) -> None:
    if record.database.slug != "attendance":
        return
    if _is_manager(user, record.database.workspace_id):
        return
    raise HttpError(403, "근무 기록은 직접 삭제할 수 없습니다.")


def _is_manager(user, workspace_id: int) -> bool:
    role = (
        WorkspaceMember.objects.filter(user=user, workspace_id=workspace_id)
        .values_list("role", flat=True)
        .first()
    )
    return role in {WorkspaceMember.Role.OWNER, WorkspaceMember.Role.ADMIN}


def _reject_clock_changes(record: Record | None, values: dict[str, Any], may_correct: bool) -> None:
    if may_correct:
        return
    for slug in _CLOCK_SLUGS:
        if slug in values and _clock_changed(record, slug, values[slug]):
            raise HttpError(403, "출근·퇴근 시각은 직접 수정할 수 없습니다.")


def _reject_identity_changes(
    user,
    workspace_id: int,
    record: Record | None,
    values: dict[str, Any],
    may_correct: bool,
) -> None:
    if may_correct:
        return
    if "work_date" in values and _date_changed(record, "work_date", values["work_date"]):
        stored = _stored_date(record, "work_date")
        incoming = _norm_date(values["work_date"])
        if stored:
            raise HttpError(403, "근무일과 임직원은 직접 수정할 수 없습니다.")
        if incoming != _today():
            raise HttpError(403, "근무일과 임직원은 본인 오늘 기록만 만들 수 있습니다.")
    if "employee" not in values or not _employee_changed(record, values["employee"]):
        return
    if _stored_employee_ids(record):
        raise HttpError(403, "근무일과 임직원은 직접 수정할 수 없습니다.")
    incoming = _employee_ids(values["employee"])
    self_id = _self_employee_id(user, workspace_id)
    if incoming != [self_id]:
        raise HttpError(403, "근무일과 임직원은 본인 오늘 기록만 만들 수 있습니다.")


def _apply_overtime(
    user,
    workspace_id: int,
    record: Record | None,
    values: dict[str, Any],
    may_correct: bool,
) -> None:
    current = _stored_text(record, "overtime_status")
    minutes_changed = "overtime_minutes" in values and not _same_minutes(record, values["overtime_minutes"])
    reason_changed = "overtime_reason" in values and not _same_text(record, "overtime_reason", values["overtime_reason"])
    wanted = _status_name(values.get("overtime_status")) if "overtime_status" in values else current
    status_changed = "overtime_status" in values and wanted != current
    if not minutes_changed and not reason_changed and not status_changed:
        return
    if current == "승인" and not may_correct:
        raise HttpError(403, "승인된 야근 시간은 수정할 수 없습니다.")
    if not may_correct:
        _require_own_row(user, workspace_id, record, values)
    if "overtime_reason" in values:
        reason = str(values.get("overtime_reason") or "").strip()
        if len(reason) > 500:
            raise HttpError(400, "야근 사유는 500자 이하입니다.")
        values["overtime_reason"] = reason
    parsed = _stored_minutes(record)
    if "overtime_minutes" in values:
        parsed = _parse_minutes(values["overtime_minutes"])
        values["overtime_minutes"] = parsed
    explicit_clear = "overtime_minutes" in values and parsed is None
    if not may_correct:
        if explicit_clear:
            values["overtime_minutes"] = None
            values["overtime_reason"] = None
            values["overtime_status"] = None
            return
        if wanted not in {"", "대기"}:
            raise HttpError(403, "야근 승인 상태는 관리자만 바꿀 수 있습니다.")
        if parsed is None:
            raise HttpError(400, "야근 시간은 1분 이상 720분 이하입니다.")
        values["overtime_status"] = "대기"
        if minutes_changed and record is not None:
            _notify_managers(user, workspace_id, record, parsed)
        return
    if wanted in {"대기", "승인", "반려"}:
        values["overtime_status"] = wanted
    elif minutes_changed and parsed is not None and not current:
        values["overtime_status"] = "대기"


def _require_own_row(user, workspace_id: int, record: Record | None, values: dict[str, Any]) -> None:
    self_id = _self_employee_id(user, workspace_id)
    if "employee" in values:
        target = _employee_ids(values["employee"])
    else:
        target = _stored_employee_ids(record)
    if self_id not in target:
        raise HttpError(403, "본인 근무 기록에만 야근을 신청할 수 있습니다.")


def _self_employee_id(user, workspace_id: int) -> int:
    from workspace.models import Database

    employees = Database.objects.filter(workspace_id=workspace_id, slug="employees").first()
    if employees is None:
        raise HttpError(400, "임직원 기록이 없습니다.")
    email = str(getattr(user, "email", "") or "").strip()
    if email:
        ids = list(
            PropertyValue.objects.filter(
                property__database=employees,
                property__slug="email",
                text_value__iexact=email,
            ).values_list("record_id", flat=True)
        )
        if len(ids) > 1:
            raise HttpError(400, "임직원 기록이 여러 건입니다.")
        if len(ids) == 1:
            return int(ids[0])
    name = str(getattr(user, "name", "") or "").strip()
    if name:
        from workspace.models import Record as EmployeeRecord

        ids = list(
            EmployeeRecord.objects.filter(database=employees, title=name).values_list("id", flat=True)[:2]
        )
        if len(ids) > 1:
            raise HttpError(400, "임직원 기록이 여러 건입니다.")
        if len(ids) == 1:
            return int(ids[0])
    raise HttpError(400, "임직원 기록이 없습니다.")


def _notify_managers(user, workspace_id: int, record: Record, minutes: int) -> None:
    try:
        from notification.utils import make_notification_sync
    except Exception:
        return
    name = str(getattr(user, "name", "") or "").strip() or str(getattr(user, "email", "") or "멤버")
    message = f"{name}님이 야근 {minutes}분을 신청했습니다."
    metadata = {
        "kind": "overtime",
        "workspace_id": workspace_id,
        "record_id": record.id,
        "database_slug": "attendance",
    }
    managers = WorkspaceMember.objects.filter(
        workspace_id=workspace_id,
        role__in=[WorkspaceMember.Role.OWNER, WorkspaceMember.Role.ADMIN],
    ).select_related("user")
    for membership in managers:
        if membership.user_id == user.id:
            continue
        try:
            make_notification_sync(membership.user, message, metadata)
        except Exception:
            continue


def _status_name(raw: Any) -> str:
    text = str(raw or "").strip()
    return {
        "waiting": "대기",
        "approved": "승인",
        "rejected": "반려",
        "대기": "대기",
        "승인": "승인",
        "반려": "반려",
    }.get(text, text)


def _parse_minutes(raw: Any) -> int | None:
    if raw is None or raw == "" or raw == []:
        return None
    if isinstance(raw, bool):
        raise HttpError(400, "야근 시간은 1분 이상 720분 이하입니다.")
    try:
        number = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise HttpError(400, "야근 시간은 1분 이상 720분 이하입니다.") from None
    if number != number.to_integral_value():
        raise HttpError(400, "야근 시간은 1분 이상 720분 이하입니다.")
    minutes = int(number)
    if minutes == 0:
        return None
    if minutes < 1 or minutes > _MAX_MINUTES:
        raise HttpError(400, "야근 시간은 1분 이상 720분 이하입니다.")
    return minutes


def _clock_changed(record: Record | None, slug: str, raw: Any) -> bool:
    return _stored_clock(record, slug) != _norm_clock(raw)


def _date_changed(record: Record | None, slug: str, raw: Any) -> bool:
    return _stored_date(record, slug) != _norm_date(raw)


def _employee_changed(record: Record | None, raw: Any) -> bool:
    return _stored_employee_ids(record) != _employee_ids(raw)


def _same_minutes(record: Record | None, raw: Any) -> bool:
    try:
        parsed = _parse_minutes(raw)
    except HttpError:
        return False
    return _stored_minutes(record) == parsed


def _same_text(record: Record | None, slug: str, raw: Any) -> bool:
    return _stored_text(record, slug) == str(raw or "").strip()


def _stored_clock(record: Record | None, slug: str) -> str | None:
    start = _stored_column(record, slug, "date_start")
    if start is None:
        return None
    text = start.isoformat() if hasattr(start, "isoformat") else start
    return _norm_clock(text)


def _stored_date(record: Record | None, slug: str) -> str | None:
    return _norm_date(_stored_clock(record, slug))


def _stored_text(record: Record | None, slug: str) -> str:
    text = _stored_column(record, slug, "text_value")
    return str(text or "").strip()


def _stored_minutes(record: Record | None) -> int | None:
    raw = _stored_column(record, "overtime_minutes", "number_value")
    if raw is None:
        return None
    return _parse_minutes(raw)


def _stored_employee_ids(record: Record | None) -> list[int]:
    raw = _stored_column(record, "employee", "json_value")
    return _employee_ids(raw)


def _stored_column(record: Record | None, slug: str, column: str) -> Any:
    if record is None or record.pk is None:
        return None
    return (
        PropertyValue.objects.filter(record=record, property__slug=slug)
        .values_list(column, flat=True)
        .first()
    )


def _employee_ids(raw: Any) -> list[int]:
    if raw in (None, "", []):
        return []
    if not isinstance(raw, list):
        raise HttpError(400, "관계 값은 레코드 id여야 합니다.")
    ids: list[int] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int):
            raise HttpError(400, "관계 값은 레코드 id여야 합니다.")
        if item not in ids:
            ids.append(item)
    return ids


def _norm_clock(raw: Any) -> str | None:
    if isinstance(raw, dict):
        raw = raw.get("start")
    if raw is None:
        return None
    text = str(raw).strip().replace(" ", "T")
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1]
    plus = text.find("+")
    if plus > 0:
        text = text[:plus]
    dot = text.find(".")
    if dot > 0:
        text = text[:dot]
    return text


def _norm_date(raw: Any) -> str | None:
    text = _norm_clock(raw)
    if text is None:
        return None
    return text[:10]


def _today() -> str:
    current = timezone.now()
    if timezone.is_aware(current):
        current = timezone.make_naive(current)
    return current.date().isoformat()
