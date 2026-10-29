from ninja import Router
from user import schema, utils
from user.toss_utils import (
    generate_access_token,
    refresh_access_token,
    get_user_info,
    decrypt_all_user_data,
    revoke_access_by_token,
    revoke_access_by_user_key,
    TossLoginError,
)
from ninja.errors import HttpError
from api.security import invalidate_auth_cache, jwt_auth
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from user.models import Jwt
from django.conf import settings
import base64
from asgiref.sync import sync_to_async
from django.db import transaction
import uuid
from datetime import datetime
import logging

logger = logging.getLogger("django")


User = get_user_model()


router = Router(
    tags=["Toss API"],
)


# 토스 로그인 API
@router.post(
    "/login",
    summary="[C] 토스 로그인",
    description="토스 인가 코드로 로그인합니다.",
    response=schema.TossLoginResponseSchema,
)
async def toss_login_api(request, data: schema.TossLoginRequestSchema):
    """
    토스 인가 코드를 받아 AccessToken을 발급받고,
    사용자 정보를 조회하여 회원가입 또는 로그인 처리합니다.
    """
    try:
        # 1. 토스 AccessToken 발급
        token_data = await generate_access_token(data.authorizationCode, data.referrer)
        toss_access_token = token_data["accessToken"]
        toss_refresh_token = token_data["refreshToken"]

        # 2. 사용자 정보 조회
        user_info = await get_user_info(toss_access_token)

        # 3. 개인정보 복호화
        decrypted_info = decrypt_all_user_data(user_info)

        toss_user_key = decrypted_info["userKey"]

        # 4. 탈퇴한 유저 확인 (7일 제한 없이 먼저 조회)
        try:
            withdrawn_user = await User.objects.aget(
                toss_user_key=toss_user_key,
                status=User.UserStatusChoice.WITHDRAW,
                withdraw_at__isnull=False,
            )

            # 탈퇴 후 7일 이내인지 확인
            seven_days_ago = timezone.now() - timezone.timedelta(days=7)
            if withdrawn_user.withdraw_at >= seven_days_ago:
                # 7일 이내: 재활성화
                logger.info(
                    f"User with toss_user_key {toss_user_key} found within 7 days, reactivating account."
                )
                user = withdrawn_user
                user.status = User.UserStatusChoice.ACTIVE
                user.withdraw_at = None
                user.withdraw_reason = None

                # 기존 유저 정보 업데이트
                user.toss_access_token = toss_access_token
                user.toss_refresh_token = toss_refresh_token
                user.name = decrypted_info.get("name") or user.name
                user.phone_number = decrypted_info.get("phone") or user.phone_number

                # 생년월일 업데이트
                birthday_str = decrypted_info.get("birthday")
                if birthday_str:
                    try:
                        user.birth_date = datetime.strptime(
                            birthday_str, "%Y%m%d"
                        ).date()
                    except ValueError:
                        pass

                user.toss_ci = decrypted_info.get("ci") or user.toss_ci

                # 성별 매핑
                gender_map = {
                    "MALE": User.UserTypeChoices.MEMBER,
                    "FEMALE": User.UserTypeChoices.MEMBER,
                }
                toss_gender = decrypted_info.get("gender")
                if toss_gender in gender_map:
                    user.type = gender_map[toss_gender]

                user.email = decrypted_info.get("email") or user.email
                user.last_login = timezone.now()
                await user.asave()
            else:
                # 7일 초과: 기존 유저의 toss_user_key를 정리하고 새 계정 생성
                logger.info(
                    f"User with toss_user_key {toss_user_key} found but 7+ days withdrawn. Clearing old toss_user_key and creating new account."
                )

                # 기존 탈퇴 유저의 toss_user_key를 null로 변경하여 충돌 방지
                withdrawn_user.toss_user_key = None
                await withdrawn_user.asave()

                # 새 유저 생성
                birth_date = None
                birthday_str = decrypted_info.get("birthday")
                if birthday_str:
                    try:
                        birth_date = datetime.strptime(birthday_str, "%Y%m%d").date()
                    except ValueError:
                        pass

                gender_map = {
                    "MALE": User.UserTypeChoices.MEMBER,
                    "FEMALE": User.UserTypeChoices.MEMBER,
                }
                toss_gender = decrypted_info.get("gender")
                gender = gender_map.get(toss_gender, User.UserTypeChoices.MEMBER)

                email = decrypted_info.get("email")
                if not email:
                    email = f"toss_{toss_user_key}@koc-erp.temp"

                @sync_to_async
                def create_social_user():
                    unique_username = f"toss-{toss_user_key}-{uuid.uuid4()}"
                    with transaction.atomic():
                        user = User.objects.create_user(
                            email=unique_username,
                            toss_user_key=toss_user_key,
                            toss_access_token=toss_access_token,
                            toss_refresh_token=toss_refresh_token,
                            toss_ci=decrypted_info.get("ci"),
                            name=decrypted_info.get("name", ""),
                            phone_number=decrypted_info.get("phone", ""),
                            birth_date=birth_date,
                            type=gender,
                            login_method=User.LoginMethodChoices.TOSS,
                            social_username=f"toss_{toss_user_key}",
                            social_email=email,
                            status=User.UserStatusChoice.ACTIVE,
                            last_login=timezone.now(),
                        )
                        user.set_unusable_password()
                        user.save()
                        return user

                user = await create_social_user()
                logger.info(
                    f"New user created after 7+ days withdrawal: {toss_user_key}"
                )

        except User.DoesNotExist:
            # 5. 기존 유저 조회 또는 생성
            try:
                user = await User.objects.aget(toss_user_key=toss_user_key)

                # 기존 유저 정보 업데이트
                user.toss_access_token = toss_access_token
                user.toss_refresh_token = toss_refresh_token
                user.name = decrypted_info.get("name") or user.name
                user.phone_number = decrypted_info.get("phone") or user.phone_number

                # 생년월일 업데이트
                birthday_str = decrypted_info.get("birthday")
                if birthday_str:
                    try:
                        user.birth_date = datetime.strptime(
                            birthday_str, "%Y%m%d"
                        ).date()
                    except ValueError:
                        logger.warning(f"Invalid birthday format: {birthday_str}")
                        pass  # 잘못된 형식은 무시

                user.toss_ci = decrypted_info.get("ci") or user.toss_ci

                # 성별 매핑 (UserTypeChoices 사용)
                gender_map = {
                    "MALE": User.UserTypeChoices.MEMBER,
                    "FEMALE": User.UserTypeChoices.MEMBER,
                }
                toss_gender = decrypted_info.get("gender")
                if toss_gender in gender_map:
                    user.type = gender_map[toss_gender]

                user.email = decrypted_info.get("email") or user.email
                user.last_login = timezone.now()

                await user.asave()

            except User.DoesNotExist:
                # 새 유저 생성
                birth_date = None
                birthday_str = decrypted_info.get("birthday")
                if birthday_str:
                    try:
                        birth_date = datetime.strptime(birthday_str, "%Y%m%d").date()
                    except ValueError:
                        pass  # 잘못된 형식은 무시

                # 성별 매핑 (UserTypeChoices 사용)
                gender_map = {
                    "MALE": User.UserTypeChoices.MEMBER,
                    "FEMALE": User.UserTypeChoices.MEMBER,
                }
                toss_gender = decrypted_info.get("gender")
                gender = gender_map.get(toss_gender, User.UserTypeChoices.MEMBER)

                # 이메일이 없는 경우 임시 이메일 생성
                email = decrypted_info.get("email")
                if not email:
                    email = f"toss_{toss_user_key}@koc-erp.temp"

                @sync_to_async
                def create_social_user():
                    unique_username = f"toss-{toss_user_key}-{uuid.uuid4()}"
                    with transaction.atomic():
                        user = User.objects.create_user(
                            email=unique_username,
                            toss_user_key=toss_user_key,
                            toss_access_token=toss_access_token,
                            toss_refresh_token=toss_refresh_token,
                            toss_ci=decrypted_info.get("ci"),
                            name=decrypted_info.get("name", ""),
                            phone_number=decrypted_info.get("phone", ""),
                            birth_date=birth_date,
                            type=gender,
                            login_method=User.LoginMethodChoices.TOSS,
                            social_username=f"toss_{toss_user_key}",
                            social_email=email,
                            status=User.UserStatusChoice.ACTIVE,
                            last_login=timezone.now(),
                        )
                        user.set_unusable_password()
                        user.save()
                        return user

                user = await create_social_user()

        # 5. JWT 토큰 발급
        access, access_exp = utils.get_access_token(
            {"user_id": user.id, "env": settings.DJANGO_ENV_NAME}
        )
        refresh, refresh_exp = utils.get_refresh_token()

        await Jwt.objects.acreate(
            user_id=user.id,
            access=access,
            refresh=refresh,
        )

        # 6. 응답 데이터 생성
        response_dict = {
            "access": access,
            "refresh": refresh,
            "status": user.status,
            "user_id": user.id,
        }
        return response_dict

        # 7. 쿠키 설정을 위한 JsonResponse (선택사항)
        # response = JsonResponse(
        #     response_dict,
        # )
        # response = utils.set_cookie_jwt(
        #     response, access, refresh, access_exp, refresh_exp, reset=None, host=None
        # )

        # return response

    except TossLoginError as e:
        raise HttpError(400, str(e))
    except Exception as e:
        raise HttpError(500, f"토스 로그인 처리 중 오류가 발생했습니다: {str(e)}")


@router.post(
    "/verify",
    summary="[C] 토스 AccessToken 검증",
    description="토스 AccessToken이 유효한지 검증합니다.",
    response={
        200: None,
    },
    auth=jwt_auth,
)
async def verify_toss_token_api(request):
    """
    현재 로그인한 사용자의 토스 AccessToken이 유효한지 검증합니다.
    """
    user = request.auth

    if not user.toss_access_token:
        raise HttpError(400, "토스 로그인 정보가 없습니다.")

    try:
        # 토스 AccessToken 검증
        await get_user_info(user.toss_access_token)
        return 200, None

    except TossLoginError as e:
        raise HttpError(401, str(e))


@router.post(
    "/refresh",
    summary="[C] 토스 AccessToken 재발급",
    description="RefreshToken을 사용하여 토스 AccessToken을 재발급받습니다.",
    response=schema.TossRefreshTokenResponseSchema,
    auth=jwt_auth,
)
async def refresh_toss_token_api(request):
    """
    현재 로그인한 사용자의 RefreshToken으로 AccessToken을 재발급받습니다.
    """
    user = request.auth

    if not user.toss_refresh_token:
        raise HttpError(400, "토스 RefreshToken이 없습니다.")

    try:
        # 토스 AccessToken 재발급
        token_data = await refresh_access_token(user.toss_refresh_token)

        # 사용자 정보에 새 토큰 저장
        user.toss_access_token = token_data["accessToken"]
        user.toss_refresh_token = token_data["refreshToken"]
        await user.asave()

        return {
            "tokenType": token_data["tokenType"],
            "accessToken": token_data["accessToken"],
            "refreshToken": token_data["refreshToken"],
            "expiresIn": token_data["expiresIn"],
            "scope": token_data["scope"],
        }

    except TossLoginError as e:
        raise HttpError(400, str(e))
    except Exception as e:
        raise HttpError(500, f"토스 토큰 재발급 중 오류가 발생했습니다: {str(e)}")


@router.get(
    "/user-info",
    summary="[C] 토스 사용자 정보 조회",
    description="현재 로그인한 사용자의 토스 정보를 조회합니다.",
    response=schema.TossUserInfoSchema,
    auth=jwt_auth,
)
async def get_toss_user_info_api(request):
    """
    현재 로그인한 사용자의 토스 정보를 조회합니다.
    """
    user = request.auth

    if not user.toss_access_token:
        raise HttpError(400, "토스 로그인 정보가 없습니다.")

    try:
        # 토스 사용자 정보 조회
        user_info = await get_user_info(user.toss_access_token)

        # 개인정보 복호화
        decrypted_info = decrypt_all_user_data(user_info)

        return decrypted_info

    except TossLoginError as e:
        raise HttpError(400, str(e))


@router.post(
    "/revoke",
    summary="[C] 토스 로그인 연결 끊기",
    description="토스 로그인 연결을 끊고 회원 탈퇴 처리합니다.",
    auth=jwt_auth,
)
async def revoke_toss_login_api(request, data: schema.TossRevokeRequestSchema = None):
    """
    토스 로그인 연결을 끊고 회원 탈퇴 처리합니다.
    userKey가 제공되면 해당 키로 연결을 끊고,
    제공되지 않으면 AccessToken으로 연결을 끊습니다.
    """
    user = request.auth

    if not user.toss_access_token:
        raise HttpError(400, "토스 로그인 정보가 없습니다.")

    try:
        if data and data.userKey:
            # userKey로 연결 끊기
            result = await revoke_access_by_user_key(
                user.toss_access_token, data.userKey
            )
        else:
            # AccessToken으로 연결 끊기
            result = await revoke_access_by_token(user.toss_access_token)

        # 토스 정보 초기화 및 탈퇴 처리
        user.toss_access_token = None
        user.toss_refresh_token = None
        user.status = User.UserStatusChoice.WITHDRAW
        user.withdraw_at = timezone.now()
        user.withdraw_reason = "토스 연결 해제"
        await user.asave()
        await invalidate_auth_cache(user.id)

        # 해당 유저의 모든 JWT 삭제
        await Jwt.objects.filter(user=user).adelete()

        logger.info(
            f"User {user.id} (toss_user_key: {user.toss_user_key}) revoked Toss connection and withdrawn"
        )

        return {
            "message": "토스 로그인 연결이 끊어지고 회원 탈퇴되었습니다.",
            "result": result,
        }

    except TossLoginError as e:
        raise HttpError(400, str(e))


@router.post(
    "/callback",
    summary="[Toss] 연결 끊기 콜백",
    description="토스에서 사용자가 연결을 끊었을 때 호출되는 콜백입니다.",
)
async def toss_revoke_callback_api(request, data: schema.TossCallbackSchema):

    # Basic Auth 검증
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        raise HttpError(401, "Basic Auth 헤더가 필요합니다.")

    try:
        # Basic Auth 헤더에서 인증 정보 추출
        encoded_credentials = auth_header.replace("Basic ", "")
        decoded_credentials = base64.b64decode(encoded_credentials).decode("utf-8")

        # 인증 정보 검증 (토스 콘솔에서 설정한 값과 비교)
        expected_auth = settings.TOSS_CALLBACK_BASIC_AUTH
        if decoded_credentials != expected_auth:
            raise HttpError(401, "인증 실패: 잘못된 Basic Auth 정보입니다.")
    except Exception as e:
        raise HttpError(401, f"인증 실패: {str(e)}")

    try:
        user = await User.objects.aget(toss_user_key=data.userKey)

        # 이미 탈퇴한 유저인지 확인
        if user.status == User.UserStatusChoice.WITHDRAW:
            logger.info(
                f"User {user.id} (toss_user_key: {data.userKey}) already withdrawn. Callback no-op."
            )
            return {"message": "User already withdrawn", "userKey": data.userKey}

        # 토스 정보 초기화 및 탈퇴 처리
        user.toss_access_token = None
        user.toss_refresh_token = None
        user.status = User.UserStatusChoice.WITHDRAW
        user.withdraw_at = timezone.now()
        user.withdraw_reason = user.withdraw_reason or "토스 회원 탈퇴"
        user.is_withdrawn = True

        await user.asave()
        await invalidate_auth_cache(user.id)

        # 해당 유저의 모든 JWT 삭제
        await Jwt.objects.filter(user=user).adelete()

        logger.info(
            f"User {user.id} (toss_user_key: {data.userKey}) withdrawn via Toss callback"
        )

        return {"message": "콜백 처리 완료", "userKey": data.userKey}

    except User.DoesNotExist:
        raise HttpError(404, "해당 토스 사용자를 찾을 수 없습니다.")
    except User.MultipleObjectsReturned:
        # 중복 데이터 문제 - 로깅 필요
        logger.error(f"중복된 토스 사용자 키: {data.userKey}")
        raise HttpError(500, "데이터 무결성 오류가 발생했습니다.")


@router.get(
    "/callback",
    summary="[Toss] 연결 끊기 콜백 (GET)",
    description="토스에서 사용자가 연결을 끊었을 때 호출되는 콜백입니다. (GET 방식)",
)
async def toss_revoke_callback_get_api(
    request, userKey: int = None, referrer: str = None
):
    callback_data = schema.TossCallbackSchema(userKey=userKey, referrer=referrer)
    return await toss_revoke_callback_api(request, callback_data)
