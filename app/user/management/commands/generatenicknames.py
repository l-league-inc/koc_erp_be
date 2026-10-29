from django.core.management import BaseCommand
from django.contrib.auth import get_user_model

from user.nickname_utils import generate_unique_nickname, get_users_without_nickname

User = get_user_model()


class Command(BaseCommand):
    help = "닉네임이 없는 기존 유저에게 자동 닉네임을 부여합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="실제 저장 없이 대상 유저와 생성될 닉네임만 출력합니다.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        users = get_users_without_nickname().order_by("id")

        if not users.exists():
            self.stdout.write(self.style.WARNING("닉네임이 없는 유저가 없습니다."))
            return

        updated_count = 0
        for user in users.iterator():
            nickname = generate_unique_nickname(exclude_user_id=user.id)

            if dry_run:
                self.stdout.write(
                    f"[dry-run] user_id={user.id} email={user.email} -> {nickname}"
                )
            else:
                user.nickname = nickname
                user.save(update_fields=["nickname"])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"user_id={user.id} email={user.email} -> {nickname}"
                    )
                )

            updated_count += 1

        action = "미리보기" if dry_run else "닉네임 부여"
        self.stdout.write(
            self.style.SUCCESS(f"{action} 완료: {updated_count}명 처리")
        )
