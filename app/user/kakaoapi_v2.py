from ninja import Router, Schema
from ninja.errors import HttpError
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from user.models import User, Jwt
from user import utils
from api.security import invalidate_auth_cache, jwt_auth
from user.kakao_utils import find_user_social_login
import logging
import httpx
import uuid
import re
from typing import Optional


logger = logging.getLogger("django")


router = Router(
    tags=["Kakao V2"],
)


class KakaoAuthSchema(Schema):
    access_token: str


@router.post(
    "/auth",
    summary="[C] 카카오 로그인 인증",
    description="Flutter에서 받은 카카오 access token을 검증하고 JWT를 발급합니다.",
)
async def kakao_auth(request, payload: KakaoAuthSchema):
    """
    Flutter kakao_flutter_sdk에서 받은 access_token으로 사용자 정보 조회 및 JWT 발급

    Flutter 클라이언트 예시:
    ```dart
    // 카카오 로그인
    OAuthToken token = await UserApi.instance.loginWithKakaoAccount();
    String accessToken = token.accessToken;

    // 백엔드로 access_token 전송
    final response = await dio.post('/api/kakao/v2/auth',
      data: {'access_token': accessToken}
    );
    ```
    """
    access_token = payload.access_token

    # 1. 카카오 access token으로 사용자 정보 조회
    async with httpx.AsyncClient() as client:
        try:
            kakao_user_data_response = await client.get(
                "https://kapi.kakao.com/v2/user/me",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-type": "application/x-www-form-urlencoded;charset=utf-8",
                },
            )
            kakao_user_data_response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Kakao API error: {e.response.status_code} - {e.response.text}"
            )
            raise HttpError(401, "유효하지 않은 카카오 액세스 토큰입니다.")
        except Exception as e:
            logger.error(f"Unexpected error during Kakao API call: {e}")
            raise HttpError(500, "카카오 사용자 정보 조회 중 오류가 발생했습니다.")

    kakao_data = kakao_user_data_response.json()
    kakao_user_id = kakao_data.get("id")

    if not kakao_user_id:
        raise HttpError(400, "카카오 사용자 ID를 가져올 수 없습니다.")

    kakao_account = kakao_data.get("kakao_account", {})
    social_email = kakao_account.get("email")
    gender = kakao_account.get("gender")
    phone_number = kakao_account.get("phone_number")

    if phone_number:
        phone_number = re.sub(r"^\+82\s", "0", phone_number)
        phone_number = re.sub(r"[^0-9]", "", phone_number)

    # 2. email로 가입된 일반 유저가 있는지 확인
    if social_email:
        exist_user = (
            await User.objects.exclude(login_method=User.LoginMethodChoices.TOSS)
            .filter(email=social_email, login_method=User.LoginMethodChoices.EMAIL)
            .aexists()
        )
        if exist_user:
            raise HttpError(
                400,
                f"{social_email}로 이미 가입된 계정이 있습니다. 이메일 로그인을 이용해주세요.",
            )

    # 3. phone_number로 가입된 일반 유저가 있는지 확인
    if phone_number:
        exist_user = await User.objects.filter(
            phone_number=phone_number, login_method=User.LoginMethodChoices.EMAIL
        ).aexists()
        if exist_user:
            raise HttpError(
                400,
                f"{phone_number}로 이미 가입된 계정이 있습니다. 이메일 로그인을 이용해주세요.",
            )

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
            user.last_login = timezone.now()
            user.social_user_id = str(kakao_user_id)
            await user.asave()

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

    # 6. JWT 토큰 발급
    jwt_access, access_exp = utils.get_access_token(
        {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
    )
    jwt_refresh, refresh_exp = utils.get_refresh_token()

    # 7. JWT 저장
    await Jwt.objects.acreate(
        user_id=user.id,
        access=jwt_access,
        refresh=jwt_refresh,
    )

    response = JsonResponse(
        {
            "access": jwt_access,
            "refresh": jwt_refresh,
            "status": user.status,
            "user_type": user.type,
            "user_email": social_email,
            "user_id": user.id,
        }
    )

    # 8. 쿠키 설정 (웹에서도 사용 가능하도록)
    response = utils.set_cookie_jwt(
        response,
        jwt_access,
        jwt_refresh,
        access_exp,
        refresh_exp,
        reset=None,
        host=None,
    )

    return response


@router.post(
    "/logout",
    summary="[C] 카카오 로그아웃",
    description="카카오 로그아웃 처리 (Flutter에서는 UserApi.instance.logout() 호출 후 백엔드 JWT 삭제)",
)
async def kakao_logout(request):
    """
    Flutter에서 카카오 로그아웃 후 백엔드 JWT 삭제

    Flutter 클라이언트 예시:
    ```dart
    // 카카오 로그아웃
    await UserApi.instance.logout();

    // 백엔드 JWT 삭제
    await dio.post('/api/kakao/v2/logout');
    ```
    """
    try:
        # Authorization 헤더에서 토큰 추출
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            access_token = auth_header.replace("Bearer ", "")

            # JWT 삭제
            deleted = await Jwt.objects.filter(access=access_token).adelete()

            if deleted[0] > 0:
                logger.info(f"JWT deleted for logout")

        response = JsonResponse({"message": "로그아웃 되었습니다."})
        response.delete_cookie("access")
        response.delete_cookie("refresh")

        return response

    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HttpError(500, "로그아웃 처리 중 오류가 발생했습니다.")


@router.post(
    "/unlink",
    summary="[C] 카카오 연결 해제",
    description="JWT 인증 유저의 카카오 계정을 Admin Key로 연결 해제하고 회원 탈퇴 처리",
    auth=jwt_auth,
)
async def kakao_unlink(request, withdraw_reason: Optional[str] = None):
    """
    JWT 인증 유저를 기준으로 카카오 Admin Key unlink 후 회원 탈퇴 처리

    Flutter 클라이언트 예시:
    ```dart
    // 백엔드 unlink 호출 (서비스 JWT 포함)
    await dio.post('/api/kakao/v2/unlink');
    ```
    """
    user = request.auth
    if not user:
        raise HttpError(401, "인증이 필요합니다.")

    if user.login_method != User.LoginMethodChoices.KAKAO:
        raise HttpError(400, "카카오 로그인 유저만 연결 해제할 수 있습니다.")

    if not user.social_user_id:
        raise HttpError(400, "카카오 소셜 ID가 없어 연결 해제할 수 없습니다.")

    if not getattr(settings, "KAKAO_ADMIN_KEY", None):
        logger.error("KAKAO_ADMIN_KEY is not configured")
        raise HttpError(500, "카카오 연결해제 설정이 올바르지 않습니다.")

    # 1. 카카오 연결 해제 API 호출
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://kapi.kakao.com/v1/user/unlink",
                headers={"Authorization": f"KakaoAK {settings.KAKAO_ADMIN_KEY}"},
                data={
                    "target_id_type": "user_id",
                    "target_id": user.social_user_id,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Kakao unlink error: {e.response.status_code} - {e.response.text}"
            )
            raise HttpError(400, "카카오 연결 해제에 실패했습니다.")
        except httpx.RequestError as e:
            logger.error(f"Kakao unlink request error: {e}")
            raise HttpError(502, "카카오 서버 통신에 실패했습니다.")
        except Exception as e:
            logger.error(f"Unexpected error during Kakao unlink: {e}")
            raise HttpError(500, "연결 해제 처리 중 오류가 발생했습니다.")

    try:
        result = response.json()
    except ValueError:
        raise HttpError(502, "카카오 응답 파싱에 실패했습니다.")

    kakao_user_id = result.get("id")

    if not kakao_user_id:
        raise HttpError(400, "카카오 연결 해제에 실패했습니다.")

    # 2. 인증 유저 탈퇴 처리
    try:
        user.status = User.UserStatusChoice.WITHDRAW
        user.withdraw_at = timezone.now()
        user.withdraw_reason = (
            f"카카오 연결 해제 - {withdraw_reason}"
            if withdraw_reason
            else "카카오 연결 해제"
        )
        await user.asave()
        await invalidate_auth_cache(user.id)

        # 해당 유저의 모든 JWT 삭제
        await Jwt.objects.filter(user=user).adelete()

        logger.info(f"User {kakao_user_id} unlinked and withdrawn")

        json_response = JsonResponse({"message": "카카오 연결이 해제되었습니다."})
        json_response.delete_cookie("access")
        json_response.delete_cookie("refresh")

        return json_response

    except User.DoesNotExist:
        logger.error(f"User with social_user_id {kakao_user_id} not found for unlink")
        raise HttpError(404, "사용자를 찾을 수 없습니다.")
    except Exception as e:
        logger.error(f"Error during user withdrawal: {e}")
        raise HttpError(500, "회원 탈퇴 처리 중 오류가 발생했습니다.")


@router.post(
    "/unlink/webhook",
    summary="[C] 카카오 연결 해제 웹훅",
    description="카카오에서 연결 해제 시 자동으로 호출되는 웹훅입니다.",
)
async def kakao_unlink_webhook(request, user_id: str, referrer_type: str):
    """
    카카오 관리자센터에서 설정한 웹훅 엔드포인트
    사용자가 카카오 앱 내에서 연결 해제 시 자동으로 호출됨
    """
    try:
        headers = request.headers
        authorization = headers.get("Authorization")

        # 카카오 웹훅 인증 확인
        if not authorization or not authorization.startswith("KakaoAK "):
            logger.error(f"Invalid webhook authorization header: {authorization}")
            raise HttpError(401, "Unauthorized: Invalid or missing KakaoAK header")

        if authorization != f"KakaoAK {settings.KAKAO_ADMIN_KEY}":
            logger.error(f"Invalid webhook key")
            raise HttpError(401, "Unauthorized: Invalid KakaoAK key")

        logger.info(
            f"Kakao unlink webhook called - user_id: {user_id}, referrer_type: {referrer_type}"
        )

        # 사용자 조회 및 탈퇴 처리
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

        # 해당 유저의 모든 JWT 삭제
        await Jwt.objects.filter(user=user).adelete()

        logger.info(f"User {user_id} withdrawn successfully via webhook")

        return JsonResponse({"message": "User unlinked successfully"})

    except User.DoesNotExist:
        logger.error(f"User with social_user_id {user_id} not found in webhook")
        return JsonResponse({"error": "User not found"}, status=404)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JsonResponse({"error": str(e)}, status=500)
