from django.contrib import admin

from workspace.models import (
    Block,
    Database,
    Property,
    PropertyValue,
    Record,
    RecordActivity,
    RelationLink,
    View,
    Workspace,
    WorkspaceMember,
)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "slug", "created_at"]
    search_fields = ["name", "slug"]


@admin.register(WorkspaceMember)
class WorkspaceMemberAdmin(admin.ModelAdmin):
    list_display = ["id", "workspace", "user", "role", "created_at"]
    list_filter = ["role"]


@admin.register(Database)
class DatabaseAdmin(admin.ModelAdmin):
    list_display = ["id", "workspace", "name", "slug", "position"]
    list_filter = ["workspace"]
    search_fields = ["name", "slug"]


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ["id", "database", "name", "slug", "type", "position"]
    list_filter = ["type"]


@admin.register(Record)
class RecordAdmin(admin.ModelAdmin):
    list_display = ["id", "database", "title", "created_by", "updated_at"]
    search_fields = ["title"]


@admin.register(PropertyValue)
class PropertyValueAdmin(admin.ModelAdmin):
    list_display = ["id", "record", "property", "text_value", "number_value"]


@admin.register(RelationLink)
class RelationLinkAdmin(admin.ModelAdmin):
    list_display = ["id", "property", "from_record", "to_record"]


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ["id", "record", "type", "position", "parent"]


@admin.register(View)
class ViewAdmin(admin.ModelAdmin):
    list_display = ["id", "database", "name", "type", "position"]


@admin.register(RecordActivity)
class RecordActivityAdmin(admin.ModelAdmin):
    list_display = ["id", "record", "action", "source", "actor", "created_at"]
    list_filter = ["action", "source"]
