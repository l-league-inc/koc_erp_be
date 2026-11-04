from django.contrib import admin

from document.models import (
    DocumentDownload,
    DocumentFile,
    DocumentFolder,
    DocumentIndex,
    DocumentMailLog,
    DocumentSpace,
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


@admin.register(DocumentIndex)
class DocumentIndexAdmin(admin.ModelAdmin):
    list_display = ("id", "file", "index_status", "index_source", "updated_at")
    list_filter = ("index_status", "index_source")


@admin.register(DocumentDownload)
class DocumentDownloadAdmin(admin.ModelAdmin):
    list_display = ("id", "file", "user", "source", "created_at")


@admin.register(DocumentMailLog)
class DocumentMailLogAdmin(admin.ModelAdmin):
    list_display = ("id", "file", "sender", "status", "sent_at", "created_at")
