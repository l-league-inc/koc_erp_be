from ninja import Router
from ninja.errors import HttpError
from django.conf import settings
from django.shortcuts import redirect
from django.http import JsonResponse
from django.utils import timezone
from user.models import User, Jwt
from user import utils
from api.security import invalidate_auth_cache, jwt_auth
from asgiref.sync import sync_to_async
import logging
import httpx
import uuid
import jwt
import time
from typing import Optional


logger = logging.getLogger("django")


router = Router(
    tags=["Apple"],
)


def generate_apple_client_secret():
    """
    Apple Client Secret 생성 (JWT 형식)
    Apple은 client_secret을 직접 발급하지 않고, 개발자가 직접 JWT를 생성해야 함
    """
    # Private Key 로드 (settings에서 파일 경로 또는 키 값 가져오기)
    try:
        # Apple Developer Console에서 다운로드한 .p8 파일의 내용
        private_key = settings.APPLE_PRIVATE_KEY

        headers = {
            "kid": settings.APPLE_KEY_ID,  # Key ID from Apple Developer Console
            "alg": "ES256",
        }

        payload = {
            "iss": settings.APPLE_TEAM_ID,  # Team ID
            "iat": int(time.time()),
            "exp": int(time.time()) + 86400 * 180,  # 6개월 (최대 180일)
            "aud": "https://appleid.apple.com",
            "sub": settings.APPLE_CLIENT_ID,  # Service ID (Bundle ID)
        }

        client_secret = jwt.encode(
            payload, private_key, algorithm="ES256", headers=headers
        )

        return client_secret
    except Exception as e:
        logger.error(f"Failed to generate Apple client secret: {e}")
        raise HttpError(500, "Apple 인증 설정 오류")


@router.get(
    "/login",
    summary="[C] 애플 로그인",
    description="애플 로그인을 위한 URL로 리다이렉트합니다.",
)
async def apple_login(request):
    """
    Apple OAuth 2.0 Authorization URL로 리다이렉트
    """
    state = str(uuid.uuid4())  # CSRF 방지를 위한 state

    # 세션에 state 저장
    await sync_to_async(request.session.__setitem__)("apple_login_state", state)
    await sync_to_async(setattr)(request.session, "modified", True)

    params = {
        "client_id": settings.APPLE_CLIENT_ID,  # Service ID
        "redirect_uri": settings.APPLE_REDIRECT_URI,
        "response_type": "code",
        "state": state,
        "scope": "name email",  # 요청할 권한
        "response_mode": "form_post",  # Apple은 form_post 방식 권장
    }

    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    auth_url = f"https://appleid.apple.com/auth/authorize?{query_string}"

    return redirect(auth_url)


@router.post(
    "/callback",
    summary="[C] 애플 로그인 콜백",
    description="애플 로그인 콜백 URL입니다. Apple에서 인증 후 호출됩니다.",
)
async def apple_login_callback(
    request,
    code: str = None,
    state: str = None,
    user: str = None,  # Apple이 첫 로그인 시에만 제공 (JSON string)
):
    """
    Apple OAuth 콜백 처리

    Args:
        code: Authorization code
        state: CSRF 방지용 state
        user: 첫 로그인 시에만 제공되는 사용자 정보 (JSON string)
    """
    # State 검증
    try:
        saved_state = await sync_to_async(request.session.__getitem__)(
            "apple_login_state"
        )
        if state != saved_state:
            raise HttpError(400, "Invalid state parameter")
        await sync_to_async(request.session.__delitem__)("apple_login_state")
    except KeyError:
        raise HttpError(400, "State not found in session")

    if not code:
        raise HttpError(400, "Authorization code not provided")

    # 1. Authorization Code로 Access Token 및 ID Token 요청
    client_secret = generate_apple_client_secret()

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://appleid.apple.com/auth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": settings.APPLE_CLIENT_ID,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.APPLE_REDIRECT_URI,
            },
        )

    if token_response.status_code != 200:
        logger.error(f"Apple token error: {token_response.text}")
        raise HttpError(
            token_response.status_code, f"Apple 토큰 발급 실패: {token_response.text}"
        )

    token_data = token_response.json()
    id_token = token_data.get("id_token")
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    if not id_token:
        raise HttpError(400, "ID token not provided by Apple")

    # 2. ID Token 디코드 (검증 없이 - 이미 Apple에서 받은 것이므로 신뢰 가능)
    try:
        # 프로덕션에서는 Apple 공개 키로 검증하는 것이 좋지만,
        # 직접 Apple에서 받은 토큰이므로 검증 생략 가능
        decoded_token = jwt.decode(id_token, options={"verify_signature": False})
    except Exception as e:
        logger.error(f"Failed to decode Apple ID token: {e}")
        raise HttpError(400, "Invalid Apple ID token")

    # 3. 사용자 정보 추출
    apple_user_id = decoded_token.get("sub")  # Apple User ID
    email = decoded_token.get("email")
    email_verified = decoded_token.get("email_verified", False)

    if not apple_user_id:
        raise HttpError(400, "Apple User ID not found in token")

    # 첫 로그인 시 제공되는 사용자 정보 파싱
    user_name = None
    if user:
        import json

        try:
            user_data = json.loads(user) if isinstance(user, str) else user
            name_data = user_data.get("name", {})
            first_name = name_data.get("firstName", "")
            last_name = name_data.get("lastName", "")
            user_name = f"{last_name}{first_name}".strip()
        except Exception as e:
            logger.warning(f"Failed to parse Apple user data: {e}")

    # 세션에 Apple access_token 저장 (unlink 시 사용)
    if access_token:
        await sync_to_async(request.session.__setitem__)(
            "apple_access_token", access_token
        )
        await sync_to_async(setattr)(request.session, "modified", True)

    # 4. email로 가입된 일반 유저가 있는지 확인
    if email:
        exist_user = (
            await User.objects.exclude(login_method=User.LoginMethodChoices.TOSS)
            .filter(email=email, login_method=User.LoginMethodChoices.EMAIL)
            .aexists()
        )
        if exist_user:
            raise HttpError(
                400,
                f"{email}로 이미 가입된 계정이 있습니다. 이메일 로그인을 이용해주세요.",
            )

    # 5. 탈퇴한 유저 확인 (7일 제한 없이 먼저 조회)
    created = False
    try:
        withdrawn_user = await User.objects.aget(
            social_user_id=str(apple_user_id),
            login_method=User.LoginMethodChoices.APPLE,
            status=User.UserStatusChoice.WITHDRAW,
            withdraw_at__isnull=False,
        )

        # 탈퇴 후 7일 이내인지 확인
        seven_days_ago = timezone.now() - timezone.timedelta(days=7)
        if withdrawn_user.withdraw_at >= seven_days_ago:
            # 7일 이내: 재활성화
            logger.info(
                f"User with social_user_id {apple_user_id} found within 7 days, reactivating account."
            )
            user_obj = withdrawn_user
            # user_obj.status = User.UserStatusChoice.ACTIVE
            # user_obj.withdraw_at = None
            # user_obj.withdraw_reason = None
            user_obj.last_login = timezone.now()

            # 정보 업데이트
            if email:
                user_obj.social_email = email
            if user_name and not user_obj.name:
                user_obj.name = user_name

            await user_obj.asave()
        else:
            # 7일 초과: 기존 유저의 social_user_id와 social_email을 정리하고 새 계정 생성
            logger.info(
                f"User with social_user_id {apple_user_id} found but 7+ days withdrawn. Clearing old social data and creating new account."
            )

            # 기존 탈퇴 유저의 social_user_id와 social_email을 null로 변경하여 충돌 방지
            withdrawn_user.social_user_id = None
            withdrawn_user.social_email = None
            await withdrawn_user.asave()

            # 새 유저 생성
            @sync_to_async
            def create_apple_user():
                unique_username = f"apple-{email or apple_user_id}-{uuid.uuid4()}"

                user = User.objects.create_user(
                    email=unique_username,
                    login_method=User.LoginMethodChoices.APPLE,
                    social_username=unique_username,
                    social_email=email,
                    social_user_id=str(apple_user_id),
                    name=user_name,
                    status=User.UserStatusChoice.ACTIVE,
                    type=User.UserTypeChoices.MEMBER,
                    last_login=timezone.now(),
                )
                user.set_unusable_password()
                user.save()
                return user

            user_obj = await create_apple_user()
            created = True
            logger.info(f"New user created after 7+ days withdrawal: {apple_user_id}")

    except User.DoesNotExist:
        # 6. 기존 Apple 유저 조회 또는 신규 생성
        try:
            user_obj = await User.objects.aget(
                social_user_id=str(apple_user_id),
                login_method=User.LoginMethodChoices.APPLE,
            )

            # 기존 유저 정보 업데이트
            user_obj.last_login = timezone.now()
            if email:
                user_obj.social_email = email
            if user_name and not user_obj.name:
                user_obj.name = user_name

            await user_obj.asave()

            logger.info(f"Existing user {apple_user_id} logged in")

        except User.DoesNotExist:
            # 신규 유저 생성
            @sync_to_async
            def create_apple_user():
                unique_username = f"apple-{email or apple_user_id}-{uuid.uuid4()}"

                user = User.objects.create_user(
                    email=unique_username,
                    login_method=User.LoginMethodChoices.APPLE,
                    social_username=unique_username,
                    social_email=email,
                    social_user_id=str(apple_user_id),
                    name=user_name,
                    status=User.UserStatusChoice.ACTIVE,
                    type=User.UserTypeChoices.MEMBER,
                    last_login=timezone.now(),
                )
                user.set_unusable_password()
                user.save()
                return user

            user_obj = await create_apple_user()
            created = True

            logger.info(f"New user created with social_user_id {apple_user_id}")

    # 7. JWT 토큰 발급
    jwt_access, access_exp = utils.get_access_token(
        {"user_id": user_obj.id, "env": settings.DJANGO_ENV_NAME}
    )
    jwt_refresh, refresh_exp = utils.get_refresh_token()

    # 8. JWT 저장
    await Jwt.objects.acreate(
        user_id=user_obj.id,
        access=jwt_access,
        refresh=jwt_refresh,
    )

    response = JsonResponse(
        {
            "access": jwt_access,
            "refresh": jwt_refresh,
            "status": user_obj.status,
            "user_type": user_obj.type,
            "user_email": email,
            "user_id": user_obj.id,
        }
    )

    # 9. 쿠키 설정
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


@router.get(
    "/logout",
    summary="[C] 애플 로그아웃",
    description="애플 로그아웃 처리 (백엔드 JWT 삭제)",
)
async def apple_logout(request):
    """
    Apple 로그아웃 처리
    Note: Apple은 별도의 로그아웃 API를 제공하지 않으므로,
    클라이언트 측에서 세션 정리 후 백엔드 JWT만 삭제
    """
    try:
        # Authorization 헤더에서 토큰 추출
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            access_token = auth_header.replace("Bearer ", "")

            # JWT 삭제
            deleted = await Jwt.objects.filter(access=access_token).adelete()

            if deleted[0] > 0:
                logger.info(f"JWT deleted for Apple logout")

        # 세션에서 Apple access token 삭제
        try:
            await sync_to_async(request.session.__delitem__)("apple_access_token")
        except KeyError:
            pass

        response = JsonResponse({"message": "로그아웃 되었습니다."})
        response.delete_cookie("access")
        response.delete_cookie("refresh")

        return response

    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HttpError(500, "로그아웃 처리 중 오류가 발생했습니다.")


@router.post(
    "/unlink",
    summary="[C] 애플 계정 연결 해제",
    description="애플 계정 연결 해제 및 회원 탈퇴 처리",
    auth=jwt_auth,
)
async def apple_unlink(request, withdraw_reason: Optional[str] = None):
    """
    Apple 계정 연결 해제 및 회원 탈퇴 처리

    Note: Apple은 연결 해제 시 Apple 서버에 토큰 무효화를 요청할 수 있으나 선택사항
    """
    user = request.auth
    if not user:
        raise HttpError(401, "인증이 필요합니다.")

    if user.login_method != User.LoginMethodChoices.APPLE:
        raise HttpError(400, "Apple 로그인 유저만 연결 해제할 수 있습니다.")

    # Apple 서버에 토큰 무효화 요청 (best effort - 실패해도 계속 진행)
    try:
        apple_access_token = await sync_to_async(request.session.get)(
            "apple_access_token"
        )
        if apple_access_token:
            client_secret = generate_apple_client_secret()

            async with httpx.AsyncClient() as client:
                revoke_response = await client.post(
                    "https://appleid.apple.com/auth/revoke",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "client_id": settings.APPLE_CLIENT_ID,
                        "client_secret": client_secret,
                        "token": apple_access_token,
                        "token_type_hint": "access_token",
                    },
                )

                if revoke_response.status_code == 200:
                    logger.info(f"Apple token revoked for user {user.social_user_id}")
                else:
                    logger.warning(
                        f"Failed to revoke Apple token: {revoke_response.text}"
                    )
    except Exception as e:
        logger.warning(f"Error revoking Apple token: {e}")

    # 사용자 탈퇴 처리 (즉시 처리)
    user.status = User.UserStatusChoice.WITHDRAW
    user.withdraw_at = timezone.now()
    user.withdraw_reason = (
        f"Apple 계정 연결 해제 - {withdraw_reason}"
        if withdraw_reason
        else "Apple 계정 연결 해제"
    )
    await user.asave()
    await invalidate_auth_cache(user.id)

    # 해당 유저의 모든 JWT 삭제
    await Jwt.objects.filter(user=user).adelete()

    # 세션 정리
    await sync_to_async(request.session.pop)("apple_access_token", None)

    logger.info(f"User {user.social_user_id} Apple account unlinked")

    json_response = JsonResponse({"message": "Apple 계정 연결이 해제되었습니다."})
    json_response.delete_cookie("access")
    json_response.delete_cookie("refresh")

    return json_response
