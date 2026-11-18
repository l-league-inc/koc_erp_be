from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="DriveRelease",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, help_text="생성일")),
                ("updated_at", models.DateTimeField(auto_now=True, help_text="수정일")),
                ("deleted_at", models.DateTimeField(blank=True, help_text="삭제일", null=True)),
                ("version", models.CharField(help_text="예: 1.1.0", max_length=32)),
                ("notes", models.TextField(blank=True, default="", help_text="사용자에게 보여줄 변경 내용")),
                ("object_key", models.CharField(help_text="S3 객체 키", max_length=500)),
                ("sha256", models.CharField(help_text="설치 파일 SHA-256", max_length=64)),
                ("size", models.PositiveBigIntegerField(default=0, help_text="바이트")),
                ("is_current", models.BooleanField(default=True, help_text="이 버전을 사용자에게 배포")),
            ],
            options={
                "verbose_name": "Drive 릴리스",
                "verbose_name_plural": "Drive 릴리스",
                "ordering": ["-created_at"],
            },
        ),
    ]
