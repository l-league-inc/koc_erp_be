from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from websocket.middlewares import CustomAuthMiddleware
from channels.security.websocket import AllowedHostsOriginValidator


def get_websocket_urlpatterns():
    from notification.routing import websocket_urlpatterns as notification_urlpatterns

    return notification_urlpatterns


def get_application():
    django_asgi_app = get_asgi_application()
    from django.conf import settings

    http_app = django_asgi_app
    session_guard = None
    if settings.MCP_ENABLED:
        from mcp_server.asgi import LifespanApplication, PrefixRouter, SessionGuard
        from mcp_server.server import build_mcp_http

        mcp_app, session_manager = build_mcp_http(django_asgi_app)
        http_app = PrefixRouter(mcp_app, django_asgi_app)
        session_guard = SessionGuard(session_manager)

    router = ProtocolTypeRouter(
        {
            "http": http_app,
            "websocket": CustomAuthMiddleware(URLRouter(get_websocket_urlpatterns())),
        }
    )
    if session_guard is None:
        return router
    return LifespanApplication(router, session_guard)
