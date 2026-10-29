from django.conf import settings
import boto3


_s3_client = None
_ses_client = None


async def get_boto3_s3_client():
    global _s3_client
    if _s3_client is None:
        session = boto3.Session()
        _s3_client = session.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_KEY,
        )
    return _s3_client


async def get_boto3_ses_client():
    global _ses_client
    if _ses_client is None:
        session = boto3.Session()
        _ses_client = session.client(
            "ses",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_KEY,
        )
    return _ses_client
