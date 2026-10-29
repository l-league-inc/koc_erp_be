from typing import Any

import json

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from mcp_server.oauth_server import (
    AUTHORIZE_FIELDS,
    OAuthClientError,
    OAuthRedirectError,
    RegistrationError,
    authenticate_oauth_user,
    authorization_server_metadata,
    client_can_use_redirect,
    error_redirect_url,
    exchange_authorization_code,
    exchange_refresh_token,
    issue_authorization_code,
    parse_authorize_request,
    register_oauth_client,
    success_redirect_url,
)
from mcp_server.social_login import (
    SocialLoginError,
    apple_authorize_url,
    drop_pending,
    kakao_authorize_url,
    load_pending,
    login_with_apple_code,
    login_with_kakao_code,
    store_pending,
)


@require_GET
def oauth_authorization_server(request: HttpRequest) -> JsonResponse:
    return JsonResponse(authorization_server_metadata())


@require_http_methods(["GET", "POST"])
async def oauth_authorize(request: HttpRequest) -> HttpResponse:
    params = request.POST if request.method == "POST" else request.GET
    try:
        authorize_request = parse_authorize_request(params)
    except OAuthClientError as exc:
        return _login_page(request, {}, exc.description, status=400)
    except OAuthRedirectError as exc:
        redirect_uri = (params.get("redirect_uri") or "").strip()
        state = (params.get("state") or "").strip()
        return _redirect(
            error_redirect_url(redirect_uri, exc.error, exc.description, state)
        )

    if not await client_can_use_redirect(
        authorize_request.client_id, authorize_request.redirect_uri
    ):
        return _login_page(
            request, {}, "클라이언트 또는 리다이렉트 주소가 올바르지 않습니다.", status=400
        )

    if request.method == "GET":
        return _login_page(request, _hidden_fields(params), "")

    user, error = await authenticate_oauth_user(
        params.get("email") or "",
        params.get("password") or "",
    )
    if user is None:
        return _login_page(request, _hidden_fields(params), error)

    try:
        code = await issue_authorization_code(user.id, authorize_request)
    except OAuthRedirectError as exc:
        return _redirect(
            error_redirect_url(
                authorize_request.redirect_uri,
                exc.error,
                exc.description,
                authorize_request.state,
            )
        )
    return _redirect(success_redirect_url(authorize_request, code))


@require_POST
async def oauth_kakao_start(request: HttpRequest) -> HttpResponse:
    authorize_request, error_response = await _pending_authorize(request)
    if error_response is not None:
        return error_response
    assert authorize_request is not None
    if not settings.KAKAO_REST_API_KEY:
        return _login_page(
            request,
            _hidden_fields(request.POST),
            "카카오 로그인이 설정되지 않았습니다.",
        )
    try:
        state = await store_pending(authorize_request)
    except SocialLoginError as exc:
        return _login_page(request, _hidden_fields(request.POST), exc.message)
    return _redirect(kakao_authorize_url(state))


@csrf_exempt
@require_GET
async def oauth_kakao_callback(request: HttpRequest) -> HttpResponse:
    return await _social_callback(
        request,
        code=(request.GET.get("code") or "").strip(),
        state=(request.GET.get("state") or "").strip(),
        login=login_with_kakao_code,
    )


@require_POST
async def oauth_apple_start(request: HttpRequest) -> HttpResponse:
    authorize_request, error_response = await _pending_authorize(request)
    if error_response is not None:
        return error_response
    assert authorize_request is not None
    if not settings.APPLE_CLIENT_ID or not settings.APPLE_PRIVATE_KEY:
        return _login_page(
            request,
            _hidden_fields(request.POST),
            "애플 로그인이 설정되지 않았습니다.",
        )
    try:
        state = await store_pending(authorize_request)
    except SocialLoginError as exc:
        return _login_page(request, _hidden_fields(request.POST), exc.message)
    return _redirect(apple_authorize_url(state))


@csrf_exempt
@require_POST
async def oauth_apple_callback(request: HttpRequest) -> HttpResponse:
    async def login(code: str) -> Any:
        return await login_with_apple_code(code, request.POST.get("user"))

    return await _social_callback(
        request,
        code=(request.POST.get("code") or "").strip(),
        state=(request.POST.get("state") or "").strip(),
        login=login,
    )


async def _pending_authorize(
    request: HttpRequest,
) -> tuple[Any, HttpResponse | None]:
    try:
        authorize_request = parse_authorize_request(request.POST)
    except OAuthClientError as exc:
        return None, _login_page(request, {}, exc.description, status=400)
    except OAuthRedirectError as exc:
        redirect_uri = (request.POST.get("redirect_uri") or "").strip()
        state = (request.POST.get("state") or "").strip()
        return None, _redirect(
            error_redirect_url(redirect_uri, exc.error, exc.description, state)
        )
    if not await client_can_use_redirect(
        authorize_request.client_id, authorize_request.redirect_uri
    ):
        return None, _login_page(
            request, {}, "클라이언트 또는 리다이렉트 주소가 올바르지 않습니다.", status=400
        )
    return authorize_request, None


async def _social_callback(
    request: HttpRequest,
    code: str,
    state: str,
    login: Any,
) -> HttpResponse:
    pending = await load_pending(state) if state else None
    fields = _hidden_fields_from_request(pending)
    if pending is None or not code:
        return _login_page(
            request,
            fields,
            "소셜 로그인이 만료되었습니다. 다시 연결해 주세요.",
        )
    try:
        user = await login(code)
    except SocialLoginError as exc:
        return _login_page(request, fields, exc.message)
    try:
        issued = await issue_authorization_code(user.id, pending)
    except OAuthRedirectError as exc:
        return _redirect(
            error_redirect_url(
                pending.redirect_uri,
                exc.error,
                exc.description,
                pending.state,
            )
        )
    await drop_pending(state)
    return _redirect(success_redirect_url(pending, issued))


def _hidden_fields_from_request(pending: Any) -> dict[str, str]:
    if pending is None:
        return {}
    return {name: getattr(pending, name, "") for name in AUTHORIZE_FIELDS}


@csrf_exempt
@require_POST
async def oauth_register(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        return JsonResponse(
            {
                "error": "invalid_client_metadata",
                "error_description": "JSON 객체가 필요합니다.",
            },
            status=400,
        )
    try:
        body = await register_oauth_client(payload)
    except RegistrationError as exc:
        return JsonResponse(
            {"error": "invalid_client_metadata", "error_description": exc.description},
            status=400,
        )
    response = JsonResponse(body, status=201)
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@require_http_methods(["POST"])
async def oauth_token(request: HttpRequest) -> JsonResponse:
    params = request.POST
    authorization = request.headers.get("Authorization", "")
    grant_type = (params.get("grant_type") or "").strip()
    try:
        if grant_type == "authorization_code":
            result = await exchange_authorization_code(params, authorization)
        elif grant_type == "refresh_token":
            result = await exchange_refresh_token(params, authorization)
        else:
            result = {
                "ok": False,
                "status": 400,
                "body": {
                    "error": "unsupported_grant_type",
                    "error_description": "지원하지 않는 grant_type입니다.",
                },
            }
    except OAuthClientError:
        result = {
            "ok": False,
            "status": 401,
            "body": {
                "error": "invalid_client",
                "error_description": "클라이언트가 올바르지 않습니다.",
            },
        }
    return _token_json(result)


def _hidden_fields(params: Any) -> dict[str, str]:
    return {name: (params.get(name) or "") for name in AUTHORIZE_FIELDS}


def _login_page(
    request: HttpRequest,
    oauth_fields: dict[str, str],
    error: str,
    status: int = 200,
) -> HttpResponse:
    response = render(
        request,
        "mcp/oauth_login.html",
        {"error": error, "oauth_fields": oauth_fields, "show_form": bool(oauth_fields)},
        status=status,
    )
    response["Cache-Control"] = "no-store"
    # HTTPS CSRF는 Referer가 필요하다. no-referrer면 로그인 POST가 거절된다.
    response["Referrer-Policy"] = "same-origin"
    return response


def _redirect(url: str) -> HttpResponseRedirect:
    response = HttpResponseRedirect(url)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _token_json(result: dict[str, Any]) -> JsonResponse:
    status = 200 if result["ok"] else result["status"]
    response = JsonResponse(result["body"], status=status)
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response
