from django.core.management.base import BaseCommand, CommandError

from document.backup_import import (
    import_backup_documents,
    resolve_user,
    resolve_workspace,
)


class Command(BaseCommand):
    help = "S3 backup 폴더 안의 문서를 꺼내 공유 문서함 루트에 복원합니다. backup 폴더는 만들지 않습니다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-id",
            type=int,
            default=None,
            help="대상 워크스페이스 id. 없으면 --workspace-slug를 사용합니다.",
        )
        parser.add_argument(
            "--workspace-slug",
            default="koc",
            help="대상 워크스페이스 슬러그. 기본값은 koc입니다.",
        )
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="올린 사람으로 기록할 사용자 id. 없으면 워크스페이스 소유자입니다.",
        )
        parser.add_argument(
            "--prefix",
            default="backup/",
            help="꺼낼 S3 prefix. 이 이름은 문서함 폴더가 되지 않습니다. 기본값은 backup/입니다.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="이번에 새로 등록할 파일 수 상한.",
        )
        parser.add_argument(
            "--index",
            action="store_true",
            help="등록한 문서의 본문 색인을 실행합니다. 공유 문서는 언어 모델을 호출할 수 있습니다.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="복사, 삭제, 등록 없이 대상 건수만 계산합니다.",
        )

    def handle(self, *args, **options):
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit는 1 이상이어야 합니다.")
        try:
            workspace = resolve_workspace(options["workspace_id"], options["workspace_slug"])
            user = resolve_user(workspace, options["user_id"])
            result = import_backup_documents(
                workspace=workspace,
                user=user,
                prefix=options["prefix"],
                dry_run=options["dry_run"],
                index=options["index"],
                limit=options["limit"],
            )
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        mode = "미리보기" if options["dry_run"] else "완료"
        removed = "" if options["dry_run"] else f"원본 삭제 {result.removed}건, "
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: 등록 {result.imported}건, {removed}색인 {result.indexed}건, "
                f"폴더 {result.folders_created}개, 기존 {result.skipped_existing}건, "
                f"제외 {result.skipped}건, 실패 {result.failed}건 "
                f"(workspace={workspace.id}, prefix={options['prefix']})"
            )
        )
        for error in result.errors[:30]:
            self.stdout.write(self.style.WARNING(error))
        if len(result.errors) > 30:
            self.stdout.write(self.style.WARNING(f"오류가 {len(result.errors) - 30}건 더 있습니다."))
