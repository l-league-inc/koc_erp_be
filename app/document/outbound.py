from datetime import datetime
from typing import Optional

from ninja import Schema


class SpaceResponseSchema(Schema):
    id: int
    workspace_id: int
    kind: str
    owner_id: Optional[int]
    root_folder_id: int


class FolderResponseSchema(Schema):
    id: int
    space_id: int
    parent_id: Optional[int]
    name: str
    is_root: bool
    path: str
    created_at: datetime


class FileResponseSchema(Schema):
    id: int
    workspace_id: int
    space_id: int
    space_kind: str
    folder_id: int
    original_filename: str
    content_type: str
    size: int
    uploaded_by_id: Optional[int]
    path: str
    index_status: str
    index_source: str
    description_ko: str
    tags_ko: list[str]
    created_at: datetime
    updated_at: datetime


class FileDetailResponseSchema(FileResponseSchema):
    extracted_text: str
    error: str


class UploadResponseSchema(Schema):
    upload_url: str
    object_key: str
    content_type: str
    expires_in: int


class DownloadResponseSchema(Schema):
    url: str
    expires_in: int


class SearchHitSchema(Schema):
    id: int
    original_filename: str
    folder_id: int
    folder_path: str
    description_ko: str
    score: float


class MailLogResponseSchema(Schema):
    id: int
    file_id: int
    sender_id: Optional[int]
    recipients: list
    subject: str
    status: str
    sent_at: Optional[datetime]
    error: str
    created_at: datetime
