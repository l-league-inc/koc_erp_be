from django.contrib.auth.management.commands import (
    createsuperuser as base_createsuperuser,
)


class Command(base_createsuperuser.Command):
    help = "My custom createsuperuser command"

    # super user type 설정을 위한 오버라이딩
    def handle(self, *args, **options):
        super().handle(*args, **options)
