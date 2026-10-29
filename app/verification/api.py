from ninja import Router
from ninja.errors import HttpError
from ninja.throttling import AnonRateThrottle
from user.models import User
from verification.models import (
    PhonenumberVerification,
    UsernamePhoneVerification,
    PasswordPhoneVerification,
)
from verification.inbound import (
    PhoneVerificationRequestSchema,
    PhoneVerificationCheckRequestSchema,
    PasswordPhoneVerificationRequestSchema,
    PasswordPhoneVerificationCheckRequestSchema,
    PasswordPhoneVerificationChangeRequestSchema,
)
from verification.outbound import (
    PhoneVerificationSuccessResponseSchema,
    UsernamePhoneVerificationResponseSchema,
    PasswordPhoneVerificationResponseSchema,
)
from config.response import SuccessResponseSchema
from django.utils import timezone
import random
import string
from verification.notification import send_alimtalk_message
from django.conf import settings
import uuid, os
from django.db import transaction
from asgiref.sync import sync_to_async
from user.models import User
from django.db.models import Q


router = Router(tags=["Verification"])


@router.post(
    "/phone",
    summary="[C] 전화번호 인증 코드 요청",
    description="전화번호를 입력받아 인증 코드를 요청합니다.",
    response=SuccessResponseSchema,
    throttle=[AnonRateThrottle("10/s")],
)
async def phone_verification_request(request, payload: PhoneVerificationRequestSchema):

    if await User.objects.filter(phone_number=payload.phone_number).aexists():
        raise HttpError(400, "해당 번호로 가입된 유저가 있습니다.")

    (
        phonenumber_verification,
        created,
    ) = await PhonenumberVerification.objects.aget_or_create(
        phone_number=payload.phone_number
    )
    if not created:
        phonenumber_verification.request_at = timezone.now()
        phonenumber_verification.code = "".join(random.choices(string.digits, k=6))
        phonenumber_verification.is_verified = False
        phonenumber_verification.hash = None
        await phonenumber_verification.asave(
            update_fields=["request_at", "code", "is_verified", "hash"]
        )

    if os.environ.get("DJANGO_ENV_NAME") != "local":
        # 알림톡 메시지 전송
        result = await send_alimtalk_message(
            payload.phone_number,
            f"[KOC ERP] 인증번호 [{phonenumber_verification.code}]를 입력해주세요.",
        )
        if int(result["result_code"]) < 0:
            raise HttpError(
                500,
                f"알림톡 메시지 전송에 실패했습니다. err_code : {result['result_code']} {result['message']}",
            )

    return {"message": "인증 코드가 발송되었습니다."}


@router.post(
    "/phone-check",
    summary="[C] 전화번호 인증 코드 확인",
    description="전화번호와 인증 코드를 입력받아 인증을 확인합니다.",
    response=PhoneVerificationSuccessResponseSchema,
    throttle=[AnonRateThrottle("10/h")],
)
async def phone_verification_check(
    request, payload: PhoneVerificationCheckRequestSchema
):

    try:
        phonenumber_verification = await PhonenumberVerification.objects.aget(
            phone_number=payload.phone_number, code=payload.code
        )
    except PhonenumberVerification.DoesNotExist:
        raise HttpError(400, "인증 코드가 일치하지 않습니다.")

    if phonenumber_verification.is_verified:
        raise HttpError(400, "인증 코드가 만료되었습니다.")

    now = timezone.now()
    if (
        now - phonenumber_verification.request_at
    ).total_seconds() > settings.PHONE_VERIFICATION_LIMIT_TIME:
        raise HttpError(400, "인증 코드가 만료되었습니다.")

    phonenumber_verification.is_verified = True
    phonenumber_verification.hash = uuid.uuid4().hex + uuid.uuid4().hex
    await phonenumber_verification.asave(update_fields=["is_verified", "hash"])

    return {
        "message": "휴대폰 번호가 성공적으로 인증되었습니다.",
        "phone_hash": phonenumber_verification.hash,
    }


@router.post(
    "/email-phone",
    summary="[C] 아이디 찾기(휴대폰 번호 인증) 요청",
    description="아이디 찾기 요청 시 휴대폰 번호 인증을 위한 코드를 요청합니다.",
    response=SuccessResponseSchema,
    throttle=[AnonRateThrottle("10/s")],
)
async def email_phone_verification_request(
    request, payload: PhoneVerificationRequestSchema
):

    try:
        user = await User.objects.aget(phone_number=payload.phone_number)
    except User.DoesNotExist:
        raise HttpError(400, "해당 번호로 가입된 유저가 없습니다.")
    except User.MultipleObjectsReturned:
        raise HttpError(
            400, "해당 번호로 가입된 유저가 여러 명 있습니다. 1:1 문의로 요청해주세요."
        )

    username_phone_verification = await UsernamePhoneVerification.objects.acreate(
        user=user,
    )
    if os.environ.get("DJANGO_ENV_NAME") != "local":
        # 문자 메시지 전송
        result = await send_alimtalk_message(
            user.phone_number,
            f"[KOC ERP] 인증번호 [{username_phone_verification.code}]를 입력해주세요.",
        )
        if int(result["result_code"]) < 0:
            raise HttpError(
                500,
                f"알림톡 메시지 전송에 실패했습니다. err_code : {result['result_code']} {result['message']}",
            )

    return {"message": "인증 코드가 발송되었습니다."}


@router.post(
    "/email-phone-check",
    summary="[C] 아이디 찾기(휴대폰 번호 인증) 확인",
    description="아이디 찾기 요청 시 휴대폰 번호와 인증 코드를 입력받아 인증을 확인합니다.",
    response=UsernamePhoneVerificationResponseSchema,
    throttle=[AnonRateThrottle("10/h")],
)
async def email_phone_verification_check(
    request, payload: PhoneVerificationCheckRequestSchema
):
    try:
        user = await User.objects.aget(phone_number=payload.phone_number)
    except User.DoesNotExist:
        raise HttpError(400, "해당 번호로 가입된 유저가 없습니다.")
    except User.MultipleObjectsReturned:
        raise HttpError(
            400, "해당 번호로 가입된 유저가 여러 명 있습니다. 1:1 문의로 요청해주세요."
        )
    try:
        phonenumber_verification = await UsernamePhoneVerification.objects.aget(
            user=user, code=payload.code
        )
    except UsernamePhoneVerification.DoesNotExist:
        raise HttpError(400, "인증 코드가 일치하지 않습니다.")

    if phonenumber_verification.is_verified:
        raise HttpError(400, "인증 코드가 만료되었습니다.")

    now = timezone.now()
    if (
        now - phonenumber_verification.request_at
    ).total_seconds() > settings.PHONE_VERIFICATION_LIMIT_TIME:
        raise HttpError(400, "인증 코드가 만료되었습니다.")

    phonenumber_verification.is_verified = True
    await phonenumber_verification.asave(update_fields=["is_verified"])

    user_email = None
    if user.login_method == User.LoginMethodChoices.EMAIL:
        user_email = user.email
    else:
        user_email = user.social_email

    return {
        "message": "휴대폰 번호가 성공적으로 인증되었습니다.",
        "phone_number": user.phone_number,
        "email": user_email,
        "login_method": user.login_method,
    }


@router.post(
    "/password-phone",
    summary="[C] 비밀번호 찾기(휴대폰 번호 인증) 요청",
    description="비밀번호 찾기 요청 시 휴대폰 번호 인증을 위한 코드를 요청합니다.",
    response=SuccessResponseSchema,
    throttle=[AnonRateThrottle("10/s")],
)
async def password_phone_verification_request(
    request, payload: PasswordPhoneVerificationRequestSchema
):

    try:
        user = await User.objects.aget(
            Q(phone_number=payload.phone_number)
            & (Q(email=payload.email) | Q(social_email=payload.email))
        )
    except User.DoesNotExist:
        raise HttpError(
            400, "해당 정보의 유저가 없습니다. 휴대폰 번호와 이메일을 확인해주세요."
        )
    except User.MultipleObjectsReturned:
        raise HttpError(
            400, "해당 번호로 가입된 유저가 여러 명 있습니다. 1:1 문의로 요청해주세요."
        )

    if user.login_method != User.LoginMethodChoices.EMAIL:
        raise HttpError(
            400,
            f"비밀번호 찾기는 이메일로 가입하신 사용자만 이용할 수 있습니다. 현재 '{user.login_method}'로 가입하셨습니다.",
        )

    password_phone_verification = await PasswordPhoneVerification.objects.acreate(
        user=user,
    )

    if os.environ.get("DJANGO_ENV_NAME") != "local":
        # 문자 메시지 전송
        result = await send_alimtalk_message(
            user.phone_number,
            f"[KOC ERP] 인증번호 [{password_phone_verification.code}]를 입력해주세요.",
        )
        if int(result["result_code"]) < 0:
            raise HttpError(
                500,
                f"알림톡 메시지 전송에 실패했습니다. err_code : {result['result_code']} {result['message']}",
            )

    return {"message": "인증 코드가 발송되었습니다."}


@router.post(
    "/password-phone-check",
    summary="[C] 비밀번호 찾기(휴대폰 번호 인증) 확인",
    description="비밀번호 찾기 요청 시 휴대폰 번호와 인증 코드를 입력받아 인증을 확인합니다.",
    response=PasswordPhoneVerificationResponseSchema,
    throttle=[AnonRateThrottle("10/h")],
)
async def password_phone_verification_check(
    request, payload: PasswordPhoneVerificationCheckRequestSchema
):
    try:
        user = await User.objects.aget(
            phone_number=payload.phone_number, email=payload.email
        )
    except User.DoesNotExist:
        raise HttpError(
            400, "해당 정보의 유저가 없습니다. 휴대폰 번호와 이메일을 확인해주세요."
        )
    except User.MultipleObjectsReturned:
        raise HttpError(
            400, "해당 번호로 가입된 유저가 여러 명 있습니다. 1:1 문의로 요청해주세요."
        )
    try:
        phonenumber_verification = await PasswordPhoneVerification.objects.aget(
            user=user, code=payload.code
        )
    except PasswordPhoneVerification.DoesNotExist:
        raise HttpError(400, "인증 코드가 일치하지 않습니다.")

    if phonenumber_verification.is_verified:
        raise HttpError(400, "인증 코드가 만료되었습니다.")

    now = timezone.now()
    if (
        now - phonenumber_verification.request_at
    ).total_seconds() > settings.PHONE_VERIFICATION_LIMIT_TIME:
        raise HttpError(400, "인증 코드가 만료되었습니다.")

    phonenumber_verification.is_verified = True
    phonenumber_verification.hash = uuid.uuid4().hex + uuid.uuid4().hex
    await phonenumber_verification.asave(update_fields=["is_verified", "hash"])

    return {
        "message": "휴대폰 번호가 성공적으로 인증되었습니다.",
        "phone_hash": phonenumber_verification.hash,
        "phone_number": user.phone_number,
        "email": user.email,
    }


@router.post(
    "/password-phone-change",
    summary="[C] 비밀번호 찾기 - 비밀번호 재설정",
    description="휴대폰 번호 인증 후 비밀번호를 재설정합니다.",
    response=SuccessResponseSchema,
    throttle=[AnonRateThrottle("10/s")],
)
async def password_phone_verification_change(
    request, payload: PasswordPhoneVerificationChangeRequestSchema
):
    try:
        user = await User.objects.aget(phone_number=payload.phone_number)
    except User.DoesNotExist:
        raise HttpError(400, "해당 번호로 가입된 유저가 없습니다.")
    except User.MultipleObjectsReturned:
        raise HttpError(
            400, "해당 번호로 가입된 유저가 여러 명 있습니다. 1:1 문의로 요청해주세요."
        )

    try:
        password_phone_verification = await PasswordPhoneVerification.objects.aget(
            user=user, hash=payload.phone_hash
        )
    except PasswordPhoneVerification.DoesNotExist:
        raise HttpError(
            400, "잘못된 접근입니다. 인증 코드를 다시 요청해주세요. ERROR-CODE-430"
        )

    if password_phone_verification.is_used:
        raise HttpError(
            400, "잘못된 접근입니다. 인증 코드를 다시 요청해주세요. ERROR-CODE-431"
        )

    if not password_phone_verification.is_verified:
        raise HttpError(
            400, "잘못된 접근입니다. 인증 코드를 다시 요청해주세요. ERROR-CODE-432"
        )

    @sync_to_async
    @transaction.atomic
    def change_password():
        user.set_password(payload.new_password)
        user.save()
        password_phone_verification.is_used = True
        password_phone_verification.save(update_fields=["is_used"])

    await change_password()

    return {"message": "비밀번호가 성공적으로 변경되었습니다."}
