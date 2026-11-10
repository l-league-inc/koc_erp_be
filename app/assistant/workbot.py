import logging
from typing import Any

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from ninja.errors import HttpError

from assistant import llm, workbot_agent
from assistant.models import Workbot, WorkbotRun
from assistant.schedule import next_run_at, parse_cron
from notification.models import Notification
from workspace.models import Property, RecordActivity, WorkspaceMember
from workspace.utils import (
    accessible_databases,
    create_record,
    fold_date_range_aliases,
    get_membership,
    query_records,
)

logger = logging.getLogger("django")
_ACTIONS = {"notify", "create_record", "agent"}


def validate_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise HttpError(400, "spec은 객체여야 합니다.")
    action = spec.get("action")
    if action not in _ACTIONS:
        raise HttpError(400, "동작은 notify, create_record, agent 중 하나입니다.")
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
        if record.get("blocks") is not None and not isinstance(record["blocks"], list):
            raise HttpError(400, "레코드 본문 블록은 배열이어야 합니다.")
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


def _fold_spec_record(user, workspace_id: int, slug: str, spec: dict[str, Any]) -> dict[str, Any]:
    record = spec.get("record")
    if not isinstance(record, dict) or not isinstance(record.get("values"), dict):
        return spec
    folded = dict(spec)
    record = dict(record)
    record["values"] = fold_date_range_aliases(
        _database(user, workspace_id, slug),
        record["values"],
    )
    folded["record"] = record
    return folded


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
        spec=_fold_spec_record(
            user,
            data["workspace_id"],
            slug,
            validate_spec(data.get("spec")),
        ),
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
        bot.spec = _fold_spec_record(
            user,
            bot.workspace_id,
            str(data.get("database_slug") or bot.database_slug).strip() or bot.database_slug,
            validate_spec(data["spec"]),
        )
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


def _schema_catalog(databases) -> str:
    lines = []
    for database in databases.prefetch_related("properties").order_by("slug"):
        fields = [
            f"{prop.slug}:{prop.name}:{prop.type}"
            for prop in database.properties.all()
            if prop.type != Property.Type.TITLE
        ]
        joined = ", ".join(fields) if fields else "없음"
        lines.append(f"- {database.slug} ({database.name}) {joined}")
    return "\n".join(lines) if lines else "- 없음"


def draft_workbot(user, workspace_id: int, instruction: str, model: str = "") -> dict[str, Any]:
    text = (instruction or "").strip()
    if not text:
        raise HttpError(400, "지시가 필요합니다.")
    get_membership(user, workspace_id)
    databases = accessible_databases(user).filter(workspace_id=workspace_id)
    catalog = _schema_catalog(databases)
    chosen = llm.use_model(user, model)
    parsed = llm.complete_json(
        [
            {
                "role": "system",
                "content": (
                    "당신은 KOC 워크봇 설계자입니다. JSON으로만 답합니다. "
                    "사용자가 요청한 대상, 조건, 주기, 만들 내용만 반영하고 요청하지 않은 동작이나 필드를 넣지 않습니다. "
                    "name, description, spec.message, spec.record.title과 사람이 읽는 값은 한국어로만 작성합니다. "
                    "영어 문장을 만들지 않습니다. "
                    "키는 name, description, database_slug, schedule, estimated_minutes, spec입니다. "
                    "name은 요청을 한 줄로 요약한 한국어 이름이고 description은 요청을 한국어로 짧게 옮긴 설명입니다. "
                    "database_slug는 아래 목록에서 요청과 가장 가까운 영역 하나입니다. "
                    "schedule은 분 시 일 월 요일 크론입니다. "
                    "매일 9시는 0 9 * * *, 매주 월요일 10시는 0 10 * * 1, 평일 9시는 0 9 * * 1-5입니다. "
                    "시각을 말하지 않았으면 0 9 * * 1-5입니다. "
                    "estimated_minutes는 요청에 있으면 그 분이고 없으면 10입니다. "
                    "spec.action은 세 가지입니다. "
                    "notify는 조건에 맞는 레코드가 있으면 알림만 보냅니다. "
                    "create_record는 매번 똑같은 제목과 값의 레코드를 만듭니다. 본문이 필요 없는 단순 등록에만 씁니다. "
                    "agent는 실행할 때마다 기존 레코드를 조회해 내용을 정리·요약·작성해야 하는 일입니다. "
                    "주간·일일 보고서, 현황 정리, 회의 자료, 요약 페이지처럼 본문이 있는 문서는 반드시 agent입니다. "
                    "agent이면 spec.filters는 빈 배열이고 spec.message는 알림에 쓸 짧은 한국어 문구입니다. "
                    "spec.filters는 그 영역 속성 slug만 쓰는 조회 필터 배열입니다. 조건이 없으면 빈 배열입니다. "
                    "spec.notify_user_ids는 정수 배열입니다. 특정 사용자를 말하지 않았으면 빈 배열입니다. "
                    "spec.message는 알림일 때 사용자에게 보여줄 한국어 문구입니다. "
                    "spec.requires_confirmation은 확인 후 실행을 요청했을 때만 true입니다. "
                    "create_record이면 spec.record.title은 한국어 제목이고 spec.record.values의 키는 그 영역 속성 slug만 씁니다. "
                    "날짜 기간은 start_date나 end_date가 아니라 date 속성 하나에 "
                    "{\"start\":\"YYYY-MM-DD\",\"end\":\"YYYY-MM-DD\"}로 넣습니다. "
                    "아래는 영역과 속성입니다.\n"
                    f"{catalog}"
                ),
            },
            {"role": "user", "content": text},
        ],
        model=chosen,
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
        "spec": _fold_spec_record(
            user,
            workspace_id,
            slug,
            validate_spec(payload.get("spec") or {}),
        ),
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
    if spec["action"] == "agent":
        return _interpret_agent(bot, actor, spec)
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
        {
            "title": spec["record"]["title"],
            "values": spec["record"].get("values") or {},
            "blocks": spec["record"].get("blocks") or [],
        },
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


def _interpret_agent(bot: Workbot, actor, spec: dict[str, Any]) -> dict[str, Any]:
    result = workbot_agent.run_agent(bot, actor, spec)
    user_ids = spec["notify_user_ids"] or [bot.owner_id]
    _member_ids(bot.workspace_id, user_ids)
    headline = spec["message"] or bot.name
    message = f"{headline}: {result['summary']}"
    payload = {
        "action": "agent",
        "notify_user_ids": user_ids,
        "message": message,
        "pending": result["pending"],
    }
    if spec["requires_confirmation"]:
        # 쓰기 도구가 대기열에 쌓인 상태라 확인 전에는 알리지도 반영하지도 않는다.
        return {
            "status": WorkbotRun.Status.WAITING,
            "summary": result["summary"],
            "record_ids": [],
            "payload": payload,
            "notify_user_ids": [],
            "message": "",
        }
    return {
        "status": WorkbotRun.Status.SUCCESS,
        "summary": result["summary"],
        "record_ids": result["record_ids"],
        "payload": payload,
        "notify_user_ids": user_ids,
        "message": message,
    }


def _record_failure(bot: Workbot, reason: str, *, notify_owner: bool) -> WorkbotRun:
    run = WorkbotRun.objects.create(
        workbot=bot,
        status=WorkbotRun.Status.FAILED,
        summary=reason[:1000],
    )
    if notify_owner:
        try:
            _notify(bot, run, [bot.owner_id], f"{bot.name} 실행 실패: {reason}")
        except Exception:
            logger.exception("workbot failure notice id=%s", bot.id)
    return run


def run_workbot(bot: Workbot, actor, *, notify_failure: bool = False) -> WorkbotRun:
    now = timezone.now()
    try:
        # 모델 호출이 길 수 있어 실행 전체를 하나의 트랜잭션으로 잡지 않고,
        # 레코드 반영과 이력 기록만 함께 묶는다.
        with transaction.atomic():
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
        run = _record_failure(bot, exc.message, notify_owner=notify_failure)
    except Exception:
        logger.exception("workbot id=%s", bot.id)
        run = _record_failure(bot, "실행에 실패했습니다.", notify_owner=notify_failure)
    bot.last_run_at = now
    if bot.enabled:
        bot.next_run_at = next_run_at(bot.schedule, now)
    bot.save(update_fields=["last_run_at", "next_run_at", "updated_at"])
    return run


def run_workbot_by_id(user, workbot_id: int) -> dict[str, Any]:
    bot = _get_bot(user, workbot_id)
    return serialize_run(run_workbot(bot, user))


def claim_due_workbots(now) -> list[Workbot]:
    """실행할 봇의 `next_run_at`을 다음 일정으로 먼저 넘기고 이긴 쪽만 돌려줍니다.

    워커가 여럿이거나 실행이 길어져도 같은 일정이 두 번 실행되지 않습니다.
    """
    # 켜져 있는데 다음 실행이 비어 있는 봇은 일정을 채워 다음 틱부터 실행되게 한다.
    for bot in Workbot.objects.filter(enabled=True, next_run_at__isnull=True):
        try:
            Workbot.objects.filter(id=bot.id, next_run_at__isnull=True).update(
                next_run_at=next_run_at(bot.schedule, now)
            )
        except HttpError:
            logger.warning("workbot id=%s 일정 형식 오류 schedule=%r", bot.id, bot.schedule)
    claimed: list[Workbot] = []
    due = Workbot.objects.select_related("owner").filter(
        enabled=True,
        next_run_at__isnull=False,
        next_run_at__lte=now,
    )
    for bot in due.order_by("next_run_at", "id"):
        try:
            upcoming = next_run_at(bot.schedule, now)
        except HttpError:
            logger.warning("workbot id=%s 일정 형식 오류 schedule=%r", bot.id, bot.schedule)
            continue
        won = Workbot.objects.filter(id=bot.id, next_run_at=bot.next_run_at).update(
            next_run_at=upcoming
        )
        if won:
            bot.next_run_at = upcoming
            claimed.append(bot)
    return claimed


def run_due_workbots() -> int:
    bots = claim_due_workbots(timezone.now())
    for bot in bots:
        logger.info("workbot run id=%s name=%s", bot.id, bot.name)
        run_workbot(bot, bot.owner, notify_failure=True)
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
            {
                "title": record.get("title"),
                "values": record.get("values") or {},
                "blocks": record.get("blocks") or [],
            },
            RecordActivity.Source.USER,
        )
        run.record_ids = [saved["id"]]
        run.summary = f"{saved['title']}을 만들었습니다."
    elif payload.get("action") == "agent":
        run.record_ids = workbot_agent.apply_pending(bot, user, payload.get("pending") or [])
        user_ids = payload.get("notify_user_ids") or []
        _member_ids(bot.workspace_id, user_ids)
        _notify(bot, run, user_ids, str(payload.get("message") or run.summary))
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
