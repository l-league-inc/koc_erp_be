from django.core.management.base import BaseCommand, CommandError

from document.indexer import (
    DEFAULT_INDEX_SLEEP_SECONDS,
    index_files,
    pending_shared_file_ids,
)
from document.models import DocumentFile

_OUTCOME_LABEL = {
    "ready": "완료",
    "failed": "실패",
    "skipped": "제외",
    "passed": "건너뜀",
}


class Command(BaseCommand):
    help = "언어 모델 색인이 없는 공유 파일을 한 건씩 색인합니다. 문서, 이미지, 오디오, 영상을 포함합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sleep",
            type=float,
            default=DEFAULT_INDEX_SLEEP_SECONDS,
            help="언어 모델을 호출한 파일 사이의 대기 초. 기본값은 5입니다.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="이번에 색인할 파일 수 상한.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="색인을 실행하지 않고 대상 건수만 보여 줍니다.",
        )

    def handle(self, *args, **options):
        sleep_seconds = options["sleep"]
        limit = options["limit"]
        if sleep_seconds < 0:
            raise CommandError("--sleep는 0 이상이어야 합니다.")
        if limit is not None and limit < 1:
            raise CommandError("--limit는 1 이상이어야 합니다.")
        file_ids = pending_shared_file_ids(limit=limit)
        if options["dry_run"]:
            self.stdout.write(f"대상 {len(file_ids)}건")
            names = dict(
                DocumentFile.objects.filter(id__in=file_ids).values_list("id", "original_filename")
            )
            for file_id in file_ids:
                self.stdout.write(f"{file_id} {names.get(file_id, '')}")
            return

        total = len(file_ids)
        done = 0

        def on_item(file_id: int, filename: str, outcome: str) -> None:
            nonlocal done
            done += 1
            label = _OUTCOME_LABEL.get(outcome, outcome)
            self.stdout.write(f"{done}/{total} {filename}: {label}")

        result = index_files(file_ids, sleep_seconds, on_item=on_item)
        self.stdout.write(
            self.style.SUCCESS(
                f"완료 {result.ready}건, 실패 {result.failed}건, "
                f"제외 {result.skipped}건, 건너뜀 {result.passed}건"
            )
        )
