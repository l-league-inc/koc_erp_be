from ninja import Router, Schema
from ninja.errors import HttpError
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from typing import Optional
from user.models import User, Jwt
from user import utils
from api.security import invalidate_auth_cache, jwt_auth
from asgiref.sync import sync_to_async
import logging
import httpx
import uuid
import jwt


logger = logging.getLogger("django")


router = Router(
    tags=["Apple V2"],
)


class AppleAuthSchema(Schema):
    identity_token: str
    user_info: dict = None  # Apple에서 첫 로그인 시에만 제공


@router.post(
    "/auth",
    summary="[C] 애플 로그인 인증",
    description="Flutter에서 받은 Apple identity token을 검증하고 JWT를 발급합니다.",
)
async def apple_auth(request, payload: AppleAuthSchema):
    """
    Flutter sign_in_with_apple에서 받은 identity_token으로 사용자 정보 검증 및 JWT 발급

    Flutter 클라이언트 예시:
    ```dart
    // 애플 로그인
    final credential = await SignInWithApple.getAppleIDCredential(
      scopes: [
        AppleIDAuthorizationScopes.email,
        AppleIDAuthorizationScopes.fullName,
      ],
    );

    // 백엔드로 identity_token 전송
    final response = await dio.post('/api/apple/auth',
      data: {
        'identity_token': credential.identityToken,
        'user_info': {
          'email': credential.email,
          'given_name': credential.givenName,
          'family_name': credential.familyName,
        }
      }
    );
    ```
    """
    identity_token = payload.identity_token
    user_info = payload.user_info or {}

    # 1. Apple identity token 검증 및 디코드
    try:
        # Apple의 공개 키를 가져와서 토큰 검증 (프로덕션에서는 필수)
        # 개발 환경에서는 검증 없이 디코드만 수행
        if settings.DJANGO_ENV_NAME == "local":
            # 로컬에서는 검증 없이 디코드
            decoded_token = jwt.decode(
                identity_token, options={"verify_signature": False}
            )
        else:
            # 프로덕션에서는 Apple 공개 키로 검증
            # Apple의 공개 키 가져오기
            async with httpx.AsyncClient() as client:
                keys_response = await client.get("https://appleid.apple.com/auth/keys")
                apple_keys = keys_response.json()["keys"]

            # JWT 헤더에서 kid 추출
            header = jwt.get_unverified_header(identity_token)
            kid = header.get("kid")

            # 해당 kid의 공개 키 찾기
            public_key = None
            for key in apple_keys:
                if key["kid"] == kid:
                    # JWK를 PEM 형식으로 변환
                    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                    break

            if not public_key:
                raise HttpError(401, "유효하지 않은 Apple 토큰입니다.")

            # 토큰 검증 및 디코드 (issuer 검증만 수행)
            decoded_token = jwt.decode(
                identity_token,
                public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},  # audience 검증 비활성화
                issuer="https://appleid.apple.com",
            )

    except jwt.ExpiredSignatureError:
        logger.error("Apple token expired")
        raise HttpError(401, "만료된 Apple 토큰입니다.")
    except jwt.InvalidTokenError as e:
        logger.error(f"Invalid Apple token: {e}")
        raise HttpError(401, "유효하지 않은 Apple 토큰입니다.")
    except HttpError:
        raise
    except Exception as e:
        logger.error(f"Apple token verification error: {e}")
        raise HttpError(500, "Apple 토큰 검증 중 오류가 발생했습니다.")

    # 2. 토큰에서 사용자 정보 추출
    apple_user_id = decoded_token.get("sub")
    if not apple_user_id:
        raise HttpError(400, "Apple 사용자 ID를 가져올 수 없습니다.")

    # 이메일은 토큰 또는 user_info에서 가져오기
    social_email = decoded_token.get("email") or user_info.get("email")

    # 이름 정보 (첫 로그인 시에만 제공됨)
    given_name = user_info.get("given_name")
    family_name = user_info.get("family_name")
    full_name = None
    if given_name or family_name:
        full_name = f"{family_name or ''}{given_name or ''}".strip()

    # 3. email로 가입된 일반 유저가 있는지 확인
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

    # 4. 탈퇴한 유저 확인 (7일 제한 없이 먼저 조회)
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
            user = withdrawn_user
            # user.status = User.UserStatusChoice.ACTIVE
            # user.withdraw_at = None
            # user.withdraw_reason = None
            user.last_login = timezone.now()

            # 정보 업데이트
            if social_email:
                user.social_email = social_email
            if full_name:
                user.name = full_name

            await user.asave()
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
                unique_username = (
                    f"apple-{social_email or apple_user_id}-{uuid.uuid4()}"
                )

                user = User.objects.create_user(
                    email=unique_username,
                    login_method=User.LoginMethodChoices.APPLE,
                    social_username=unique_username,
                    social_email=social_email,
                    social_user_id=str(apple_user_id),
                    name=full_name,
                    status=User.UserStatusChoice.ACTIVE,
                    type=User.UserTypeChoices.MEMBER,
                    last_login=timezone.now(),
                )
                user.set_unusable_password()
                user.save()
                return user

            user = await create_apple_user()
            created = True
            logger.info(f"New user created after 7+ days withdrawal: {apple_user_id}")

    except User.DoesNotExist:
        # 5. 기존 Apple 유저 조회 또는 신규 생성
        try:
            user = await User.objects.aget(
                social_user_id=str(apple_user_id),
                login_method=User.LoginMethodChoices.APPLE,
            )

            # 기존 유저 정보 업데이트
            user.last_login = timezone.now()
            if social_email:
                user.social_email = social_email
            if full_name and not user.name:
                user.name = full_name

            await user.asave()

            logger.info(f"Existing user {apple_user_id} logged in")

        except User.DoesNotExist:
            # 신규 유저 생성
            @sync_to_async
            def create_apple_user():
                unique_username = (
                    f"apple-{social_email or apple_user_id}-{uuid.uuid4()}"
                )

                user = User.objects.create_user(
                    email=unique_username,
                    login_method=User.LoginMethodChoices.APPLE,
                    social_username=unique_username,
                    social_email=social_email,
                    social_user_id=str(apple_user_id),
                    name=full_name,
                    status=User.UserStatusChoice.ACTIVE,
                    type=User.UserTypeChoices.MEMBER,  # 기본값
                    last_login=timezone.now(),
                )
                user.set_unusable_password()
                user.save()
                return user

            user = await create_apple_user()
            created = True

            logger.info(f"New user created with social_user_id {apple_user_id}")

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
    summary="[C] 애플 로그아웃",
    description="애플 로그아웃 처리 (Flutter에서 로그아웃 후 백엔드 JWT 삭제)",
)
async def apple_logout(request):
    """
    Flutter에서 애플 로그아웃 후 백엔드 JWT 삭제

    Flutter 클라이언트 예시:
    ```dart
    // 애플 로그아웃 (클라이언트 측에서 세션 정리)

    // 백엔드 JWT 삭제
    await dio.post('/api/apple/logout');
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
                logger.info(f"JWT deleted for Apple logout")

        response = JsonResponse({"message": "로그아웃 되었습니다."})
        response.delete_cookie("access")
        response.delete_cookie("refresh")

        return response

    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HttpError(500, "로그아웃 처리 중 오류가 발생했습니다.")


@router.post(
    "/revoke",
    summary="[C] 애플 계정 연결 해제",
    description="애플 계정 연결 해제 및 회원 탈퇴 처리",
    auth=jwt_auth,
)
async def apple_revoke(request, withdraw_reason: Optional[str] = None):
    """
    애플 계정 연결 해제 및 회원 탈퇴 처리

    Flutter 클라이언트 예시:
    ```dart
    // 백엔드 회원 탈퇴 처리 (서비스 JWT 포함)
    await dio.post('/api/apple/revoke');
    ```
    """
    user = request.auth
    if not user:
        raise HttpError(401, "인증이 필요합니다.")

    if user.login_method != User.LoginMethodChoices.APPLE:
        raise HttpError(400, "Apple 로그인 유저만 연결 해제할 수 있습니다.")

    try:
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

        logger.info(f"User {user.social_user_id} Apple account revoked")

        json_response = JsonResponse({"message": "Apple 계정 연결이 해제되었습니다."})
        json_response.delete_cookie("access")
        json_response.delete_cookie("refresh")

        return json_response

    except HttpError:
        raise
    except Exception as e:
        logger.error(f"Apple revoke error: {e}")
        raise HttpError(500, "계정 연결 해제 처리 중 오류가 발생했습니다.")
