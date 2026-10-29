from django.core.management import BaseCommand
import os
import time


class Command(BaseCommand):
    def handle(self, *args, **options):

        start_time = time.time()

        os.system("python manage.py initadmin")
        os.system("python manage.py initcategory")

        end_time = time.time()  # command 종료 시간 기록
        elapsed_time = end_time - start_time  # 경과 시간 계산

        self.stdout.write(self.style.SUCCESS(f"time: {round(elapsed_time, 2)}s"))
