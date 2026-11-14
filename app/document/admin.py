import threading

from django.contrib import admin, messages

from document.indexer import (
    DEFAULT_INDEX_SLEEP_SECONDS,
    run_index_files,
    split_shared_file_ids,
)
from document.models import (
    DocumentDownload,
    DocumentFile,
    DocumentFolder,
    DocumentIndex,
    DocumentMailLog,
    DocumentSpace,
)


@admin.action(description="선택한 공유 문서 색인")
def reindex_selected(modeladmin, request, queryset):
    if queryset.model is DocumentIndex:
        file_ids = list(queryset.values_list("file_id", flat=True))
    else:
        file_ids = list(queryset.values_list("id", flat=True))
    shared_ids, personal_count = split_shared_file_ids(file_ids)
    if personal_count:
        modeladmin.message_user(
            request,
            f"개인 문서 {personal_count}건은 언어 모델 색인 대상이 아닙니다.",
            messages.WARNING,
        )
    if not shared_ids:
        return
    threading.Thread(
        target=run_index_files,
        args=(shared_ids, DEFAULT_INDEX_SLEEP_SECONDS),
        kwargs={"force": True},
        daemon=True,
    ).start()
    modeladmin.message_user(
        request,
        f"{len(shared_ids)}건을 백그라운드에서 순차 색인합니다. 결과는 색인 상태에서 확인합니다.",
    )


@admin.register(DocumentSpace)
class DocumentSpaceAdmin(admin.ModelAdmin):
    list_display = ("id", "workspace", "kind", "owner", "created_at")
    list_filter = ("kind",)


@admin.register(DocumentFolder)
class DocumentFolderAdmin(admin.ModelAdmin):
    list_display = ("id", "space", "parent", "name", "is_root", "created_at")


@admin.register(DocumentFile)
class DocumentFileAdmin(admin.ModelAdmin):
    list_display = ("id", "original_filename", "folder", "size", "uploaded_by", "created_at")
    search_fields = ("original_filename", "object_key")
    actions = [reindex_selected]


@admin.register(DocumentIndex)
class DocumentIndexAdmin(admin.ModelAdmin):
    list_display = ("id", "file", "index_status", "index_source", "updated_at")
    list_filter = ("index_status", "index_source")
    actions = [reindex_selected]


@admin.register(DocumentDownload)
class DocumentDownloadAdmin(admin.ModelAdmin):
    list_display = ("id", "file", "user", "source", "created_at")


@admin.register(DocumentMailLog)
class DocumentMailLogAdmin(admin.ModelAdmin):
    list_display = ("id", "file", "sender", "status", "sent_at", "created_at")
