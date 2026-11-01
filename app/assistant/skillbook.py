"""고정 스킬 파일과 워크스페이스 스킬을 읽고 저장합니다."""

from pathlib import Path
from typing import Any

from django.db import IntegrityError, transaction
from ninja.errors import HttpError

from assistant.models import Skill
from workspace.utils import get_membership, validate_slug

_SKILL_DIR = Path(__file__).resolve().parent / "skills"
BUNDLED_NAMES = (
    "attendance",
    "schedule",
    "quote",
    "travel",
    "after_service",
)
DESCRIPTION_LIMIT = 300
BODY_LIMIT = 8000
_BUNDLED = "bundled"
_USER = "user"


def _parse_frontmatter(text: str, path: Path) -> tuple[str, str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise RuntimeError(f"스킬 프론트매터가 없습니다: {path}")
    fields: dict[str, str] = {}
    body_start = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = index + 1
            break
        if ":" not in line:
            raise RuntimeError(f"스킬 프론트매터 형식이 올바르지 않습니다: {path}")
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    if body_start is None:
        raise RuntimeError(f"스킬 프론트매터가 닫히지 않았습니다: {path}")
    name = fields.get("name") or ""
    description = fields.get("description") or ""
    body = "\n".join(lines[body_start:]).strip()
    if not name or not description or not body:
        raise RuntimeError(f"스킬 이름, 설명, 본문이 필요합니다: {path}")
    return name, description, body


def load_bundled() -> list[dict[str, Any]]:
    skills = []
    for name in BUNDLED_NAMES:
        path = _SKILL_DIR / name / "SKILL.md"
        parsed_name, description, body = _parse_frontmatter(path.read_text(encoding="utf-8"), path)
        if parsed_name != name:
            raise RuntimeError(f"스킬 이름이 디렉터리와 다릅니다: {path}")
        skills.append(
            {
                "name": name,
                "description": description,
                "body": body,
                "source": _BUNDLED,
                "enabled": True,
            }
        )
    return skills


def bundled_names() -> set[str]:
    return set(BUNDLED_NAMES)


def validate_skill_name(name: str) -> str:
    return validate_slug(name)


def _reject_bundled_name(name: str) -> None:
    if name in bundled_names():
        raise HttpError(400, "고정 스킬 이름은 쓸 수 없습니다.")


def _clean_text(value: Any, *, empty_message: str, limit: int, limit_message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HttpError(400, empty_message)
    if len(text) > limit:
        raise HttpError(400, limit_message)
    return text


def clean_description(value: Any) -> str:
    return _clean_text(
        value,
        empty_message="설명이 필요합니다.",
        limit=DESCRIPTION_LIMIT,
        limit_message="설명은 300자를 넘길 수 없습니다.",
    )


def clean_body(value: Any) -> str:
    return _clean_text(
        value,
        empty_message="본문이 필요합니다.",
        limit=BODY_LIMIT,
        limit_message="본문은 8000자를 넘길 수 없습니다.",
    )


def _serialize_user(skill: Skill) -> dict[str, Any]:
    return {
        "id": skill.id,
        "workspace_id": skill.workspace_id,
        "name": skill.name,
        "description": skill.description,
        "body": skill.body,
        "source": _USER,
        "enabled": skill.enabled,
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def _serialize_bundled(workspace_id: int, skill: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": None,
        "workspace_id": workspace_id,
        "name": skill["name"],
        "description": skill["description"],
        "body": skill["body"],
        "source": _BUNDLED,
        "enabled": True,
        "created_at": None,
        "updated_at": None,
    }


def list_skills(user, workspace_id: int) -> list[dict[str, Any]]:
    get_membership(user, workspace_id)
    rows = [_serialize_bundled(workspace_id, skill) for skill in load_bundled()]
    user_skills = Skill.objects.filter(workspace_id=workspace_id).order_by("name", "id")
    rows.extend(_serialize_user(skill) for skill in user_skills)
    return rows


def active_index(workspace_id: int) -> list[dict[str, str]]:
    rows = [
        {"name": skill["name"], "description": skill["description"], "source": _BUNDLED}
        for skill in load_bundled()
    ]
    user_skills = Skill.objects.filter(workspace_id=workspace_id, enabled=True).order_by("name", "id")
    rows.extend(
        {"name": skill.name, "description": skill.description, "source": _USER}
        for skill in user_skills
    )
    return rows


def view_skill(workspace_id: int, name: str) -> dict[str, Any]:
    cleaned = (name or "").strip()
    for skill in load_bundled():
        if skill["name"] == cleaned:
            return {
                "name": skill["name"],
                "description": skill["description"],
                "body": skill["body"],
                "source": _BUNDLED,
            }
    skill = Skill.objects.filter(workspace_id=workspace_id, name=cleaned).first()
    if skill is None:
        raise HttpError(404, "스킬을 찾을 수 없습니다.")
    return {
        "name": skill.name,
        "description": skill.description,
        "body": skill.body,
        "source": _USER,
        "enabled": skill.enabled,
    }


def _get_user_skill(user, skill_id: int) -> Skill:
    skill = Skill.objects.filter(id=skill_id).first()
    if skill is None:
        raise HttpError(404, "스킬을 찾을 수 없습니다.")
    get_membership(user, skill.workspace_id)
    return skill


@transaction.atomic
def create_skill(user, data: dict[str, Any]) -> dict[str, Any]:
    workspace_id = int(data["workspace_id"])
    get_membership(user, workspace_id)
    name = validate_slug(str(data.get("name") or ""))
    _reject_bundled_name(name)
    description = clean_description(data.get("description"))
    body = clean_body(data.get("body"))
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise HttpError(400, "활성 값은 true 또는 false여야 합니다.")
    if Skill.objects.filter(workspace_id=workspace_id, name=name).exists():
        raise HttpError(400, "이미 있는 스킬 이름입니다.")
    try:
        skill = Skill.objects.create(
            workspace_id=workspace_id,
            created_by=user,
            name=name,
            description=description,
            body=body,
            enabled=enabled,
        )
    except IntegrityError:
        raise HttpError(400, "이미 있는 스킬 이름입니다.") from None
    return _serialize_user(skill)


@transaction.atomic
def update_skill(user, skill_id: int, data: dict[str, Any]) -> dict[str, Any]:
    skill = _get_user_skill(user, skill_id)
    if "description" in data:
        skill.description = clean_description(data.get("description"))
    if "body" in data:
        skill.body = clean_body(data.get("body"))
    if "enabled" in data:
        if not isinstance(data.get("enabled"), bool):
            raise HttpError(400, "활성 값은 true 또는 false여야 합니다.")
        skill.enabled = data["enabled"]
    skill.save()
    return _serialize_user(skill)


def delete_skill(user, skill_id: int) -> None:
    skill = _get_user_skill(user, skill_id)
    skill.delete()


def prepare_create_payload(workspace_id: int, arguments: dict[str, Any]) -> dict[str, Any]:
    name = validate_skill_name(str(arguments.get("name") or ""))
    _reject_bundled_name(name)
    description = clean_description(arguments.get("description"))
    body = clean_body(arguments.get("body"))
    enabled = arguments.get("enabled", True)
    if not isinstance(enabled, bool):
        raise HttpError(400, "활성 값은 true 또는 false여야 합니다.")
    if Skill.objects.filter(workspace_id=workspace_id, name=name).exists():
        raise HttpError(400, "이미 있는 스킬 이름입니다.")
    return {"name": name, "description": description, "body": body, "enabled": enabled}


def prepare_update_payload(workspace_id: int, arguments: dict[str, Any]) -> dict[str, Any]:
    name = validate_skill_name(str(arguments.get("name") or ""))
    if name in bundled_names():
        raise HttpError(400, "고정 스킬은 수정할 수 없습니다.")
    if not Skill.objects.filter(workspace_id=workspace_id, name=name).exists():
        raise HttpError(404, "스킬을 찾을 수 없습니다.")
    payload: dict[str, Any] = {"name": name}
    if "description" in arguments:
        payload["description"] = clean_description(arguments.get("description"))
    if "body" in arguments:
        payload["body"] = clean_body(arguments.get("body"))
    if "enabled" in arguments:
        if not isinstance(arguments.get("enabled"), bool):
            raise HttpError(400, "활성 값은 true 또는 false여야 합니다.")
        payload["enabled"] = arguments["enabled"]
    if len(payload) == 1:
        raise HttpError(400, "수정할 내용이 필요합니다.")
    return payload


def apply_skill_proposal(user, workspace_id: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "create_skill":
        return create_skill(
            user,
            {
                "workspace_id": workspace_id,
                "name": payload.get("name"),
                "description": payload.get("description"),
                "body": payload.get("body"),
                "enabled": payload.get("enabled", True),
            },
        )
    if kind == "update_skill":
        name = validate_slug(str(payload.get("name") or ""))
        if name in bundled_names():
            raise HttpError(400, "고정 스킬은 수정할 수 없습니다.")
        skill = Skill.objects.filter(workspace_id=workspace_id, name=name).first()
        if skill is None:
            raise HttpError(404, "스킬을 찾을 수 없습니다.")
        changes = {}
        for key in ("description", "body", "enabled"):
            if key in payload:
                changes[key] = payload[key]
        if not changes:
            raise HttpError(400, "수정할 내용이 필요합니다.")
        return update_skill(user, skill.id, changes)
    raise HttpError(400, "지원하지 않는 초안입니다.")
