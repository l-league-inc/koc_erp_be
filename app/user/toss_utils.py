"""
토스 로그인 API 유틸리티 함수
"""

import base64
import logging
from typing import Dict, Optional, Tuple

import httpx
from Crypto.Cipher import AES
from django.conf import settings

logger = logging.getLogger(__name__)

# 토스 로그인 API BaseURL
TOSS_BASE_URL = "https://apps-in-toss-api.toss.im"


class TossLoginError(Exception):
    """토스 로그인 관련 에러"""

    pass


async def generate_access_token(
    authorization_code: str, referrer: str
) -> Dict[str, str]:
    """
    인가 코드로 AccessToken을 발급받습니다.

    Args:
        authorization_code: SDK로부터 받은 인가 코드
        referrer: SDK로부터 받은 referrer (sandbox 또는 DEFAULT)

    Returns:
        Dict with accessToken, refreshToken, scope, tokenType, expiresIn

    Raises:
        TossLoginError: 토큰 발급 실패 시
    """
    url = f"{TOSS_BASE_URL}/api-partner/v1/apps-in-toss/user/oauth2/generate-token"

    payload = {
        "authorizationCode": authorization_code,
        "referrer": referrer,
    }

    # mTLS 인증서 설정
    cert = None
    if hasattr(settings, "TOSS_CERT_PATH") and hasattr(settings, "TOSS_KEY_PATH"):
        cert = (settings.TOSS_CERT_PATH, settings.TOSS_KEY_PATH)

    async with httpx.AsyncClient(cert=cert, verify=True) as client:
        try:
            response = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("resultType") == "SUCCESS":
                    return data["success"]
                else:
                    error = data.get("error", {})
                    raise TossLoginError(
                        f"토큰 발급 실패: {error.get('errorCode', 'UNKNOWN')} - "
                        f"{error.get('reason', '알 수 없는 오류')}"
                    )
            else:
                error = response.json().get("error", "invalid_grant")
                raise TossLoginError(f"토큰 발급 실패: {error}")

        except httpx.RequestError as e:
            logger.error(f"토스 API 요청 실패: {e}")
            raise TossLoginError(f"토스 API 요청 실패: {str(e)}")


async def refresh_access_token(refresh_token: str) -> Dict[str, str]:
    """
    RefreshToken으로 AccessToken을 재발급받습니다.

    Args:
        refresh_token: 발급받은 RefreshToken

    Returns:
        Dict with accessToken, refreshToken, scope, tokenType, expiresIn

    Raises:
        TossLoginError: 토큰 재발급 실패 시
    """
    url = f"{TOSS_BASE_URL}/api-partner/v1/apps-in-toss/user/oauth2/refresh-token"

    payload = {"refreshToken": refresh_token}

    # mTLS 인증서 설정
    cert = None
    if hasattr(settings, "TOSS_CERT_PATH") and hasattr(settings, "TOSS_KEY_PATH"):
        cert = (settings.TOSS_CERT_PATH, settings.TOSS_KEY_PATH)

    async with httpx.AsyncClient(cert=cert, verify=True) as client:
        try:
            response = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("resultType") == "SUCCESS":
                    return data["success"]
                else:
                    error = data.get("error", {})
                    raise TossLoginError(
                        f"토큰 재발급 실패: {error.get('errorCode', 'UNKNOWN')} - "
                        f"{error.get('reason', '알 수 없는 오류')}"
                    )
            else:
                error = response.json().get("error", "invalid_grant")
                raise TossLoginError(f"토큰 재발급 실패: {error}")

        except httpx.RequestError as e:
            logger.error(f"토스 API 요청 실패: {e}")
            raise TossLoginError(f"토스 API 요청 실패: {str(e)}")


async def get_user_info(access_token: str) -> Dict:
    """
    AccessToken으로 사용자 정보를 조회합니다.

    Args:
        access_token: 발급받은 AccessToken

    Returns:
        Dict with userKey, scope, agreedTerms, name, phone, birthday, ci, di, gender, nationality, email
        (개인정보는 암호화된 상태)

    Raises:
        TossLoginError: 사용자 정보 조회 실패 시
    """
    url = f"{TOSS_BASE_URL}/api-partner/v1/apps-in-toss/user/oauth2/login-me"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # mTLS 인증서 설정
    cert = None
    if hasattr(settings, "TOSS_CERT_PATH") and hasattr(settings, "TOSS_KEY_PATH"):
        cert = (settings.TOSS_CERT_PATH, settings.TOSS_KEY_PATH)

    async with httpx.AsyncClient(cert=cert, verify=True) as client:
        try:
            response = await client.get(url, headers=headers, timeout=10.0)

            if response.status_code == 200:
                data = response.json()
                if data.get("resultType") == "SUCCESS":
                    return data["success"]
                else:
                    error = data.get("error", {})
                    raise TossLoginError(
                        f"사용자 정보 조회 실패: {error.get('errorCode', 'UNKNOWN')} - "
                        f"{error.get('reason', '알 수 없는 오류')}"
                    )
            else:
                error = response.json().get("error", "invalid_grant")
                raise TossLoginError(f"사용자 정보 조회 실패: {error}")

        except httpx.RequestError as e:
            logger.error(f"토스 API 요청 실패: {e}")
            raise TossLoginError(f"토스 API 요청 실패: {str(e)}")


def decrypt_user_data(encrypted_text: str) -> str:
    """
    AES-256-GCM 방식으로 암호화된 사용자 정보를 복호화합니다.

    Args:
        encrypted_text: Base64로 인코딩된 암호화된 텍스트

    Returns:
        복호화된 텍스트

    Raises:
        TossLoginError: 복호화 실패 시
    """
    try:
        IV_LENGTH = 12
        TAG_LENGTH = 16

        # Base64 디코딩
        decoded = base64.b64decode(encrypted_text)

        # 복호화 키 (Base64로 인코딩된 키)
        key_byte_array = base64.b64decode(settings.TOSS_DECRYPT_KEY)

        # IV 추출
        iv = decoded[:IV_LENGTH]

        # 암호문과 태그 추출
        ciphertext_and_tag = decoded[IV_LENGTH:]
        ciphertext = ciphertext_and_tag[:-TAG_LENGTH]
        tag = ciphertext_and_tag[-TAG_LENGTH:]

        # AES GCM 복호화
        cipher = AES.new(key_byte_array, AES.MODE_GCM, nonce=iv)
        cipher.update(settings.TOSS_AAD.encode())

        decrypted = cipher.decrypt_and_verify(ciphertext, tag)

        return decrypted.decode("utf-8")

    except Exception as e:
        logger.error(f"복호화 실패: {e}")
        raise TossLoginError(f"복호화 실패: {str(e)}")


async def revoke_access_by_token(access_token: str) -> Dict:
    """
    AccessToken으로 로그인 연결을 끊습니다.

    Args:
        access_token: 발급받은 AccessToken

    Returns:
        성공 메시지

    Raises:
        TossLoginError: 연결 끊기 실패 시
    """
    url = f"{TOSS_BASE_URL}/api-partner/v1/apps-in-toss/user/oauth2/access/remove-by-access-token"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # mTLS 인증서 설정
    cert = None
    if hasattr(settings, "TOSS_CERT_PATH") and hasattr(settings, "TOSS_KEY_PATH"):
        cert = (settings.TOSS_CERT_PATH, settings.TOSS_KEY_PATH)

    async with httpx.AsyncClient(cert=cert, verify=True) as client:
        try:
            response = await client.post(url, headers=headers, timeout=10.0)

            if response.status_code == 200:
                data = response.json()
                if data.get("resultType") == "SUCCESS":
                    return data["success"]
                else:
                    error = data.get("error", {})
                    raise TossLoginError(
                        f"연결 끊기 실패: {error.get('errorCode', 'UNKNOWN')} - "
                        f"{error.get('reason', '알 수 없는 오류')}"
                    )
            else:
                raise TossLoginError(
                    f"연결 끊기 실패: 상태 코드 {response.status_code}"
                )

        except httpx.RequestError as e:
            logger.error(f"토스 API 요청 실패: {e}")
            raise TossLoginError(f"토스 API 요청 실패: {str(e)}")


async def revoke_access_by_user_key(access_token: str, user_key: int) -> Dict:
    """
    userKey로 로그인 연결을 끊습니다.

    Args:
        access_token: 발급받은 AccessToken
        user_key: 토스 사용자 키

    Returns:
        성공 메시지 with userKey

    Raises:
        TossLoginError: 연결 끊기 실패 시
    """
    url = f"{TOSS_BASE_URL}/api-partner/v1/apps-in-toss/user/oauth2/access/remove-by-user-key"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {"userKey": user_key}

    # mTLS 인증서 설정
    cert = None
    if hasattr(settings, "TOSS_CERT_PATH") and hasattr(settings, "TOSS_KEY_PATH"):
        cert = (settings.TOSS_CERT_PATH, settings.TOSS_KEY_PATH)

    async with httpx.AsyncClient(cert=cert, verify=True) as client:
        try:
            response = await client.post(
                url, json=payload, headers=headers, timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("resultType") == "SUCCESS":
                    return data["success"]
                else:
                    error = data.get("error", {})
                    raise TossLoginError(
                        f"연결 끊기 실패: {error.get('errorCode', 'UNKNOWN')} - "
                        f"{error.get('reason', '알 수 없는 오류')}"
                    )
            else:
                raise TossLoginError(
                    f"연결 끊기 실패: 상태 코드 {response.status_code}"
                )

        except httpx.RequestError as e:
            logger.error(f"토스 API 요청 실패: {e}")
            raise TossLoginError(f"토스 API 요청 실패: {str(e)}")


def decrypt_all_user_data(encrypted_data: Dict) -> Dict:
    """
    사용자 정보의 모든 암호화된 필드를 복호화합니다.

    Args:
        encrypted_data: 암호화된 사용자 정보

    Returns:
        복호화된 사용자 정보
    """
    decrypted_data = encrypted_data.copy()

    # 복호화가 필요한 필드들
    encrypted_fields = [
        "name",
        "phone",
        "birthday",
        "ci",
        "gender",
        "nationality",
        "email",
    ]

    for field in encrypted_fields:
        if field in decrypted_data and decrypted_data[field]:
            try:
                decrypted_data[field] = decrypt_user_data(decrypted_data[field])
            except TossLoginError as e:
                logger.warning(f"{field} 복호화 실패: {e}")
                decrypted_data[field] = None

    return decrypted_data
