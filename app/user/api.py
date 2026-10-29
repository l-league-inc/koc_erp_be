import os
from datetime import timedelta
from typing import List, Optional

from api.security import admin_auth, invalidate_auth_cache, jwt_auth, withdraw_auth
from asgiref.sync import sync_to_async
from common.outbound import SuccessResponse
from django.conf import settings
from django.contrib.auth import aauthenticate, get_user_model
from django.http import HttpResponseRedirect, JsonResponse
from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.pagination import paginate
from notification.models import Notification
from verification.models import PhonenumberVerification

from user import response, schema, utils
from user.email_util import (
    send_password_reset_email,
    # send_find_username_email,
    send_verification_email,
)
from user.models import Jwt, PasswordEmailVerification
from user.utils import decodeJWT

User = get_user_model()


router = Router(tags=["User"])


@router.post(
    "/signup",
    summary="[C] 회원가입",
    description="일반유저 회원가입을 합니다.",
    response=response.UserTinyResponseSchema,
)
async def signup_api(request, data: schema.UserSignupSchema):
    # email 중복 검사
    if (
        await User.objects.exclude(login_method=User.LoginMethodChoices.TOSS)
        .filter(email=data.email, withdraw_at__isnull=True)
        .aexists()
    ):
        raise HttpError(400, "이미 사용중인 이메일입니다.")
    # social email 중복 검사
    if (
        await User.objects.exclude(login_method=User.LoginMethodChoices.TOSS)
        .filter(social_email=data.email, withdraw_at__isnull=True)
        .aexists()
    ):
        raise HttpError(400, "이미 사용중인 이메일입니다.")
    # 전화 번호 중복 검사
    if (
        await User.objects.exclude(login_method=User.LoginMethodChoices.TOSS)
        .filter(phone_number=data.phone_number, withdraw_at__isnull=True)
        .aexists()
    ):
        raise HttpError(400, "이미 사용중인 전화번호입니다.")
    data = data.dict()
    data.pop("password2")

    phone_hash = data.pop("phone_hash", None)
    phone_number = data.get("phone_number", None)
    if phone_hash and phone_number:
        try:
            phonenumber_verification = await PhonenumberVerification.objects.aget(
                phone_number=phone_number,
                is_verified=True,
                hash=phone_hash,
            )
        except PhonenumberVerification.DoesNotExist:
            raise HttpError(400, "인증되지 않은 전화번호입니다.")

    user = await sync_to_async(User.objects.create_user)(**data)
    if os.getenv("DJANGO_SETTINGS_MODULE") != "config.settings.local":
        await sync_to_async(send_verification_email)(user)

    return user


@router.post(
    "/login",
    summary="[C] 로그인",
    description="로그인을 합니다.",
    response=response.UserLoginResponseSchema,
)
async def login_api(request, data: schema.UserLoginSchema):
    user = await aauthenticate(request, email=data.email, password=data.password)

    if not user:
        raise HttpError(404, "이메일 또는 비밀번호가 일치하지 않습니다.")

    user.last_login = timezone.make_aware(timezone.now())
    await user.asave()

    access, access_exp = utils.get_access_token(
        {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
    )
    refresh, refresh_exp = utils.get_refresh_token()

    await Jwt.objects.acreate(
        user_id=user.id,
        access=access,
        refresh=refresh,
    )

    is_flutter = getattr(request, "is_flutter", False)
    response = JsonResponse(
        {
            # 테스트
            "access": access,
            "refresh": refresh,
            "status": user.status,
            "is_flutter": is_flutter,
        }
    )
    # 플러터 환경이면 access 토큰 response에 추가
    if (
        is_flutter
        or os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings.local"
    ):
        response = JsonResponse(
            {
                "access": access,
                "refresh": refresh,
                "status": user.status,
                "is_flutter": is_flutter,
            }
        )

    # 요청하는 도메인에 따라 쿠키 설정
    host = request.get_host()

    # 쿠키에 토큰 설정
    response = utils.set_cookie_jwt(
        response, access, refresh, access_exp, refresh_exp, reset=None, host=host
    )

    return response


@router.get(
    "/logout",
    summary="[C] 로그아웃",
    description="쿠키에 있는 refresh 토큰을 가져와 로그아웃을 합니다.",
)
async def logout_api(request, payload: Optional[schema.LogoutSchema] = None):
    refresh = payload.refresh if payload else None
    refresh = refresh or request.COOKIES.get("refresh")
    active_jwt = None
    try:
        active_jwt = await Jwt.objects.select_related("user").aget(refresh=refresh)
    except Jwt.DoesNotExist:
        pass
    if active_jwt:
        await active_jwt.adelete()

    response = JsonResponse({"detail": "로그아웃 되었습니다."})

    domain = None
    host = request.get_host()
    if settings.DJANGO_ENV_NAME in ["main", "dev"]:
        domain = settings.SESSION_COOKIE_DOMAIN
    if host and host in ["localhost", "127.0.0.1"]:
        domain = None

    response.delete_cookie(
        "access",
        domain=domain,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        "refresh",
        domain=domain,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )

    return response


@router.post(
    "/refresh",
    summary="[C] 토큰 갱신",
    description="쿠키에 있는 refresh 토큰을 통해 엑세스 토큰 갱신",
    response=response.UserLoginResponseSchema,
)
async def refresh_api(request, payload: Optional[schema.TokenRefreshSchema] = None):
    refresh = payload.refresh if payload else None
    refresh = refresh or request.COOKIES.get("refresh")
    try:
        active_jwt = await Jwt.objects.select_related("user").aget(refresh=refresh)
    except Jwt.DoesNotExist:
        raise HttpError(403, "존재하지 않는 토큰입니다.")
    token_verification = await utils.verify_token(refresh)

    if token_verification is None:
        raise HttpError(403, "토큰이 만료되었습니다.")

    access, access_exp = utils.get_access_token(
        {"user_id": active_jwt.user.id, "env": settings.DJANGO_ENV_NAME}
    )
    refresh, refresh_exp = utils.get_refresh_token()

    active_jwt.access = access
    active_jwt.refresh = refresh
    await active_jwt.asave()

    is_flutter = getattr(request, "is_flutter", False)
    response = JsonResponse(
        {
            # 테스트
            "access": access,
            "refresh": refresh,
            "status": active_jwt.user.status,
            "is_flutter": is_flutter,
        }
    )

    # 플러터 환경이면 access 토큰 response에 추가
    if (
        is_flutter
        or os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings.local"
    ):
        response = JsonResponse(
            {
                "access": access,
                "refresh": refresh,
                "status": active_jwt.user.status,
                "is_flutter": is_flutter,
            }
        )

    # 요청하는 도메인에 따라 쿠키 설정
    host = request.get_host()

    response = utils.set_cookie_jwt(
        response, access, refresh, access_exp, refresh_exp, reset=None, host=host
    )

    return response


@router.get(
    "/verify",
    summary="[C] 토큰 검증",
    description="쿠키에 있는 엑세스 토큰을 통해 유저 정보를 검증합니다.",
    response={
        200: None,
    },
)
async def verify_api(request):
    user = await utils.get_user(request)
    if not isinstance(user, User):
        raise HttpError(401, "올바르지 않은 토큰입니다.")
    return 200, None


@router.get(
    "/me",
    summary="[C] 내 정보 조회",
    description="내 정보를 조회합니다.",
)
async def me_api(request):
    user = await utils.get_user(request)
    if not isinstance(user, User):
        return 200, {"data": "guest"}
    user.unread_notification_count = await Notification.objects.filter(
        user=user, is_read=False
    ).acount()
    return response.UserMeResponseSchema.from_orm(user).dict()


@router.patch(
    "/me",
    summary="[C] 내 정보 수정",
    description="내 정보를 수정합니다.",
    response=response.UserDetailResponseSchema,
    auth=jwt_auth,
)
async def me_patch_api(request, data: schema.UserUpdateSchema):
    user = request.auth
    update_data = data.dict(exclude_unset=True)

    if "nickname" in update_data:
        update_data["nickname"] = await utils.validate_nickname_for_user(
            update_data["nickname"],
            user.id,
        )

    for key, value in update_data.items():
        setattr(user, key, value)

    await user.asave()
    return user


@router.post(
    "/change-password",
    summary="[C] 비밀번호 변경",
    description="비밀번호를 변경합니다.",
    auth=jwt_auth,
)
async def change_password_api(request, data: schema.ChangePasswordSchema):
    user = request.auth
    if not user.check_password(data.password):
        raise HttpError(400, "비밀번호가 일치하지 않습니다.")
    user.set_password(data.new_password)
    await user.asave()
    return {"detail": "비밀번호가 변경되었습니다."}


@router.get(
    "/list",
    summary="[A] 유저 리스트",
    description="관리자 권한으로 유저 리스트를 조회합니다.",
    response=List[response.UserDetailResponseSchema],
    auth=admin_auth,
)
@paginate
async def get_user_list(request, filters: schema.UserListFilterSchema = Query(...)):
    @sync_to_async
    def filter_users():
        queryset = User.objects.all()
        queryset = filters.filter(queryset)
        return queryset

    users = await filter_users()

    return users


@router.get(
    "/find",
    summary="[C] 전화번호로 유저 조회",
    description="전화번호로 유저를 조회합니다.",
    response=response.UserTinyResponseSchema,
    auth=jwt_auth,
)
async def get_user_by_phone(request, phone_number: Optional[str] = None):
    if not phone_number:
        raise HttpError(400, "전화번호를 입력해주세요.")
    phone_number = "".join([i for i in phone_number if i.isdigit()])
    if len(phone_number) <= 8:
        phone_number = f"010{phone_number}"
    try:
        user = await User.objects.aget(phone_number=phone_number)
    except User.DoesNotExist:
        raise HttpError(404, "해당 전화번호로 가입된 유저가 없습니다.")
    except User.MultipleObjectsReturned:
        raise HttpError(400, "전화번호가 중복되었습니다. 관리자에게 문의해주세요.")
    return user


# @router.post(
#     "/find-username",
#     summary="[C]아이디 찾기",
#     description="이메일로 아이디를 찾습니다.",
# )
# async def find_username(request, data: schema.VerifyEmailRequestSchema):
#     try:
#         user = await User.objects.aget(email=data.email)
#     except User.DoesNotExist:
#         raise HttpError(400, "해당 이메일로 등록된 사용자가 없습니다.")
#     if os.getenv("DJANGO_SETTINGS_MODULE") != "config.settings.local":
#         await sync_to_async(send_find_username_email)(user)
#     return {"message": "아이디 찾기 이메일 인증이 전송되었어요."}


@router.post(
    "/verify-email-request",
    summary="[C] 이메일 인증 재요청",
    description="이메일 인증을 위한 이메일을 재전송합니다.",
)
async def verify_email_request(request, data: schema.VerifyEmailRequestSchema):
    try:
        user = await User.objects.aget(email=data.email)
    except User.DoesNotExist:
        raise HttpError(400, "해당 이메일로 등록된 사용자가 없습니다.")

    if user.status == User.UserStatusChoice.ACTIVE:
        raise HttpError(400, "이미 인증된 사용자에요.")

    if os.getenv("DJANGO_SETTINGS_MODULE") != "config.settings.local":
        result = await sync_to_async(send_verification_email)(user)

    return {"message": "이메일 인증 이메일이 재전송되었어요."}


@router.get(
    "/verify-email",
    summary="[C] 이메일 인증",
    description="이메일 인증을 처리하고 자동으로 로그인합니다.",
)
async def verify_email(request, token: str):
    user = await decodeJWT(f"Bearer {token}")
    if not user:
        raise HttpError(400, "토큰이 유효하지 않아요.")

    user.status = User.UserStatusChoice.ACTIVE
    user.last_login = timezone.make_aware(timezone.now())
    await user.asave()
    await invalidate_auth_cache(user.id)

    # JWT 토큰 전체 삭제
    await Jwt.objects.filter(user=user).adelete()

    access, access_exp = utils.get_access_token(
        {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
    )
    refresh, refresh_exp = utils.get_refresh_token()

    # JWT 저장
    await Jwt.objects.acreate(
        user_id=user.id,
        access=access,
        refresh=refresh,
    )

    if os.getenv("DJANGO_SETTINGS_MODULE") == "config.settings.local":
        response = JsonResponse(
            {
                "status": user.status,
                "access_token": access,
                "refresh_token": refresh,
            }
        )
        return response

    response = HttpResponseRedirect(settings.FRONTEND_LOGIN_SUCCESS_URL)
    return utils.set_cookie_jwt(
        response, access, refresh, access_exp, refresh_exp, reset=None
    )


@router.post(
    "/reset-password-request",
    summary="[C] 비밀번호 재설정 요청",
    description="비밀번호 재설정을 위한 이메일을 전송합니다.",
)
async def reset_password_request(request, data: schema.VerifyEmailRequestSchema):
    try:
        user = await User.objects.aget(email=data.email)
    except User.DoesNotExist:
        raise HttpError(400, "해당 이메일로 등록된 사용자가 없습니다.")

    verification = await utils.create_password_reset_token(user)

    if os.getenv("DJANGO_SETTINGS_MODULE") != "config.settings.local":
        await sync_to_async(send_password_reset_email)(user, verification)
    return 200, {"message": "비밀번호 재설정 이메일이 전송되었어요."}


@router.get(
    "/reset-password-verify",
    summary="[C] 비밀번호 재설정 토큰 확인",
    description="비밀번호 재설정 토큰이 유효한지 확인합니다.",
)
async def reset_password_verify(request, token: str):
    try:
        verification = await PasswordEmailVerification.objects.select_related(
            "user"
        ).aget(
            token=token,
            is_verified=False,
        )
    except PasswordEmailVerification.DoesNotExist:
        raise HttpError(400, "유효하지 않거나 만료된 비밀번호 재설정 토큰이에요.")

    if timezone.make_aware(timezone.now()) - timezone.make_aware(
        verification.created_at
    ) > timedelta(hours=settings.EMAIL_TOKEN_EXPIRE_HOURS):
        raise HttpError(400, "비밀번호 재설정 토큰이 만료되었어요.")

    user = verification.user

    # JWT 토큰 전체 삭제
    await Jwt.objects.filter(user=user).adelete()

    access, access_exp = utils.get_access_token(
        {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
    )
    refresh, refresh_exp = utils.get_refresh_token()

    # JWT 저장
    await Jwt.objects.acreate(
        user_id=user.id,
        access=access,
        refresh=refresh,
    )

    if os.getenv("DJANGO_SETTINGS_MODULE") == "config.settings.local":
        response = JsonResponse(
            {
                "status": user.status,
                "access_token": access,
                "refresh_token": refresh,
                "reset_token": token,
            }
        )
        return response

    response = HttpResponseRedirect(settings.FRONTEND_PASSWORD_RESET_SUCCESS_URL)
    return utils.set_cookie_jwt(
        response, access, refresh, access_exp, refresh_exp, reset=token
    )


@router.post(
    "/reset-password",
    summary="[C] 비밀번호 재설정",
    description="비밀번호를 재설정합니다.",
)
async def reset_password(request, data: schema.ResetPasswordSchema):
    reset = request.COOKIES.get("reset")
    if not reset:
        raise HttpError(400, "비밀번호 재설정 토큰이 없어요.")

    try:
        verification = await PasswordEmailVerification.objects.select_related(
            "user"
        ).aget(
            token=reset,
            is_verified=False,
        )
    except PasswordEmailVerification.DoesNotExist:
        raise HttpError(400, "유효하지 않거나 만료된 비밀번호 재설정 토큰이에요.")

    if timezone.make_aware(timezone.now()) - timezone.make_aware(
        verification.created_at
    ) > timedelta(hours=settings.EMAIL_TOKEN_EXPIRE_HOURS):
        raise HttpError(
            400, "비밀번호 재설정 토큰이 만료되었어요. 새로운 재설정 요청을 해주세요."
        )

    # if verification.user.check_password(data.new_password):
    #     raise HttpError(400, "새 비밀번호가 현재 비밀번호와 같아요. 다른 비밀번호를 사용해주세요.")

    verification.user.set_password(data.new_password)
    await verification.user.asave()

    verification.is_verified = True
    verification.verified_at = timezone.make_aware(timezone.now())
    await verification.asave()

    return 200, {"message": "비밀번호가 성공적으로 재설정되었어요."}


@router.post(
    "/withdraw",
    summary="[C] 회원탈퇴",
    description="회원탈퇴를 합니다.",
    response=SuccessResponse,
    auth=jwt_auth,
)
async def user_withdraw(request, data: schema.UserWithdrawSchema):
    user = request.auth

    is_valid = await sync_to_async(user.check_password)(data.password)
    if not is_valid:
        raise HttpError(400, "비밀번호가 일치하지 않습니다.")

    user.status = User.UserStatusChoice.WITHDRAW
    user.withdraw_at = timezone.make_aware(timezone.now())
    user.withdraw_reason = data.withdraw_reason
    await user.asave()
    await invalidate_auth_cache(user.id)
    return {"message": "회원탈퇴가 완료되었습니다."}


@router.post(
    "/restore",
    summary="[C] 회원 복구",
    description="회원을 복구합니다.",
    response=SuccessResponse,
    auth=withdraw_auth,
)
async def user_restore(request):
    user = request.auth
    user.status = User.UserStatusChoice.ACTIVE
    user.withdraw_at = None
    user.withdraw_reason = None
    await user.asave()
    await invalidate_auth_cache(user.id)
    return {"message": "회원 복구가 완료되었습니다."}


@router.patch(
    "/{user_id}",
    summary="[A] 유저 정보 수정, 회원 탈퇴",
    description="관리자 권한으로 유저 정보를 수정합니다.",
    response=response.UserDetailResponseSchema,
    auth=admin_auth,
)
async def update_user(request, user_id: int, data: schema.AdminUserUpdateSchema):
    try:
        user = await User.objects.aget(id=user_id)
    except User.DoesNotExist:
        raise HttpError(404, "해당 유저가 존재하지 않습니다.")

    if data.phone_number:
        if (
            await User.objects.filter(phone_number=data.phone_number)
            .exclude(status__in=[User.UserStatusChoice.WITHDRAW])
            .aexists()
        ):
            raise HttpError(400, "이미 사용중인 전화번호입니다.")
        user.phone_number = data.phone_number

    if data.status:
        user.status = data.status
        if user.status == User.UserStatusChoice.WITHDRAW:
            user.withdraw_at = timezone.make_aware(timezone.now())

    if data.withdraw_reason:
        user.withdraw_reason = data.withdraw_reason

    await user.asave()
    await invalidate_auth_cache(user.id)
    return user
