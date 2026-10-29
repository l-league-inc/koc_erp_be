from django.core.management import BaseCommand
from django.contrib.auth import get_user_model


User = get_user_model()


class Command(BaseCommand):
    def handle(self, *args, **options):
        if not User.objects.filter(email="admin@example.com").exists():
            User.objects.create_superuser(
                "admin@example.com",
                "password1234!",
            )
            self.stdout.write(self.style.SUCCESS("Create Admin..."))
        else:
            self.stdout.write(self.style.WARNING("Init Admin Complete..."))

        self.stdout.write(self.style.SUCCESS("Init Admin Complete..."))
