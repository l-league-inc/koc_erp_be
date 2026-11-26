from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from assistant.agent import find_self_employee
from workspace.models import RecordActivity
from workspace.utils import (
    accessible_databases,
    create_record,
    get_membership,
    query_records,
    update_record,
)

_REQUIRED_SLUGS = frozenset({"employee", "work_date", "check_in", "check_out"})


def today_status(user, workspace_id: int) -> dict[str, Any]:
    _attendance(user, workspace_id)
    employee = _employee(user, workspace_id)
    moment = _moment()
    row = _today_row(user, workspace_id, int(employee["id"]), moment.date().isoformat())
    return _status(employee, row, moment.date().isoformat())


def clock_in(user, workspace_id: int) -> dict[str, Any]:
    database, slugs = _attendance(user, workspace_id)
    employee = _employee(user, workspace_id)
    moment = _moment()
    today = moment.date().isoformat()
    stamp = moment.isoformat()
    with transaction.atomic():
        row = _today_row(user, workspace_id, int(employee["id"]), today)
        if row is None:
            values: dict[str, Any] = {
                "employee": [employee["id"]],
                "work_date": today,
                "check_in": stamp,
            }
            if "registered_at" in slugs:
                values["registered_at"] = stamp
            saved = create_record(
                user,
                database.id,
                {"title": f"{today} 출근", "values": values},
                RecordActivity.Source.USER,
            )
            return _status(employee, saved, today)
        if _clock_text((row.get("values") or {}).get("check_in")):
            raise HttpError(409, "오늘 출근은 이미 있습니다.")
        saved = update_record(
            user,
            int(row["id"]),
            {"values": {"check_in": stamp}},
            RecordActivity.Source.USER,
        )
    return _status(employee, saved, today)


def clock_out(user, workspace_id: int) -> dict[str, Any]:
    _database, _slugs = _attendance(user, workspace_id)
    employee = _employee(user, workspace_id)
    moment = _moment()
    today = moment.date().isoformat()
    stamp = moment.isoformat()
    with transaction.atomic():
        row = _today_row(user, workspace_id, int(employee["id"]), today)
        values = (row or {}).get("values") or {}
        if row is None or not _clock_text(values.get("check_in")):
            raise HttpError(400, "출근 기록이 없습니다.")
        if _clock_text(values.get("check_out")):
            raise HttpError(409, "오늘 퇴근은 이미 있습니다.")
        saved = update_record(
            user,
            int(row["id"]),
            {"values": {"check_out": stamp}},
            RecordActivity.Source.USER,
        )
    return _status(employee, saved, today)


def _attendance(user, workspace_id: int):
    get_membership(user, workspace_id)
    database = (
        accessible_databases(user)
        .filter(workspace_id=workspace_id, slug="attendance")
        .first()
    )
    if database is None:
        raise HttpError(400, "근무 기록 데이터베이스가 없습니다.")
    slugs = set(database.properties.values_list("slug", flat=True))
    if not _REQUIRED_SLUGS <= slugs:
        raise HttpError(400, "근무 기록에 필요한 속성이 없습니다.")
    return database, slugs


def _employee(user, workspace_id: int) -> dict[str, Any]:
    found = find_self_employee(user, workspace_id)
    if found.get("found"):
        return {"id": int(found["id"]), "title": str(found["title"])}
    if found.get("matches"):
        raise HttpError(400, "임직원 기록이 여러 건입니다.")
    raise HttpError(400, "임직원 기록이 없습니다.")


def _today_row(user, workspace_id: int, employee_id: int, today: str) -> dict[str, Any] | None:
    result = query_records(
        user,
        {
            "workspace_id": workspace_id,
            "database_slug": "attendance",
            "filters": [
                {"property": "employee", "op": "eq", "value": employee_id},
                {"property": "work_date", "op": "eq", "value": today},
            ],
            "page": 1,
            "page_size": 1,
        },
    )
    rows = list(result.get("data") or [])
    if not rows:
        return None
    return rows[0]


def _moment() -> datetime:
    current = timezone.now()
    if timezone.is_aware(current):
        current = timezone.make_naive(current)
    return current.replace(microsecond=0)


def _clock_text(raw: Any) -> str | None:
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


def _date_text(raw: Any) -> str | None:
    text = _clock_text(raw)
    if text is None:
        return None
    return text[:10]


def _status(employee: dict[str, Any], record: dict[str, Any] | None, today: str) -> dict[str, Any]:
    values = record.get("values") if record else {}
    if not isinstance(values, dict):
        values = {}
    check_in = _clock_text(values.get("check_in"))
    check_out = _clock_text(values.get("check_out"))
    if check_out:
        state = "out"
    elif check_in:
        state = "in"
    else:
        state = "none"
    return {
        "state": state,
        "record_id": None if record is None else int(record["id"]),
        "title": "" if record is None else str(record.get("title") or ""),
        "work_date": _date_text(values.get("work_date")) or today,
        "check_in": check_in,
        "check_out": check_out,
        "employee_id": int(employee["id"]),
        "employee_title": str(employee["title"]),
    }
