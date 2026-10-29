import json
import boto3
import requests
from django.conf import settings
import httpx


async def send_alimtalk_message(receiver, message):
    """비동기적으로 메시지를 보내는 함수"""

    send_message_url = "https://apis.aligo.in/send/"
    payload = {
        "key": settings.ALIMTALK_APIKEY,
        "userid": settings.ALIMTALK_USERID,
        "sender": settings.ALIMTALK_ADMIN_NUMBER,
        "receiver": receiver,
        "msg": message,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(send_message_url, data=payload)
        return response.json()


def call_send_alimtalk_message(receiver, message):
    """AWS Lambda를 통해 알림톡 메시지를 보내는 함수"""
    lambda_client = boto3.client(
        "lambda",
        region_name=settings.AWS_UPLOAD_REGION,
        aws_access_key_id=settings.AWS_UPLOAD_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_UPLOAD_SECRET_KEY,
    )
    # Lambda 함수를 동기적으로 호출
    response = lambda_client.invoke(
        FunctionName="sogonfit-message",
        InvocationType="RequestResponse",
        Payload=json.dumps({"receiver": receiver, "message": message}),
    )

    # 응답에서 Payload 추출 및 반환
    response_payload = json.load(response["Payload"])
    return response_payload


def get_alimtalk_token():
    """알리고 토큰을 받아오는 함수"""

    get_token_url = "https://kakaoapi.aligo.in/akv10/token/create/30/s/"
    payload = {
        "apikey": settings.ALIMTALK_APIKEY,
        "userid": settings.ALIMTALK_USERID,
    }
    response = requests.post(get_token_url, data=payload)
    token = response.json().get("token", None)
    return token, response.json()
