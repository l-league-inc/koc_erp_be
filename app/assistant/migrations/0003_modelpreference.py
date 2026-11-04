import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0002_skill"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ModelPreference",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("model", models.CharField(help_text="모델 id", max_length=64)),
                ("updated_at", models.DateTimeField(auto_now=True, help_text="수정일")),
                (
                    "user",
                    models.OneToOneField(
                        help_text="사용자",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="llm_preference",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
