from django.core.management import BaseCommand

from workspace.seed import seed_koc_workspace


class Command(BaseCommand):
    help = "KOC 워크스페이스 기본 데이터베이스를 만듭니다."

    def handle(self, *args, **options):
        workspace = seed_koc_workspace()
        self.stdout.write(
            self.style.SUCCESS(f"KOC 워크스페이스 시드를 맞췄습니다. workspace={workspace.id}")
        )
