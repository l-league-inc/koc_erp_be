import asyncio
from typing import Any


class PrefixRouter:
    """`/mcp`만 MCP 앱으로 보내고 나머지 HTTP는 Django로 보냅니다."""

    def __init__(self, mcp_app: Any, django_app: Any) -> None:
        self.mcp_app = mcp_app
        self.django_app = django_app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = scope.get("path") or ""
        if scope["type"] == "http" and (path == "/mcp" or path.startswith("/mcp/")):
            await self.mcp_app(scope, receive, send)
            return
        await self.django_app(scope, receive, send)


class SessionGuard:
    """세션 매니저를 요청 태스크와 분리된 태스크에서 유지합니다."""

    def __init__(self, session_manager: Any) -> None:
        self.session_manager = session_manager
        self._lock: asyncio.Lock | None = None
        self._started: asyncio.Event | None = None
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        assert self._started is not None
        assert self._stop is not None
        try:
            async with self.session_manager.run():
                self._started.set()
                await self._stop.wait()
        finally:
            self._started.set()

    async def ensure(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
            self._started = asyncio.Event()
            self._stop = asyncio.Event()
        assert self._started is not None
        if self._started.is_set():
            return
        async with self._lock:
            if self._task is None:
                self._task = asyncio.create_task(self._run())
            await self._started.wait()

    async def shutdown(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None


class LifespanApplication:
    """gunicorn lifespan과 첫 `/mcp` 요청에서 세션 매니저를 켭니다."""

    def __init__(self, app: Any, guard: SessionGuard) -> None:
        self.app = app
        self.guard = guard

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        path = scope.get("path") or ""
        if scope["type"] == "http" and (path == "/mcp" or path.startswith("/mcp/")):
            await self.guard.ensure()
        await self.app(scope, receive, send)

    async def _lifespan(self, receive: Any, send: Any) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    await self.guard.ensure()
                except Exception as exc:
                    await send(
                        {"type": "lifespan.startup.failed", "message": str(exc)}
                    )
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await self.guard.shutdown()
                await send({"type": "lifespan.shutdown.complete"})
                return
