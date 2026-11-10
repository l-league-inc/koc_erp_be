"""워크봇 예약 실행기.

서버 프로세스 안의 백그라운드 스레드가 일정마다 `run_due_workbots`를 부릅니다.
워커가 여러 개여도 `claim_due_bots`가 `next_run_at`을 조건부로 먼저 넘기므로
같은 실행이 두 번 일어나지 않습니다.
"""

import logging
import threading
import time

from django.conf import settings
from django.db import close_old_connections

from assistant.workbot import run_due_workbots

logger = logging.getLogger("django")

_lock = threading.Lock()
_thread: threading.Thread | None = None


def _loop(interval: int) -> None:
    # 워커마다 시작 시각이 다르므로 틱이 겹쳐도 claim이 중복 실행을 막습니다.
    time.sleep(5)
    while True:
        try:
            close_old_connections()
            count = run_due_workbots()
            if count:
                logger.info("workbot scheduler ran=%s", count)
        except Exception:
            logger.exception("workbot scheduler tick failed")
        finally:
            close_old_connections()
        time.sleep(interval)


def start_scheduler() -> bool:
    """설정이 켜져 있으면 스케줄러 스레드를 한 번만 띄웁니다."""
    global _thread
    if not getattr(settings, "WORKBOT_SCHEDULER_ENABLED", False):
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        interval = max(int(getattr(settings, "WORKBOT_SCHEDULER_INTERVAL", 30)), 5)
        _thread = threading.Thread(
            target=_loop,
            args=(interval,),
            name="workbot-scheduler",
            daemon=True,
        )
        _thread.start()
    logger.info("workbot scheduler started interval=%ss", interval)
    return True
