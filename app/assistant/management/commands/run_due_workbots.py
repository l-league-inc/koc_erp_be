from django.core.management.base import BaseCommand

from assistant.workbot import run_due_workbots


class Command(BaseCommand):
    help = "다음 실행 시각이 지난 워크봇을 실행합니다."

    def handle(self, *args, **options):
        count = run_due_workbots()
        self.stdout.write(f"ran {count}")
