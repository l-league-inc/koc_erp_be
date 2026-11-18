import os

from django.core.management.base import BaseCommand, CommandError

from drive.services import publish_release


class Command(BaseCommand):
    help = "KOC Drive 설치 파일을 현재 릴리스로 올립니다."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="KOC ERP.exe 경로")
        parser.add_argument("--version", required=True, help="예: 1.1.0")
        parser.add_argument("--notes", default="", help="사용자에게 보여줄 변경 내용")

    def handle(self, *args, **options):
        path = options["file"]
        if not os.path.isfile(path):
            raise CommandError("파일이 없습니다.")
        try:
            with open(path, "rb") as package:
                release = publish_release(
                    version=options["version"],
                    notes=options["notes"],
                    package=package,
                    make_current=True,
                )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"{release.version} {release.sha256}")
