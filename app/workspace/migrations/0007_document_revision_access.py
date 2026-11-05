import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0006_block_appflowy_types"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="database",
            name="access",
            field=models.CharField(
                choices=[("member", "멤버"), ("admin", "관리자")],
                default="member",
                help_text="본문 수정 권한",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="page",
            name="access",
            field=models.CharField(
                choices=[("member", "멤버"), ("admin", "관리자")],
                default="member",
                help_text="문서 본문 수정 권한",
                max_length=10,
            ),
        ),
        migrations.CreateModel(
            name="DocumentRevision",
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
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, help_text="생성일")),
                ("updated_at", models.DateTimeField(auto_now=True, help_text="수정일")),
                ("deleted_at", models.DateTimeField(blank=True, help_text="삭제일", null=True)),
                ("body", models.JSONField(default=dict, help_text="복원 스냅샷")),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        help_text="고친 사용자",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="document_revisions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "page",
                    models.ForeignKey(
                        blank=True,
                        help_text="문서 페이지",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="revisions",
                        to="workspace.page",
                    ),
                ),
                (
                    "record",
                    models.ForeignKey(
                        blank=True,
                        help_text="레코드",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="revisions",
                        to="workspace.record",
                    ),
                ),
            ],
            options={
                "ordering": ["-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="documentrevision",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("page__isnull", True), ("record__isnull", False)),
                    models.Q(("page__isnull", False), ("record__isnull", True)),
                    _connector="OR",
                ),
                name="revision_record_or_page",
            ),
        ),
    ]
