from api.docs import MixedDocs
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import include, path
from django.utils import timezone
from django.views.decorators.http import require_GET
from ninja import NinjaAPI
from notice.api import router as notice_router
from notification.api import router as notification_router
from user.api import router as user_router
from user.appleapi import router as apple_router
from user.appleapi_v2 import router as apple_v2_router
from user.kakaoapi import router as kakao_router
from user.kakaoapi_v2 import router as kakao_v2_router
from user.tossapi import router as toss_router
from verification.api import router as verify_router
from workspace.api import router as workspace_router

from config.api import router as aws_router
from mcp_server.oauth_metadata import metadata_body
from mcp_server.oauth_views import (
    oauth_authorization_server,
    oauth_apple_callback,
    oauth_apple_start,
    oauth_authorize,
    oauth_kakao_callback,
    oauth_kakao_start,
    oauth_register,
    oauth_token,
)

base_api = NinjaAPI(
    title="KOC ERP API",
    version=settings.SERVER_VERSION,
    docs=MixedDocs(),
    docs_decorator=staff_member_required,
    docs_url="/<engine>/",
)


@base_api.get("api/health-checker", include_in_schema=False)
def home_handler(request):
    return render(
        request,
        "index.html",
        {
            "service_name": settings.SERVICE_NAME,
            "server_version": settings.SERVER_VERSION,
            "server_time": timezone.make_aware(timezone.now()).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        },
    )


@require_GET
def oauth_protected_resource(request: HttpRequest) -> HttpResponse:
    return HttpResponse(metadata_body(), content_type="application/json")


@require_GET
def openai_apps_challenge(request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        settings.OPENAI_APPS_CHALLENGE_TOKEN,
        content_type="text/plain; charset=utf-8",
    )


base_api.add_router("api/v1/aws", aws_router)
base_api.add_router("api/v1/auth", user_router)
base_api.add_router("api/v1/kakao", kakao_router)
base_api.add_router("api/v2/kakao", kakao_v2_router)
base_api.add_router("api/v1/apple", apple_router)
base_api.add_router("api/v2/apple", apple_v2_router)
base_api.add_router("api/v1/toss", toss_router)
base_api.add_router("api/v1/notice", notice_router)
base_api.add_router("api/v1/verify", verify_router)
base_api.add_router("api/v1/notification", notification_router)
base_api.add_router("api/v1/workspace", workspace_router)

urlpatterns = [
    path(
        ".well-known/oauth-protected-resource",
        oauth_protected_resource,
        name="oauth-protected-resource",
    ),
    path(
        ".well-known/oauth-protected-resource/mcp",
        oauth_protected_resource,
        name="oauth-protected-resource-mcp",
    ),
    path(
        ".well-known/openai-apps-challenge",
        openai_apps_challenge,
        name="openai-apps-challenge",
    ),
    path(
        ".well-known/oauth-authorization-server",
        oauth_authorization_server,
        name="oauth-authorization-server",
    ),
    path("oauth/authorize", oauth_authorize, name="oauth-authorize"),
    path("oauth/kakao/start", oauth_kakao_start, name="oauth-kakao-start"),
    path("oauth/kakao/callback", oauth_kakao_callback, name="oauth-kakao-callback"),
    path("oauth/apple/start", oauth_apple_start, name="oauth-apple-start"),
    path("oauth/apple/callback", oauth_apple_callback, name="oauth-apple-callback"),
    path("oauth/register", oauth_register, name="oauth-register"),
    path("oauth/token", oauth_token, name="oauth-token"),
    path("wiki/", include("wiki.urls")),
    path("admin/", admin.site.urls),
    path("", base_api.urls),
]
