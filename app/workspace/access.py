"""데이터베이스와 문서 페이지의 본문 쓰기 권한입니다."""

from ninja.errors import HttpError

from workspace.models import Database, Page, WorkspaceMember
from workspace.utils import get_membership


def require_access_manager(user, workspace_id: int) -> None:
    membership = get_membership(user, workspace_id)
    if membership.role not in {WorkspaceMember.Role.OWNER, WorkspaceMember.Role.ADMIN}:
        raise HttpError(403, "접근 설정은 관리자만 바꿀 수 있습니다.")


def require_content_write(user, *, database: Database | None = None, page: Page | None = None) -> None:
    if database is not None:
        access = database.access
        workspace_id = database.workspace_id
    elif page is not None and page.kind == Page.Kind.DOCUMENT:
        access = page.access
        workspace_id = page.workspace_id
    else:
        return
    if access != Database.Access.ADMIN:
        return
    membership = get_membership(user, workspace_id)
    if membership.role not in {WorkspaceMember.Role.OWNER, WorkspaceMember.Role.ADMIN}:
        raise HttpError(403, "이 문서는 관리자만 수정할 수 있습니다.")


def clean_access(value) -> str:
    if value not in {Database.Access.MEMBER, Database.Access.ADMIN}:
        raise HttpError(400, "접근 값은 member 또는 admin이어야 합니다.")
    return value
