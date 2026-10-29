from ninja import Schema, UploadedFile


class UploadSchema(Schema):
    file_name: str
