from ninja import Router
from ninja.errors import HttpError
from django.conf import settings
from django.shortcuts import redirect
from django.http import JsonResponse
from django.utils import timezone
from user.models import User, Jwt
from user.kakao_utils import find_user_social_login
from user import utils
from api.security import invalidate_auth_cache, jwt_auth
from asgiref.sync import sync_to_async
import logging
import httpx
import uuid
import re
from typing import Optional


logger = logging.getLogger("django")


router = Router(
    tags=["Kakao"],
)


@router.get(
    "/login",
    summary="[C] 카카오 로그인",
    description="카카오 로그인을 위한 URL을 반환합니다.",
)
async def kakao_login(request):
    _restApiKey = settings.KAKAO_REST_API_KEY
    _redirectUrl = settings.KAKAO_LOGIN_REDIRECT_URI
    _url = f"https://kauth.kakao.com/oauth/authorize?client_id={_restApiKey}&redirect_uri={_redirectUrl}&response_type=code"
    return redirect(_url)


@router.get(
    "/callback",
    summary="[C] 카카오 로그인 콜백",
    description="카카오 로그인 콜백 URL입니다.",
)
async def kakao_login_callback(request, code: str):
    async with httpx.AsyncClient() as client:
        kakao_response = await client.post(
            "https://kauth.kakao.com/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": settings.KAKAO_REST_API_KEY,
                "redirect_uri": settings.KAKAO_LOGIN_REDIRECT_URI,
                "code": code,
            },
        )
    kakao_response_json = kakao_response.json()
    access_token = kakao_response_json.get("access_token")
    if not access_token:
        logger.error(kakao_response)
        logger.error(kakao_response.status_code)
        logger.error(kakao_response_json)
        error_code = kakao_response_json.get("error_code")
        if error_code == "KOE320":
            raise HttpError(
                400,
                "카카오 인가 코드가 만료되었거나 이미 사용되었습니다. 다시 로그인해 주세요.",
            )
        raise HttpError(
            kakao_response.status_code,
            f"{error_code}-{kakao_response_json.get('error_description')}",
        )
    async with httpx.AsyncClient() as client:
        kakao_user_data_response = await client.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-type": "application/x-www-form-urlencoded;charset=utf-8",
            },
            params={"target_id_type": "user_id"},
        )
    kakao_data = kakao_user_data_response.json()
    kakao_user_id = kakao_data.get("id")
    if kakao_user_data_response.status_code != 200:
        logger.error(kakao_user_data_response)
        logger.error(kakao_user_data_response.status_code)
        logger.error(kakao_data)
        raise HttpError(
            kakao_user_data_response.status_code, kakao_user_data_response.msg
        )

    kakao_account = kakao_data.get("kakao_account")
    social_email = kakao_account.get("email")
    gender = kakao_account.get("gender")
    phone_number = kakao_account.get("phone_number")
    if phone_number is not None:
        phone_number = re.sub(r"^\+82\s", "0", phone_number)
        phone_number = re.sub(r"[^0-9]", "", phone_number)

    # email로 가입된 유저가 있는지 확인
    exist_user = (
        await User.objects.exclude(login_method=User.LoginMethodChoices.TOSS)
        .filter(email=social_email)
        .aexists()
    )
    if exist_user:
        raise HttpError(400, f"{social_email}로 가입된 유저가 있습니다.")
    # phone_number로 가입된 유저가 있는지 확인
    if phone_number is not None:
        exist_user = (
            await User.objects.exclude(login_method=User.LoginMethodChoices.TOSS)
            .filter(
                phone_number=phone_number, login_method=User.LoginMethodChoices.EMAIL
            )
            .aexists()
        )
        if exist_user:
            raise HttpError(400, f"{phone_number}로 가입된 유저가 있습니다.")

    # 세션에 토큰 저장
    await sync_to_async(request.session.__setitem__)("access_token", access_token)
    await sync_to_async(setattr)(request.session, "modified", True)

    # 탈퇴한 유저 확인 (7일 제한 없이 먼저 조회)
    try:
        withdrawn_user = await User.objects.aget(
            social_user_id=str(kakao_user_id),
            login_method=User.LoginMethodChoices.KAKAO,
            status=User.UserStatusChoice.WITHDRAW,
            withdraw_at__isnull=False,
        )

        # 탈퇴 후 7일 이내인지 확인
        seven_days_ago = timezone.now() - timezone.timedelta(days=7)
        if withdrawn_user.withdraw_at >= seven_days_ago:
            # 7일 이내: 재활성화
            logger.info(
                f"User with social_user_id {kakao_user_id} found within 7 days, reactivating account."
            )
            user = withdrawn_user
            # user.status = User.UserStatusChoice.ACTIVE
            # user.withdraw_at = None
            # user.withdraw_reason = None
            user.social_user_id = str(kakao_user_id)
            user.last_login = timezone.now()
            await user.asave()
        else:
            # 7일 초과: 기존 유저의 social_user_id와 social_email을 정리하고 새 계정 생성
            logger.info(
                f"User with social_user_id {kakao_user_id} found but 7+ days withdrawn. Clearing old social data and creating new account."
            )

            # 기존 탈퇴 유저의 social_user_id와 social_email을 null로 변경하여 충돌 방지
            withdrawn_user.social_user_id = None
            withdrawn_user.social_email = None
            await withdrawn_user.asave()

            logger.info(
                f"Cleared withdrawn user (id={withdrawn_user.id}) social data. "
                f"Now creating new account with social_email={social_email}"
            )

            # 새 유저 생성
            unique_username = f"kakao-{social_email}-{uuid.uuid4()}"
            (
                user,
                created,
                access,
                refresh,
                access_exp,
                refresh_exp,
            ) = await find_user_social_login(
                email=unique_username,
                login_method=User.LoginMethodChoices.KAKAO,
                social_username=unique_username,
                social_email=social_email,
                phone_number=phone_number,
                gender=gender,
            )
            logger.info(
                f"find_user_social_login returned: user_id={user.id}, created={created}, status={user.status}"
            )
            user.last_login = timezone.now()
            user.social_user_id = str(kakao_user_id)
            await user.asave()
            logger.info(f"Set social_user_id={kakao_user_id} for new user {user.id}")

    except User.DoesNotExist:
        # 신규 유저 생성
        logger.info(
            f"User with social_user_id {kakao_user_id} not found. Creating new account."
        )

        unique_username = f"kakao-{social_email}-{uuid.uuid4()}"
        (
            user,
            created,
            access,
            refresh,
            access_exp,
            refresh_exp,
        ) = await find_user_social_login(
            email=unique_username,
            login_method=User.LoginMethodChoices.KAKAO,
            social_username=unique_username,
            social_email=social_email,
            phone_number=phone_number,
            gender=gender,
        )
        user.last_login = timezone.now()
        user.social_user_id = str(kakao_user_id)
        await user.asave()

    # 토큰 재발급
    access, access_exp = utils.get_access_token(
        {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
    )
    refresh, refresh_exp = utils.get_refresh_token()

    await Jwt.objects.acreate(
        user_id=user.id,
        access=access,
        refresh=refresh,
    )

    response = JsonResponse(
        {
            "user_info": kakao_account,
            "access": access,
            "refresh": refresh,
            "status": user.status,
            "user_email": social_email,
            "user_type": user.type,
        }
    )

    # 쿠키에 토큰 설정
    response = utils.set_cookie_jwt(
        response, access, refresh, access_exp, refresh_exp, reset=None, host=None
    )

    return response


@router.get(
    "/logout",
    summary="[C] 카카오 로그아웃",
    description="카카오 로그아웃을 위한 URL을 반환합니다.",
)
async def kakao_logout(request):
    _restApiKey = settings.KAKAO_REST_API_KEY
    _redirectUrl = f"{settings.KAKAO_LOGIN_DOMAIN}/logout/kakao/callback"
    _url = f"https://kauth.kakao.com/oauth/logout?client_id={_restApiKey}&logout_redirect_uri={_redirectUrl}"
    return {"logout_url": _url}


@router.get(
    "/unlink",
    summary="[C] 카카오 연결 해제",
    description="카카오 연결 해제를 위한 URL을 반환합니다.",
    auth=jwt_auth,
)
async def kakao_unlink(request, withdraw_reason: Optional[str] = None):
    user = request.auth
    if not user:
        raise HttpError(401, "인증이 필요합니다.")

    if user.login_method != User.LoginMethodChoices.KAKAO:
        return JsonResponse(
            {"data": "카카오 로그인 유저만 연결 해제할 수 있습니다."}, status=400
        )

    if not user.social_user_id:
        return JsonResponse(
            {"data": "카카오 소셜 ID가 없어 연결 해제할 수 없습니다."}, status=400
        )

    if not getattr(settings, "KAKAO_ADMIN_KEY", None):
        logger.error("KAKAO_ADMIN_KEY is not configured")
        return JsonResponse(
            {"data": "카카오 연결해제 설정이 올바르지 않습니다."}, status=500
        )

    _url = "https://kapi.kakao.com/v1/user/unlink"
    _header = {"Authorization": f"KakaoAK {settings.KAKAO_ADMIN_KEY}"}
    _data = {
        "target_id_type": "user_id",
        "target_id": user.social_user_id,
    }

    async with httpx.AsyncClient() as client:
        try:
            _res = await client.post(
                _url,
                headers=_header,
                data=_data,
            )
            _res.raise_for_status()
        except httpx.HTTPStatusError as e:
            return JsonResponse({"data": e.response.json()}, status=400)
        except httpx.RequestError:
            return JsonResponse(
                {"data": "카카오 서버 통신에 실패했습니다."}, status=502
            )

    try:
        _result = _res.json()
    except ValueError:
        return JsonResponse({"data": "카카오 응답 파싱에 실패했습니다."}, status=502)

    if _result.get("id"):
        user.status = User.UserStatusChoice.WITHDRAW
        user.withdraw_at = timezone.now()
        user.withdraw_reason = (
            f"카카오 연결 해제 - {withdraw_reason}"
            if withdraw_reason
            else "카카오 연결 해제"
        )
        await user.asave()
        await invalidate_auth_cache(user.id)

        await Jwt.objects.filter(user=user).adelete()

        await sync_to_async(request.session.pop)("access_token", None)

        response = JsonResponse({"data": "카카오 연결해제 되었습니다."})

        response.delete_cookie("access")
        response.delete_cookie("refresh")

        return response
    return JsonResponse({"data": "카카오 연결해제 실패했습니다."}, status=400)


@router.get(
    "/unlink/webhook",
    summary="[C] 카카오 연결 해제 웹훅",
    description="카카오 연결 해제 웹훅입니다. 카카오에서 연결 해제 시 호출됩니다.",
)
async def kakao_unlink_webhook(request, user_id: str, referrer_type: str):
    try:
        headers = request.headers
        authorization = headers.get("Authorization")
        if not authorization or not authorization.startswith("KakaoAK "):
            raise HttpError(401, "Unauthorized: Invalid or missing KakaoAK header")
        if authorization != f"KakaoAK {settings.KAKAO_ADMIN_KEY}":
            raise HttpError(401, "Unauthorized: Invalid KakaoAK key")
        logger.info(
            f"Kakao unlink webhook called with user_id: {user_id}, referrer_type: {referrer_type}"
        )
        logger.info(f"Headers: {headers}")
        user = await User.objects.aget(
            social_user_id=user_id,
            login_method=User.LoginMethodChoices.KAKAO,
        )

        if user.status == User.UserStatusChoice.WITHDRAW:
            logger.info(f"User {user_id} already withdrawn. webhook no-op.")
            return JsonResponse({"message": "User already unlinked"})

        user.status = User.UserStatusChoice.WITHDRAW
        user.withdraw_at = timezone.now()
        user.withdraw_reason = user.withdraw_reason or "카카오 연결 해제 (웹훅)"
        await user.asave()
        await invalidate_auth_cache(user.id)
        await Jwt.objects.filter(user=user).adelete()
        logger.info(f"User {user_id} has been withdrawn successfully.")
        return JsonResponse({"message": "User unlinked successfully"})
    except User.DoesNotExist:
        logger.error(f"User with social_user_id {user_id} not found.")
        return JsonResponse({"error": "User not found"}, status=404)
    except Exception as e:
        logger.error(f"Error in kakao unlink webhook: {e}")
        return JsonResponse({"error": str(e)}, status=500)
