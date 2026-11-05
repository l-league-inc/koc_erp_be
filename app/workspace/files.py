"""페이지 본문 파일을 비공개 저장소에 올립니다."""

import mimetypes
from typing import Any

from ninja.errors import HttpError

from document.storage import (
    PRESIGN_EXPIRES,
    assert_block_object_key,
    build_block_object_key,
    clean_content_type,
    presign_get,
    presign_put,
)
from workspace.utils import get_block, get_membership


def create_block_file_upload(user, workspace_id: int, file_name: str) -> dict[str, Any]:
    get_membership(user, workspace_id)
    object_key = build_block_object_key(workspace_id, file_name)
    guessed, _encoding = mimetypes.guess_type(file_name)
    return {
        "upload_url": presign_put(object_key, clean_content_type(guessed or "")),
        "object_key": object_key,
        "expires_in": PRESIGN_EXPIRES,
    }


def create_block_file_download(user, block_id: int) -> dict[str, Any]:
    block = get_block(user, block_id)
    content = block.content or {}
    object_key = content.get("object_key")
    if not isinstance(object_key, str) or not object_key:
        raise HttpError(400, "이 블록에 파일이 없습니다.")
    workspace_id = (
        block.record.database.workspace_id if block.record_id else block.page.workspace_id
    )
    assert_block_object_key(workspace_id, object_key)
    file_name = content.get("file_name")
    if not isinstance(file_name, str) or not file_name.strip():
        file_name = object_key.rsplit("/", 1)[-1]
    return {
        "download_url": presign_get(object_key, file_name),
        "expires_in": PRESIGN_EXPIRES,
    }
