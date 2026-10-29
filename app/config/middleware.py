from django.http import HttpResponseNotFound

from config.sentry_utils import is_scanner_request


class OAuthPopupMiddleware:
    """OAuth 로그인 팝업이 플랫폼 창으로 결과를 돌려줄 수 있게 합니다."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/oauth/"):
            response["Cross-Origin-Opener-Policy"] = "unsafe-none"
        return response


class BlockScannerPathsMiddleware:
    """봇 스캔용 민감 경로 요청을 조기에 404로 차단합니다."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_scanner_request(request.path):
            return HttpResponseNotFound()
        return self.get_response(request)
