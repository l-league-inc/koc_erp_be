import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings


def authorization_server_issuer() -> str:
    configured = settings.MCP_OAUTH_ISSUER.strip().rstrip("/")
    if configured:
        return configured
    parts = urlsplit(settings.MCP_RESOURCE_URL)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def protected_resource_metadata() -> dict[str, Any]:
    return {
        "resource": settings.MCP_RESOURCE_URL,
        "authorization_servers": [authorization_server_issuer()],
        "scopes_supported": ["koc_erp"],
        "bearer_methods_supported": ["header"],
    }


def protected_resource_metadata_url() -> str:
    parts = urlsplit(settings.MCP_RESOURCE_URL)
    path = parts.path.strip("/")
    suffix = f"/{path}" if path else ""
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            f"/.well-known/oauth-protected-resource{suffix}",
            "",
            "",
        )
    )


def www_authenticate_header() -> str:
    metadata_url = protected_resource_metadata_url()
    return f'Bearer realm="koc_erp", resource_metadata="{metadata_url}"'


def metadata_body() -> bytes:
    return json.dumps(
        protected_resource_metadata(),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
