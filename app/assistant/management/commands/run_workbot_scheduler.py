import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from assistant.workbot import run_due_workbots


class Command(BaseCommand):
    help = "워크봇 예약 실행기를 계속 돌립니다. 서버 안 스케줄러를 끈 환경에서 별도 프로세스로 씁니다."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=30, help="확인 주기(초)")

    def handle(self, *args, **options):
        interval = max(int(options["interval"]), 5)
        self.stdout.write(f"workbot scheduler interval={interval}s")
        while True:
            close_old_connections()
            try:
                count = run_due_workbots()
                if count:
                    self.stdout.write(f"ran {count}")
            except Exception as exc:  # noqa: BLE001 - 다음 틱에서 다시 시도합니다.
                self.stderr.write(f"tick failed: {exc}")
            time.sleep(interval)
