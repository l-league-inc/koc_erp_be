from typing import Optional

from ninja import Schema


class FolderCreateSchema(Schema):
    parent_id: int
    name: str


class FolderUpdateSchema(Schema):
    name: Optional[str] = None
    parent_id: Optional[int] = None


class UploadRequestSchema(Schema):
    folder_id: int
    file_name: str
    content_type: str = "application/octet-stream"
    size: int


class FileCreateSchema(Schema):
    folder_id: int
    object_key: str
    original_filename: str
    content_type: str
    size: int


class FileMoveSchema(Schema):
    folder_id: int
