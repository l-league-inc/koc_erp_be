from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Max
from ninja.errors import HttpError

from workspace.events import publish_workspace_event
from workspace.models import Block, Database, Page, PageFavorite

TRASH_PAGE_KINDS = {
    Page.Kind.FOLDER,
    Page.Kind.DOCUMENT,
    Page.Kind.LINKED_VIEW,
}


def ensure_database_page(database: Database) -> Page:
    """데이터베이스 사이드바 페이지를 만들고 폴더 묶음과 맞춥니다."""
    parent = _folder_for_section(database)
    page = Page.objects.filter(database=database, kind=Page.Kind.DATABASE).first()
    if page is None:
        return Page.objects.create(
            workspace_id=database.workspace_id,
            parent=parent,
            kind=Page.Kind.DATABASE,
            name=database.name,
            icon=database.icon,
            position=database.position,
            database=database,
        )
    page.parent = parent
    page.name = database.name
    page.icon = database.icon
    page.position = database.position
    page.save(update_fields=["parent", "name", "icon", "position", "updated_at"])
    return page


def _folder_for_section(database: Database) -> Page | None:
    if not database.section_slug:
        return None
    folder = Page.objects.filter(
        workspace_id=database.workspace_id,
        kind=Page.Kind.FOLDER,
        slug=database.section_slug,
    ).first()
    if folder is None:
        return Page.objects.create(
            workspace_id=database.workspace_id,
            kind=Page.Kind.FOLDER,
            name=database.section or database.section_slug,
            slug=database.section_slug,
            position=database.position,
        )
    if database.section and folder.name != database.section:
        folder.name = database.section
        folder.save(update_fields=["name", "updated_at"])
    return folder


def sync_folder_children(folder: Page) -> None:
    children = Page.objects.filter(parent=folder, kind=Page.Kind.DATABASE).select_related(
        "database"
    )
    for child in children:
        database = child.database
        if database is None:
            continue
        database.section = folder.name
        database.section_slug = folder.slug
        database.save(update_fields=["section", "section_slug", "updated_at"])


def sync_database_section(page: Page) -> None:
    database = page.database
    if database is None:
        return
    parent = page.parent
    if parent is not None and parent.kind == Page.Kind.FOLDER:
        database.section = parent.name
        database.section_slug = parent.slug
    else:
        database.section = ""
        database.section_slug = ""
    database.name = page.name
    database.icon = page.icon
    database.position = page.position
    database.save(
        update_fields=["section", "section_slug", "name", "icon", "position", "updated_at"]
    )


def serialize_page(page: Page, *, include_blocks: bool = False) -> dict[str, Any]:
    from workspace.utils import serialize_block

    payload = {
        "id": page.id,
        "workspace_id": page.workspace_id,
        "parent_id": page.parent_id,
        "kind": page.kind,
        "name": page.name,
        "slug": page.slug,
        "icon": page.icon,
        "position": page.position,
        "database_id": page.database_id,
        "view_id": page.view_id,
        "created_at": page.created_at,
        "updated_at": page.updated_at,
    }
    if include_blocks:
        blocks = page.blocks.order_by("position", "id") if page.kind == Page.Kind.DOCUMENT else []
        payload["blocks"] = [serialize_block(block) for block in blocks]
    return payload


def serialize_favorite(favorite: PageFavorite) -> dict[str, Any]:
    page = favorite.page
    return {
        "id": favorite.id,
        "page_id": page.id,
        "name": page.name,
        "kind": page.kind,
        "icon": page.icon,
        "position": favorite.position,
        "database_id": page.database_id,
        "view_id": page.view_id,
    }


def get_page(user, page_id: int) -> Page:
    from workspace.utils import _membership_exists

    page = (
        Page.objects.select_related("workspace", "database", "parent")
        .filter(id=page_id)
        .first()
    )
    if page is None:
        raise HttpError(404, "페이지를 찾을 수 없습니다.")
    if not _membership_exists(user, page.workspace_id):
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    return page


def list_pages(user, workspace_id: int) -> list[dict[str, Any]]:
    from workspace.utils import get_membership

    get_membership(user, workspace_id)
    rows = Page.objects.filter(workspace_id=workspace_id).order_by("position", "id")
    return [serialize_page(row) for row in rows]


def _parent_page(user, workspace_id: int, parent_id: int | None) -> Page | None:
    if parent_id is None:
        return None
    parent = get_page(user, parent_id)
    if parent.workspace_id != workspace_id:
        raise HttpError(400, "부모 페이지가 같은 워크스페이스에 있어야 합니다.")
    return parent


def _reject_page_cycle(page: Page, parent: Page | None) -> None:
    current = parent
    while current is not None:
        if current.id == page.id:
            raise HttpError(400, "페이지를 자신의 하위로 옮길 수 없습니다.")
        current = current.parent


@transaction.atomic
def create_page(user, workspace_id: int, data: dict[str, Any]) -> dict[str, Any]:
    from workspace.utils import get_database, get_membership, get_view, validate_slug

    get_membership(user, workspace_id)
    kind = str(data.get("kind") or "")
    if kind not in {Page.Kind.FOLDER, Page.Kind.DOCUMENT, Page.Kind.LINKED_VIEW}:
        raise HttpError(400, "만들 수 있는 페이지는 폴더, 문서, 연결 보기입니다.")
    name = str(data.get("name") or "").strip()
    if not name:
        raise HttpError(400, "페이지 이름이 필요합니다.")
    parent = _parent_page(user, workspace_id, data.get("parent_id"))
    slug = ""
    database = None
    view = None
    if kind == Page.Kind.FOLDER:
        slug = validate_slug(str(data.get("slug") or ""))
    if kind == Page.Kind.LINKED_VIEW:
        if data.get("database_id") is None:
            raise HttpError(400, "연결 보기에는 데이터베이스가 필요합니다.")
        database = get_database(user, int(data["database_id"]))
        if database.workspace_id != workspace_id:
            raise HttpError(400, "같은 워크스페이스의 데이터베이스만 연결할 수 있습니다.")
        if data.get("view_id") is not None:
            view = get_view(user, int(data["view_id"]))
            if view.database_id != database.id:
                raise HttpError(400, "보기가 데이터베이스와 맞지 않습니다.")
    try:
        page = Page.objects.create(
            workspace_id=workspace_id,
            parent=parent,
            kind=kind,
            name=name,
            slug=slug,
            icon=str(data.get("icon") or ""),
            position=int(data.get("position") or 0),
            database=database,
            view=view,
        )
    except IntegrityError:
        raise HttpError(400, "이미 같은 키가 있습니다.") from None
    publish_workspace_event(workspace_id, "page", "created", page.id, user.id)
    return serialize_page(page, include_blocks=True)


@transaction.atomic
def update_page(user, page_id: int, data: dict[str, Any]) -> dict[str, Any]:
    from workspace.utils import validate_slug

    page = get_page(user, page_id)
    if data.get("name") is not None:
        name = str(data["name"]).strip()
        if not name:
            raise HttpError(400, "페이지 이름은 비울 수 없습니다.")
        page.name = name
    if data.get("icon") is not None:
        page.icon = str(data["icon"])
    if data.get("position") is not None:
        page.position = int(data["position"])
    if page.kind == Page.Kind.FOLDER and data.get("slug") is not None:
        page.slug = validate_slug(str(data["slug"]))
    if page.kind == Page.Kind.LINKED_VIEW and "view_id" in data:
        if data.get("view_id") is None:
            page.view = None
        else:
            from workspace.utils import get_view

            view = get_view(user, int(data["view_id"]))
            if page.database_id is None or view.database_id != page.database_id:
                raise HttpError(400, "보기가 데이터베이스와 맞지 않습니다.")
            page.view = view
    try:
        page.save()
    except IntegrityError:
        raise HttpError(400, "이미 같은 키가 있습니다.") from None
    if page.kind == Page.Kind.FOLDER and (
        data.get("name") is not None or data.get("slug") is not None
    ):
        sync_folder_children(page)
    if page.kind == Page.Kind.DATABASE:
        sync_database_section(page)
    publish_workspace_event(page.workspace_id, "page", "updated", page.id, user.id)
    return serialize_page(page, include_blocks=True)


@transaction.atomic
def move_page(user, page_id: int, data: dict[str, Any]) -> dict[str, Any]:
    page = get_page(user, page_id)
    if "parent_id" not in data:
        raise HttpError(400, "부모 페이지가 필요합니다.")
    parent = _parent_page(user, page.workspace_id, data.get("parent_id"))
    _reject_page_cycle(page, parent)
    page.parent = parent
    if data.get("position") is not None:
        page.position = int(data["position"])
    page.save(update_fields=["parent", "position", "updated_at"])
    if page.kind == Page.Kind.DATABASE:
        sync_database_section(page)
    publish_workspace_event(page.workspace_id, "page", "updated", page.id, user.id)
    return serialize_page(page)


def delete_database_page(user, page: Page) -> None:
    from workspace.utils import delete_database_object

    database = page.database
    if database is None:
        page.delete()
        publish_workspace_event(page.workspace_id, "page", "deleted", page.id, user.id)
        return
    workspace_id = page.workspace_id
    database_id = database.id
    page_id = page.id
    delete_database_object(database)
    for linked in Page.objects.filter(database_id=database_id, kind=Page.Kind.LINKED_VIEW):
        linked_id = linked.id
        linked.delete()
        publish_workspace_event(workspace_id, "page", "deleted", linked_id, user.id)
    if Page.objects.filter(id=page_id).exists():
        page.delete()
    publish_workspace_event(workspace_id, "database", "deleted", database_id, user.id)
    publish_workspace_event(workspace_id, "page", "deleted", page_id, user.id)


@transaction.atomic
def delete_page(user, page_id: int) -> None:
    page = get_page(user, page_id)
    if page.kind == Page.Kind.DATABASE:
        delete_database_page(user, page)
        return
    Page.objects.filter(parent=page).update(parent_id=page.parent_id)
    workspace_id = page.workspace_id
    deleted_id = page.id
    page.delete()
    publish_workspace_event(workspace_id, "page", "deleted", deleted_id, user.id)


@transaction.atomic
def restore_page(user, page_id: int) -> dict[str, Any]:
    from workspace.utils import _membership_exists

    page = (
        Page.all_objects.select_related("database")
        .filter(id=page_id, deleted_at__isnull=False)
        .first()
    )
    if page is None or page.kind not in TRASH_PAGE_KINDS:
        raise HttpError(404, "휴지통에서 페이지를 찾을 수 없습니다.")
    if page.kind == Page.Kind.LINKED_VIEW and (
        page.database_id is None or page.database.deleted_at is not None
    ):
        raise HttpError(404, "휴지통에서 페이지를 찾을 수 없습니다.")
    if not _membership_exists(user, page.workspace_id):
        raise HttpError(403, "워크스페이스에 접근할 수 없습니다.")
    page.restore()
    publish_workspace_event(page.workspace_id, "page", "restored", page.id, user.id)
    return serialize_page(page, include_blocks=True)


def trash_pages(workspace_id: int) -> list[dict[str, Any]]:
    rows = (
        Page.all_objects.filter(
            workspace_id=workspace_id,
            deleted_at__isnull=False,
            kind__in=TRASH_PAGE_KINDS,
        )
        .select_related("database")
        .order_by("-deleted_at", "-id")
    )
    items = []
    for row in rows:
        if row.kind == Page.Kind.LINKED_VIEW and (
            row.database_id is None or row.database.deleted_at is not None
        ):
            continue
        items.append(
            {
                "kind": "page",
                "id": row.id,
                "title": row.name,
                "icon": row.icon,
                "database_id": row.database_id,
                "database_slug": row.database.slug if row.database_id else "",
                "database_name": row.database.name if row.database_id else "",
                "page_kind": row.kind,
                "deleted_at": row.deleted_at,
            }
        )
    return items


@transaction.atomic
def duplicate_page(user, page_id: int) -> dict[str, Any]:
    page = get_page(user, page_id)
    if page.kind != Page.Kind.DOCUMENT:
        raise HttpError(400, "문서 페이지만 복제할 수 있습니다.")
    name = f"{page.name} 복사"[:100]
    copied = Page.objects.create(
        workspace_id=page.workspace_id,
        parent_id=page.parent_id,
        kind=Page.Kind.DOCUMENT,
        name=name,
        icon=page.icon,
        position=page.position + 1,
    )
    _copy_page_blocks(page, copied)
    publish_workspace_event(page.workspace_id, "page", "created", copied.id, user.id)
    return serialize_page(copied, include_blocks=True)


def _copy_page_blocks(source: Page, target: Page) -> None:
    copied: dict[int, Block] = {}
    for block in source.blocks.order_by("position", "id"):
        parent = copied.get(block.parent_id) if block.parent_id else None
        copied[block.id] = Block.objects.create(
            page=target,
            parent=parent,
            type=block.type,
            content=block.content or {},
            position=block.position,
        )


def list_page_blocks(user, page_id: int) -> list[dict[str, Any]]:
    from workspace.utils import serialize_block

    page = get_page(user, page_id)
    if page.kind != Page.Kind.DOCUMENT:
        raise HttpError(400, "문서 페이지에만 블록이 있습니다.")
    return [serialize_block(block) for block in page.blocks.order_by("position", "id")]


@transaction.atomic
def create_page_block(user, page_id: int, data: dict[str, Any]) -> dict[str, Any]:
    from workspace.utils import (
        _block_parent_for_page,
        _validate_block_type,
        serialize_block,
        validate_block_content,
    )

    page = get_page(user, page_id)
    if page.kind != Page.Kind.DOCUMENT:
        raise HttpError(400, "문서 페이지에만 블록을 추가할 수 있습니다.")
    block_type = _validate_block_type(str(data.get("type") or ""))
    content = validate_block_content(block_type, data.get("content") or {}, page.workspace_id)
    block = Block.objects.create(
        page=page,
        parent=_block_parent_for_page(user, page, data.get("parent_id")),
        type=block_type,
        content=content,
        position=int(data.get("position") or 0),
    )
    publish_workspace_event(page.workspace_id, "block", "created", block.id, user.id)
    return serialize_block(block)


@transaction.atomic
def favorite_page(user, page_id: int) -> dict[str, Any]:
    page = get_page(user, page_id)
    favorite = PageFavorite.objects.filter(user=user, page=page).first()
    if favorite is None:
        last = PageFavorite.objects.filter(user=user, page__workspace_id=page.workspace_id).aggregate(
            position=Max("position")
        )
        favorite = PageFavorite.objects.create(
            user=user,
            page=page,
            position=(last["position"] or 0) + 1,
        )
    return serialize_favorite(favorite)


@transaction.atomic
def unfavorite_page(user, page_id: int) -> None:
    page = get_page(user, page_id)
    favorite = PageFavorite.objects.filter(user=user, page=page).first()
    if favorite is not None:
        favorite.delete()


def list_favorites(user, workspace_id: int) -> list[dict[str, Any]]:
    from workspace.utils import get_membership

    get_membership(user, workspace_id)
    rows = (
        PageFavorite.objects.filter(user=user, page__workspace_id=workspace_id)
        .select_related("page")
        .order_by("position", "id")
    )
    return [serialize_favorite(row) for row in rows]
