from ninja import Schema


class UploadResponseSchema(Schema):
    uploadURL: str
    imageURL: str


class UploadNewResponseSchema(Schema):
    uploadURL: dict
    imageURL: str


class DirectUploadResponseSchema(Schema):
    url: str


class SuccessResponseSchema(Schema):
    message: str
