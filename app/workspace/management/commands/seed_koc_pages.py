from django.core.management import BaseCommand

from workspace.pages import seed_koc_pages


class Command(BaseCommand):
    help = "KOC 기본 페이지와 CSV 데이터베이스, 레코드를 만듭니다."

    def handle(self, *args, **options):
        result = seed_koc_pages()
        for warning in result["warnings"]:
            self.stdout.write(self.style.WARNING(warning))
        workspace = result["workspace"]
        self.stdout.write(
            self.style.SUCCESS(
                "KOC 페이지 시드를 맞췄습니다. "
                f"workspace={workspace.id} databases={result['database_count']} "
                f"records={result['record_count']} created={result['created_count']}"
            )
        )
