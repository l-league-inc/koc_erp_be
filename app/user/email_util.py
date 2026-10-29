import jwt
import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from datetime import datetime, timedelta

CHARSET = "UTF-8"


def create_email_verification_token(
    user_id: int,
) -> str:
    exp = datetime.utcnow() + timedelta(hours=settings.EMAIL_TOKEN_EXPIRE_HOURS)
    to_encode = {
        "user_id": user_id,
        "exp": exp,
    }
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def send_find_username_email(user):
    session = boto3.Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_KEY,
        region_name=settings.AWS_REGION,
    )
    ses_client = session.client("ses")
    subject = f"[{settings.SERVICE_NAME}] 아이디 찾기"
    body_text = f"회원님의 아이디는 {user.username} 입니다."
    body_html = f"""
    <html>
    <head></head>
    <body>
        <h1>아이디 찾기 결과</h1>
        <p>회원님의 아이디는 <strong>{user.username}</strong> 입니다.</p>
    </body>
    </html>
    """

    try:
        response = ses_client.send_email(
            Source=settings.SENDER,
            Destination={"ToAddresses": [user.email]},
            Message={
                "Subject": {"Data": subject, "Charset": CHARSET},
                "Body": {
                    "Text": {"Data": body_text, "Charset": CHARSET},
                    "Html": {"Data": body_html, "Charset": CHARSET},
                },
            },
        )
    except ClientError as e:
        return False
    return True


def send_verification_email(user) -> bool:
    token = create_email_verification_token(user.id)
    verification_link = (
        f"{settings.BASE_URL}{settings.API_V1_STR}/auth/verify-email?token={token}"
    )
    session = boto3.Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_KEY,
        region_name=settings.AWS_REGION,
    )
    ses_client = session.client("ses")
    subject = f"[{settings.SERVICE_NAME}] 이메일 주소 인증하기"
    body_text = f"아래 버튼을 클릭하여 이메일을 인증해주세요: {verification_link}"
    body_html = f"""
    <html>
    <head></head>
    <body>
        <h1>이메일 주소 인증</h1>
        <p>아래 버튼을 클릭하여 이메일을 인증해주세요</p>
        <a style="display: inline-block; margin-top: 10px; padding: 10px 20px; font-size: 16px; color: #ffffff; background-color: #5DEBCC; text-decoration: none; border-radius: 5px;" href='{verification_link}'>이메일 인증하기</a>
    </body>
    </html>
    """

    try:
        response = ses_client.send_email(
            Source=settings.SENDER,
            Destination={"ToAddresses": [user.email]},
            Message={
                "Subject": {"Data": subject, "Charset": CHARSET},
                "Body": {
                    "Text": {"Data": body_text, "Charset": CHARSET},
                    "Html": {"Data": body_html, "Charset": CHARSET},
                },
            },
        )
    except ClientError as e:
        return False, e
    return True, None


def send_password_reset_email(user, token):
    reset_url = f"{settings.BASE_URL}{settings.API_V1_STR}/auth/reset-password-verify?token={token.token}"
    session = boto3.Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_KEY,
        region_name=settings.AWS_REGION,
    )
    ses_client = session.client("ses")
    subject = f"[{settings.SERVICE_NAME}] 비밀번호 재설정하기"
    body_text = f"비밀번호 초기화하기 위해 아래 버튼을 클릭해주세요: {reset_url}"
    body_html = f"""

    <html>
    <head></head>
    <body>
        <h1>비밀번호를 변경해주세요</h1>
        <p>아래 버튼을 클릭하여 비밀번호를 변경해주세요</p>
        <a style="display: inline-block; margin-top: 10px; padding: 10px 20px; font-size: 16px; color: #ffffff; background-color: #5DEBCC; text-decoration: none; border-radius: 5px;" href='{reset_url}'>비밀번호 변경하기</a>
    </body>
    </html>
    """

    try:
        response = ses_client.send_email(
            Source=settings.SENDER,
            Destination={"ToAddresses": [user.email]},
            Message={
                "Subject": {"Data": subject, "Charset": CHARSET},
                "Body": {
                    "Text": {"Data": body_text, "Charset": CHARSET},
                    "Html": {"Data": body_html, "Charset": CHARSET},
                },
            },
        )
    except ClientError as e:
        return False
    return True
