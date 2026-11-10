"""워크스페이스 멤버 등록과 관리입니다. owner/admin만 부릅니다."""

from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from ninja.errors import HttpError

from workspace.models import WorkspaceMember
from workspace.utils import get_membership

User = get_user_model()

Role = WorkspaceMember.Role
MANAGER_ROLES = {Role.OWNER, Role.ADMIN}


def serialize_member_detail(member: WorkspaceMember) -> dict[str, Any]:
    user = member.user
    return {
        "user_id": member.user_id,
        "name": user.name or "",
        "email": user.email or "",
        "phone_number": user.phone_number or "",
        "user_status": user.status,
        "role": member.role,
        "joined_at": member.created_at,
    }


def _require_manager(user, workspace_id: int) -> WorkspaceMember:
    membership = get_membership(user, workspace_id)
    if membership.role not in MANAGER_ROLES:
        raise HttpError(403, "멤버를 관리할 권한이 없습니다.")
    return membership


def _clean_role(role: str) -> str:
    if role not in Role.values:
        raise HttpError(400, "역할은 owner, admin, member 중 하나여야 합니다.")
    return role


def _require_owner_for_privileged(actor: WorkspaceMember, *roles: str) -> None:
    """admin/owner 역할을 주거나 건드리는 일은 owner만 합니다."""
    if actor.role != Role.OWNER and any(role in MANAGER_ROLES for role in roles):
        raise HttpError(403, "관리자와 소유자 역할은 소유자만 바꿀 수 있습니다.")


def _target_membership(workspace_id: int, target_user_id: int) -> WorkspaceMember:
    target = (
        WorkspaceMember.objects.select_for_update(of=("self",))
        .select_related("user")
        .filter(workspace_id=workspace_id, user_id=target_user_id)
        .first()
    )
    if target is None:
        raise HttpError(404, "워크스페이스 멤버를 찾을 수 없습니다.")
    return target


def _ensure_other_owner_remains(workspace_id: int, target: WorkspaceMember) -> None:
    if target.role != Role.OWNER:
        return
    others = (
        WorkspaceMember.objects.select_for_update(of=("self",))
        .filter(workspace_id=workspace_id, role=Role.OWNER)
        .exclude(pk=target.pk)
        .exists()
    )
    if not others:
        raise HttpError(400, "마지막 소유자는 바꾸거나 내보낼 수 없습니다.")


def list_member_details(user, workspace_id: int) -> list[dict[str, Any]]:
    _require_manager(user, workspace_id)
    members = (
        WorkspaceMember.objects.filter(workspace_id=workspace_id)
        .select_related("user")
        .order_by("id")
    )
    return [serialize_member_detail(member) for member in members]


@transaction.atomic
def add_member(user, workspace_id: int, data: dict[str, Any]) -> dict[str, Any]:
    actor = _require_manager(user, workspace_id)
    role = _clean_role(data.get("role") or Role.MEMBER)
    _require_owner_for_privileged(actor, role)

    user_id = data.get("user_id")
    email = (data.get("email") or "").strip()
    if bool(user_id) == bool(email):
        raise HttpError(400, "user_id와 email 중 하나만 보내주세요.")

    candidates = User.objects.filter(id=user_id) if user_id else User.objects.filter(email=email)
    target_user = candidates.exclude(status=User.UserStatusChoice.WITHDRAW).first()
    if target_user is None:
        raise HttpError(404, "등록할 유저를 찾을 수 없습니다.")

    if WorkspaceMember.objects.filter(
        workspace_id=workspace_id, user=target_user
    ).exists():
        raise HttpError(400, "이미 워크스페이스 멤버입니다.")

    member = WorkspaceMember.objects.create(
        workspace_id=workspace_id, user=target_user, role=role
    )
    return serialize_member_detail(member)


@transaction.atomic
def update_member_role(
    user, workspace_id: int, target_user_id: int, role: str
) -> dict[str, Any]:
    actor = _require_manager(user, workspace_id)
    role = _clean_role(role)
    target = _target_membership(workspace_id, target_user_id)
    _require_owner_for_privileged(actor, role, target.role)
    if target.role != role:
        if target.role == Role.OWNER:
            _ensure_other_owner_remains(workspace_id, target)
        target.role = role
        target.save(update_fields=["role", "updated_at"])
    return serialize_member_detail(target)


@transaction.atomic
def remove_member(user, workspace_id: int, target_user_id: int) -> None:
    actor = _require_manager(user, workspace_id)
    target = _target_membership(workspace_id, target_user_id)
    _require_owner_for_privileged(actor, target.role)
    _ensure_other_owner_remains(workspace_id, target)
    target.delete()
