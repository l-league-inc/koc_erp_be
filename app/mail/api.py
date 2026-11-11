from asgiref.sync import sync_to_async
from ninja import Router

from api.security import jwt_auth
from mail import service
from mail.schema import (
    MailAccountResponseSchema,
    MailAccountUpsertSchema,
    MailMessageDetailSchema,
    MailMessageListItemSchema,
    MailSendResponseSchema,
    MailSendSchema,
)

router = Router(tags=["Mail"])


@router.get(
    "/account",
    summary="[C] 메일 계정 조회",
    description="연결된 Daum 메일 계정 상태를 조회합니다. 앱 비밀번호는 반환하지 않습니다.",
    response=MailAccountResponseSchema,
    auth=jwt_auth,
)
async def get_account_api(request):
    return await sync_to_async(service.get_account)(request.auth)


@router.put(
    "/account",
    summary="[C] 메일 계정 등록",
    description="Daum 메일 아이디와 앱 비밀번호를 저장하고 IMAP/SMTP 연결을 확인합니다.",
    response=MailAccountResponseSchema,
    auth=jwt_auth,
)
async def upsert_account_api(request, payload: MailAccountUpsertSchema):
    return await sync_to_async(service.upsert_account)(
        request.auth,
        payload.username,
        payload.app_password,
    )


@router.delete(
    "/account",
    summary="[C] 메일 계정 삭제",
    description="연결된 메일 계정을 제거합니다.",
    response={204: None},
    auth=jwt_auth,
)
async def delete_account_api(request):
    await sync_to_async(service.delete_account)(request.auth)
    return 204, None


@router.get(
    "/messages",
    summary="[C] 메일 목록 조회",
    description="IMAP으로 메일 목록을 조회합니다.",
    response=list[MailMessageListItemSchema],
    auth=jwt_auth,
)
async def list_messages_api(
    request,
    folder: str = "INBOX",
    limit: int = 20,
    unread_only: bool = False,
):
    return await sync_to_async(service.list_messages)(
        request.auth,
        folder=folder,
        limit=limit,
        unread_only=unread_only,
    )


@router.get(
    "/messages/{uid}",
    summary="[C] 메일 상세 조회",
    description="IMAP으로 메일 본문을 조회합니다.",
    response=MailMessageDetailSchema,
    auth=jwt_auth,
)
async def get_message_api(request, uid: str, folder: str = "INBOX"):
    return await sync_to_async(service.get_message)(request.auth, uid, folder=folder)


@router.post(
    "/send",
    summary="[C] 메일 작성 발송",
    description="SMTP로 메일을 발송합니다.",
    response=MailSendResponseSchema,
    auth=jwt_auth,
)
async def send_message_api(request, payload: MailSendSchema):
    return await sync_to_async(service.send_message)(
        request.auth,
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        cc=payload.cc,
        bcc=payload.bcc,
    )
