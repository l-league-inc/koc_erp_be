from django.db import models

from common.models import CommonModel


class OAuthClient(CommonModel):
    """ChatGPT 플러그인 등록이 동적 등록으로 만든 OAuth 클라이언트입니다."""

    client_id = models.CharField(max_length=128, help_text="OAuth client_id")
    client_secret = models.CharField(
        max_length=255, blank=True, default="", help_text="OAuth client_secret"
    )
    token_endpoint_auth_method = models.CharField(
        max_length=32, default="none", help_text="토큰 엔드포인트 인증 방식"
    )
    redirect_uris = models.JSONField(default=list, help_text="허용된 리다이렉트 URI")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["client_id"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_mcp_oauth_client_id",
            )
        ]


class OAuthAuthorizationCode(CommonModel):
    """ChatGPT에 넘기기 전 5분간 유효한 일회용 인가 코드입니다."""

    code_hash = models.CharField(max_length=64, help_text="인가 코드 SHA-256")
    user_id = models.PositiveBigIntegerField(help_text="로그인한 사용자")
    client_id = models.TextField(help_text="OAuth client_id")
    redirect_uri = models.TextField(help_text="인가 요청 redirect_uri")
    code_challenge = models.CharField(max_length=128, help_text="PKCE S256 challenge")
    resource = models.TextField(blank=True, default="", help_text="OAuth resource")
    expires_at = models.DateTimeField(db_index=True, help_text="만료 시각")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["code_hash"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_mcp_oauth_code_hash",
            )
        ]


class OAuthSocialPending(CommonModel):
    """카카오·애플 콜백이 돌아올 때까지 보관하는 인가 요청입니다."""

    state_key = models.CharField(max_length=64, help_text="소셜 로그인 state")
    payload = models.JSONField(help_text="AuthorizeRequest")
    expires_at = models.DateTimeField(db_index=True, help_text="만료 시각")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["state_key"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_mcp_oauth_social_state",
            )
        ]
