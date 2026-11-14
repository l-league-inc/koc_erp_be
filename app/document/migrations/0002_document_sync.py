import django.db.models.deletion
from django.db import migrations, models

from document.names import allocate_unique_name


def _rename_duplicates(apps, schema_editor):
    DocumentFolder = apps.get_model("document", "DocumentFolder")
    DocumentFile = apps.get_model("document", "DocumentFile")
    DocumentIndex = apps.get_model("document", "DocumentIndex")

    folders = list(
        DocumentFolder.objects.filter(deleted_at__isnull=True, is_root=False).order_by(
            "space_id", "parent_id", "id"
        )
    )
    taken_folders: dict[tuple, set[str]] = {}
    for folder in folders:
        key = (folder.space_id, folder.parent_id)
        taken = taken_folders.setdefault(key, set())
        renamed = allocate_unique_name(folder.name, taken, fallback="folder")
        if renamed != folder.name:
            folder.name = renamed
            folder.save(update_fields=["name"])

    files = list(
        DocumentFile.objects.filter(deleted_at__isnull=True).order_by("folder_id", "id")
    )
    taken_files: dict[int, set[str]] = {}
    for stored_file in files:
        taken = taken_files.setdefault(stored_file.folder_id, set())
        renamed = allocate_unique_name(
            stored_file.original_filename,
            taken,
            fallback="file",
        )
        if renamed != stored_file.original_filename:
            stored_file.original_filename = renamed
            stored_file.save(update_fields=["original_filename"])
            DocumentIndex.objects.filter(file_id=stored_file.id).update(filename=renamed)


class Migration(migrations.Migration):

    dependencies = [
        ("document", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentfile",
            name="content_hash",
            field=models.CharField(blank=True, default="", help_text="SHA-256", max_length=64),
        ),
        migrations.CreateModel(
            name="DocumentChange",
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
                ("entity", models.CharField(choices=[("folder", "폴더"), ("file", "파일")], help_text="대상 종류", max_length=10)),
                ("entity_id", models.PositiveBigIntegerField(help_text="대상 id")),
                ("op", models.CharField(choices=[("upsert", "반영"), ("delete", "삭제")], help_text="동작", max_length=10)),
                ("payload", models.JSONField(default=dict, help_text="변경 내용")),
                ("created_at", models.DateTimeField(auto_now_add=True, help_text="생성일")),
                (
                    "space",
                    models.ForeignKey(
                        help_text="문서함",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="changes",
                        to="document.documentspace",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="documentchange",
            index=models.Index(fields=["space", "id"], name="document_change_space_id"),
        ),
        migrations.RunPython(_rename_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="documentfile",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("folder", "original_filename"),
                name="unique_document_file_name",
            ),
        ),
    ]
