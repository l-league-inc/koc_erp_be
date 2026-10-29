from ninja import Router, File, UploadedFile
from ninja.errors import HttpError
from api.security import jwt_auth, admin_auth
from config.schema import UploadSchema
from config.response import (
    UploadResponseSchema,
    UploadNewResponseSchema,
    DirectUploadResponseSchema,
)
from django.conf import settings
from config.aws import get_boto3_s3_client
import requests
import uuid, os
import mimetypes


router = Router(tags=["AWS"])


DJANGO_ENV_NAME = os.environ.get("DJANGO_ENV_NAME")


@router.post(
    "/upload",
    summary="[C] AWS S3 이미지 업로드 URL 생성",
    description="AWS S3에 이미지를 업로드하기 위한 URL을 생성합니다.",
    response=UploadResponseSchema,
    auth=jwt_auth,
)
async def get_aws_upload_url(request, data: UploadSchema):

    file_name = data.file_name
    file_name = file_name.replace(" ", "_") if file_name else "default_image.png"

    uuid_hex = uuid.uuid4().hex

    # 이미지 업로드 경로 설정
    object_name = f"{settings.SERVICE_NAME.lower()}/images/{DJANGO_ENV_NAME}/{uuid_hex}/{file_name}"
    image_url = f"{settings.CLOUDFRONT_URL}/{object_name}"

    s3_client = await get_boto3_s3_client()

    try:
        response = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": settings.AWS_UPLOAD_BUCKET, "Key": object_name},
            ExpiresIn=300,
        )
        return {"uploadURL": response, "imageURL": image_url}
    except Exception as e:
        raise HttpError(500, f"Failed to generate presigned URL: {e}")


@router.post(
    "/upload-new",
    summary="[C] S3 파일 업로드 (new)",
    description="파일을 업로드합니다.",
    response=UploadNewResponseSchema,
    auth=jwt_auth,
)
async def upload_file_post(request, payload: UploadSchema):
    file_name = payload.file_name

    # 확장자를 확인해서 content-type을 지정해줄 수 있음
    fields = {}
    content_type, _ = mimetypes.guess_type(file_name)  # mp3 -> audio/mpeg
    if content_type is None:
        content_type = "application/octet-stream"
    fields["Content-Type"] = content_type

    uuid_hex = uuid.uuid4().hex
    # 이미지 업로드 경로 설정
    object_name = f"{settings.SERVICE_NAME.lower()}/images/{DJANGO_ENV_NAME}/{uuid_hex}/{file_name}"
    image_url = f"{settings.CLOUDFRONT_URL}/{object_name}"

    s3_client = await get_boto3_s3_client()
    try:
        response = s3_client.generate_presigned_post(
            Fields=fields,  # Content-Type
            Bucket=settings.AWS_UPLOAD_BUCKET,
            Key=object_name,
            Conditions=[
                fields,  # Content-Type
                ["content-length-range", 1, 10485760],  # 용량 제한 1byte ~ 10MB
            ],
            ExpiresIn=300,
        )
    except Exception as e:
        raise HttpError(500, f"Failed to generate presigned URL: {e}")

    return {"uploadURL": response, "imageURL": image_url}


@router.post(
    "/directupload",
    summary="[A] AWS S3 이미지 다이렉트 업로드",
    description="AWS S3에 이미지를 다이렉트로 업로드합니다.",
    response=DirectUploadResponseSchema,
    auth=admin_auth,
)
async def direct_upload_aws_image(request, upload: UploadedFile = File(...)):
    file = upload.read()
    file_name = upload.name
    uuid_hex = uuid.uuid4().hex

    object_name = f"{settings.SERVICE_NAME.lower()}/images/{DJANGO_ENV_NAME}/{uuid_hex}/{file_name}"
    image_url = f"{settings.CLOUDFRONT_URL}/{object_name}"

    s3_client = await get_boto3_s3_client()

    try:
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": settings.AWS_UPLOAD_BUCKET, "Key": object_name},
            ExpiresIn=300,
        )
    except Exception as e:
        raise HttpError(500, f"Failed to generate presigned URL: {e}")

    response = requests.put(presigned_url, data=file)
    if response.status_code == 200:
        return {"url": image_url}
    raise HttpError(500, f"Failed to upload image: {response.text}")
