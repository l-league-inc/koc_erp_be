import logging
from typing import Any

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from ninja.errors import HttpError

from assistant import llm
from assistant.models import Workbot, WorkbotRun
from assistant.schedule import next_run_at, parse_cron
from notification.models import Notification
from workspace.models import RecordActivity, WorkspaceMember
from workspace.utils import (
    accessible_databases,
    create_record,
    get_membership,
    query_records,
)

logger = logging.getLogger("django")
_ACTIONS = {"notify", "create_record"}


def validate_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise HttpError(400, "spec은 객체여야 합니다.")
    action = spec.get("action")
    if action not in _ACTIONS:
        raise HttpError(400, "동작은 notify 또는 create_record입니다.")
    filters = spec.get("filters") or []
    if not isinstance(filters, list):
        raise HttpError(400, "필터는 배열이어야 합니다.")
    notify_user_ids = spec.get("notify_user_ids") or []
    if not isinstance(notify_user_ids, list) or any(not isinstance(item, int) for item in notify_user_ids):
        raise HttpError(400, "알림 대상은 사용자 id 배열이어야 합니다.")
    message = str(spec.get("message") or "").strip()
    if action == "notify" and not message:
        raise HttpError(400, "알림 문구가 필요합니다.")
    record = spec.get("record")
    if action == "create_record":
        if not isinstance(record, dict) or not str(record.get("title") or "").strip():
            raise HttpError(400, "만들 레코드의 제목이 필요합니다.")
    else:
        record = None
    return {
        "filters": filters,
        "action": action,
        "notify_user_ids": notify_user_ids,
        "message": message,
        "requires_confirmation": bool(spec.get("requires_confirmation")),
        "record": record,
    }


def _minutes(value: Any) -> int:
    try:
        minutes = int(value or 0)
    except (TypeError, ValueError):
        raise HttpError(400, "예상 시간은 0 이상이어야 합니다.") from None
    if minutes < 0:
        raise HttpError(400, "예상 시간은 0 이상이어야 합니다.")
    return minutes


def _database(user, workspace_id: int, slug: str):
    database = (
        accessible_databases(user).filter(workspace_id=workspace_id, slug=slug).first()
    )
    if database is None:
        raise HttpError(404, "데이터베이스를 찾을 수 없습니다.")
    return database


def _workspace_ids(user):
    return WorkspaceMember.objects.filter(user=user).values("workspace_id")


def _get_bot(user, workbot_id: int) -> Workbot:
    bot = (
        Workbot.objects.select_related("workspace")
        .filter(id=workbot_id, workspace_id__in=_workspace_ids(user))
        .first()
    )
    if bot is None:
        if Workbot.objects.filter(id=workbot_id).exists():
            raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
        raise HttpError(404, "워크봇을 찾을 수 없습니다.")
    return bot


def serialize_workbot(bot: Workbot) -> dict[str, Any]:
    return {
        "id": bot.id,
        "workspace_id": bot.workspace_id,
        "owner_id": bot.owner_id,
        "name": bot.name,
        "description": bot.description,
        "instruction": bot.instruction,
        "spec": bot.spec or {},
        "schedule": bot.schedule,
        "enabled": bot.enabled,
        "database_slug": bot.database_slug,
        "estimated_minutes": bot.estimated_minutes,
        "next_run_at": bot.next_run_at,
        "last_run_at": bot.last_run_at,
        "created_at": bot.created_at,
        "updated_at": bot.updated_at,
    }


def serialize_run(run: WorkbotRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "workbot_id": run.workbot_id,
        "status": run.status,
        "summary": run.summary,
        "record_ids": run.record_ids or [],
        "payload": run.payload or {},
        "created_at": run.created_at,
    }


def _schedule_fields(bot: Workbot, now) -> None:
    if bot.enabled:
        bot.next_run_at = next_run_at(bot.schedule, now)
    else:
        bot.next_run_at = None


def create_workbot(user, data: dict[str, Any]) -> dict[str, Any]:
    get_membership(user, data["workspace_id"])
    name = str(data.get("name") or "").strip()
    if not name:
        raise HttpError(400, "이름이 필요합니다.")
    slug = str(data.get("database_slug") or "").strip()
    _database(user, data["workspace_id"], slug)
    schedule = " ".join(str(data.get("schedule") or "").split())
    parse_cron(schedule)
    minutes = _minutes(data.get("estimated_minutes"))
    enabled = bool(data.get("enabled", True))
    bot = Workbot(
        workspace_id=data["workspace_id"],
        owner=user,
        name=name,
        description=str(data.get("description") or ""),
        instruction=str(data.get("instruction") or ""),
        spec=validate_spec(data.get("spec")),
        schedule=schedule,
        enabled=enabled,
        database_slug=slug,
        estimated_minutes=minutes,
    )
    _schedule_fields(bot, timezone.now())
    bot.save()
    return serialize_workbot(bot)


def list_workbots(user) -> list[dict[str, Any]]:
    bots = Workbot.objects.filter(workspace_id__in=_workspace_ids(user)).order_by("-id")
    return [serialize_workbot(bot) for bot in bots]


def update_workbot(user, workbot_id: int, data: dict[str, Any]) -> dict[str, Any]:
    bot = _get_bot(user, workbot_id)
    schedule_changed = False
    if data.get("name") is not None:
        name = str(data["name"]).strip()
        if not name:
            raise HttpError(400, "이름은 비울 수 없습니다.")
        bot.name = name
    if data.get("description") is not None:
        bot.description = str(data["description"])
    if data.get("instruction") is not None:
        bot.instruction = str(data["instruction"])
    if data.get("spec") is not None:
        bot.spec = validate_spec(data["spec"])
    if data.get("schedule") is not None:
        bot.schedule = " ".join(str(data["schedule"]).split())
        parse_cron(bot.schedule)
        schedule_changed = True
    if data.get("enabled") is not None:
        bot.enabled = bool(data["enabled"])
        schedule_changed = True
    if data.get("database_slug") is not None:
        slug = str(data["database_slug"]).strip()
        _database(user, bot.workspace_id, slug)
        bot.database_slug = slug
    if data.get("estimated_minutes") is not None:
        bot.estimated_minutes = _minutes(data["estimated_minutes"])
    if schedule_changed:
        _schedule_fields(bot, timezone.now())
    bot.save()
    return serialize_workbot(bot)


def delete_workbot(user, workbot_id: int) -> None:
    bot = _get_bot(user, workbot_id)
    bot.delete()


def draft_workbot(user, workspace_id: int, instruction: str) -> dict[str, Any]:
    text = (instruction or "").strip()
    if not text:
        raise HttpError(400, "지시가 필요합니다.")
    get_membership(user, workspace_id)
    databases = accessible_databases(user).filter(workspace_id=workspace_id)
    catalog = ", ".join(databases.values_list("slug", flat=True))
    parsed = llm.complete_json(
        [
            {
                "role": "system",
                "content": (
                    "워크봇 초안을 JSON으로만 답합니다. 키는 name, description, database_slug, "
                    "schedule, estimated_minutes, spec입니다. schedule은 분 시 일 월 요일 크론입니다. "
                    "spec.action은 notify 또는 create_record입니다. "
                    "spec.filters는 워크스페이스 조회 필터 배열입니다. "
                    "spec.notify_user_ids는 정수 배열이고 spec.message는 알림 문구입니다. "
                    "spec.requires_confirmation은 boolean입니다. "
                    "create_record이면 spec.record.title이 필요합니다. "
                    f"사용할 수 있는 database_slug는 {catalog}입니다."
                ),
            },
            {"role": "user", "content": text},
        ]
    )
    normalized = _normalize_draft(user, workspace_id, parsed)
    normalized["instruction"] = text
    return normalized


def _normalize_draft(user, workspace_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    slug = str(payload.get("database_slug") or "").strip()
    _database(user, workspace_id, slug)
    schedule = " ".join(str(payload.get("schedule") or "").split())
    parse_cron(schedule)
    minutes = _minutes(payload.get("estimated_minutes"))
    name = str(payload.get("name") or "").strip() or "워크봇"
    return {
        "name": name,
        "description": str(payload.get("description") or "").strip(),
        "database_slug": slug,
        "schedule": schedule,
        "estimated_minutes": minutes,
        "spec": validate_spec(payload.get("spec") or {}),
    }


def _member_ids(workspace_id: int, user_ids: list[int]) -> None:
    found = set(
        WorkspaceMember.objects.filter(
            workspace_id=workspace_id,
            user_id__in=user_ids,
        ).values_list("user_id", flat=True)
    )
    if set(user_ids) - found:
        raise HttpError(400, "알림 대상이 워크스페이스 멤버가 아닙니다.")


def _notify(bot: Workbot, run: WorkbotRun, user_ids: list[int], message: str) -> None:
    text = message[:200]
    for user_id in user_ids:
        Notification.objects.create(
            user_id=user_id,
            message=text,
            metadata={"workbot_id": bot.id, "run_id": run.id},
        )


def _interpret(bot: Workbot, actor) -> dict[str, Any]:
    spec = validate_spec(bot.spec)
    database = _database(actor, bot.workspace_id, bot.database_slug)
    if spec["action"] == "notify":
        result = query_records(
            actor,
            {
                "database_id": database.id,
                "filters": spec["filters"],
                "page": 1,
                "page_size": 20,
            },
        )
        record_ids = [row["id"] for row in result["data"]]
        if result["count"] == 0:
            return {
                "status": WorkbotRun.Status.SUCCESS,
                "summary": "해당하는 레코드가 없습니다.",
                "record_ids": [],
                "payload": {},
                "notify_user_ids": [],
                "message": "",
            }
        user_ids = spec["notify_user_ids"] or [bot.owner_id]
        _member_ids(bot.workspace_id, user_ids)
        message = f"{spec['message']} ({result['count']}건)"
        payload = {
            "action": "notify",
            "notify_user_ids": user_ids,
            "message": message,
            "record_ids": record_ids,
        }
        if spec["requires_confirmation"]:
            return {
                "status": WorkbotRun.Status.WAITING,
                "summary": message,
                "record_ids": record_ids,
                "payload": payload,
                "notify_user_ids": [],
                "message": "",
            }
        return {
            "status": WorkbotRun.Status.SUCCESS,
            "summary": message,
            "record_ids": record_ids,
            "payload": payload,
            "notify_user_ids": user_ids,
            "message": message,
        }

    payload = {
        "action": "create_record",
        "database_id": database.id,
        "record": spec["record"],
    }
    if spec["requires_confirmation"]:
        title = spec["record"]["title"]
        return {
            "status": WorkbotRun.Status.WAITING,
            "summary": f"{title} 생성을 확인해 주세요.",
            "record_ids": [],
            "payload": payload,
            "notify_user_ids": [],
            "message": "",
        }
    saved = create_record(
        actor,
        database.id,
        {"title": spec["record"]["title"], "values": spec["record"].get("values") or {}},
        RecordActivity.Source.USER,
    )
    return {
        "status": WorkbotRun.Status.SUCCESS,
        "summary": f"{saved['title']}을 만들었습니다.",
        "record_ids": [saved["id"]],
        "payload": payload,
        "notify_user_ids": [],
        "message": "",
    }


@transaction.atomic
def run_workbot(bot: Workbot, actor) -> WorkbotRun:
    now = timezone.now()
    try:
        outcome = _interpret(bot, actor)
        run = WorkbotRun.objects.create(
            workbot=bot,
            status=outcome["status"],
            summary=outcome["summary"][:1000],
            record_ids=outcome["record_ids"],
            payload=outcome["payload"],
        )
        if outcome["notify_user_ids"]:
            _notify(bot, run, outcome["notify_user_ids"], outcome["message"])
    except HttpError as exc:
        run = WorkbotRun.objects.create(
            workbot=bot,
            status=WorkbotRun.Status.FAILED,
            summary=exc.message,
        )
    except Exception:
        logger.exception("workbot id=%s", bot.id)
        run = WorkbotRun.objects.create(
            workbot=bot,
            status=WorkbotRun.Status.FAILED,
            summary="실행에 실패했습니다.",
        )
    bot.last_run_at = now
    if bot.enabled:
        bot.next_run_at = next_run_at(bot.schedule, now)
    bot.save(update_fields=["last_run_at", "next_run_at", "updated_at"])
    return run


def run_workbot_by_id(user, workbot_id: int) -> dict[str, Any]:
    bot = _get_bot(user, workbot_id)
    return serialize_run(run_workbot(bot, user))


def run_due_workbots() -> int:
    now = timezone.now()
    bots = list(
        Workbot.objects.select_related("owner").filter(
            enabled=True,
            next_run_at__isnull=False,
            next_run_at__lte=now,
        )
    )
    for bot in bots:
        run_workbot(bot, bot.owner)
    return len(bots)


@transaction.atomic
def confirm_run(user, run_id: int) -> dict[str, Any]:
    run = (
        WorkbotRun.objects.select_related("workbot")
        .filter(id=run_id, workbot__workspace_id__in=_workspace_ids(user))
        .first()
    )
    if run is None:
        if WorkbotRun.objects.filter(id=run_id).exists():
            raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
        raise HttpError(404, "실행을 찾을 수 없습니다.")
    if run.status != WorkbotRun.Status.WAITING:
        raise HttpError(400, "확인 대기 중인 실행만 확정할 수 있습니다.")
    payload = run.payload or {}
    bot = run.workbot
    if payload.get("action") == "notify":
        user_ids = payload.get("notify_user_ids") or []
        _member_ids(bot.workspace_id, user_ids)
        _notify(bot, run, user_ids, str(payload.get("message") or run.summary))
        run.record_ids = payload.get("record_ids") or []
        run.summary = str(payload.get("message") or run.summary)
    elif payload.get("action") == "create_record":
        record = payload.get("record") or {}
        saved = create_record(
            user,
            int(payload["database_id"]),
            {"title": record.get("title"), "values": record.get("values") or {}},
            RecordActivity.Source.USER,
        )
        run.record_ids = [saved["id"]]
        run.summary = f"{saved['title']}을 만들었습니다."
    else:
        raise HttpError(400, "확정할 내용이 없습니다.")
    run.status = WorkbotRun.Status.SUCCESS
    run.save(update_fields=["status", "summary", "record_ids", "updated_at"])
    return serialize_run(run)


def list_runs(user, workbot_id: int | None) -> list[dict[str, Any]]:
    runs = WorkbotRun.objects.filter(workbot__workspace_id__in=_workspace_ids(user))
    if workbot_id is not None:
        runs = runs.filter(workbot_id=workbot_id)
    return [serialize_run(run) for run in runs.order_by("-id")[:50]]


def workbot_stats(user) -> dict[str, Any]:
    bots = Workbot.objects.filter(workspace_id__in=_workspace_ids(user))
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    runs = WorkbotRun.objects.filter(workbot__in=bots, created_at__gte=start)
    total = runs.count()
    success = runs.filter(status=WorkbotRun.Status.SUCCESS).count()
    minutes = {bot.id: bot.estimated_minutes for bot in bots}
    saved = 0
    for row in runs.filter(status=WorkbotRun.Status.SUCCESS).values("workbot_id").annotate(count=Count("id")):
        saved += minutes.get(row["workbot_id"], 0) * row["count"]
    rate = 0.0 if total == 0 else round(success * 1000 / total) / 10
    return {
        "active_count": bots.filter(enabled=True).count(),
        "month_run_count": total,
        "success_rate": rate,
        "saved_minutes": saved,
    }
