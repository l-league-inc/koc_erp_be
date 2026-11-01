from django.contrib import admin
from django.db.models import Count

from assistant.models import AgentMessage, AgentSession, ProposedAction, Skill, Workbot, WorkbotRun


class _ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class AgentMessageInline(_ReadOnlyInline):
    model = AgentMessage
    fields = ["role", "content", "created_at"]
    readonly_fields = ["role", "content", "created_at"]
    ordering = ["id"]


class ProposedActionInline(_ReadOnlyInline):
    model = ProposedAction
    fields = ["kind", "status", "payload", "result", "created_at"]
    readonly_fields = ["kind", "status", "payload", "result", "created_at"]
    ordering = ["id"]


class WorkbotRunInline(_ReadOnlyInline):
    model = WorkbotRun
    fields = ["status", "summary", "record_ids", "created_at"]
    readonly_fields = ["status", "summary", "record_ids", "created_at"]
    ordering = ["-id"]


@admin.register(AgentSession)
class AgentSessionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "workspace",
        "database_slug",
        "message_count",
        "updated_at",
    ]
    list_filter = ["database_slug", "workspace"]
    search_fields = ["user__email", "user__name", "messages__content"]
    readonly_fields = ["user", "workspace", "database_slug", "created_at", "updated_at"]
    inlines = [AgentMessageInline, ProposedActionInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_message_count=Count("messages"))

    @admin.display(description="메시지", ordering="_message_count")
    def message_count(self, obj):
        return obj._message_count


@admin.register(AgentMessage)
class AgentMessageAdmin(admin.ModelAdmin):
    list_display = ["id", "session", "role", "preview", "created_at"]
    list_filter = ["role"]
    search_fields = ["content", "session__user__email"]
    readonly_fields = ["session", "role", "content", "created_at", "updated_at"]

    @admin.display(description="내용")
    def preview(self, obj):
        text = " ".join((obj.content or "").split())
        if len(text) <= 80:
            return text
        return text[:80] + "…"


@admin.register(ProposedAction)
class ProposedActionAdmin(admin.ModelAdmin):
    list_display = ["id", "session", "kind", "status", "created_at"]
    list_filter = ["kind", "status"]
    search_fields = ["session__user__email"]
    readonly_fields = ["session", "kind", "status", "payload", "result", "created_at", "updated_at"]


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "workspace", "enabled", "created_by", "updated_at"]
    list_filter = ["enabled", "workspace"]
    search_fields = ["name", "description", "body", "created_by__email"]
    readonly_fields = ["created_by", "created_at", "updated_at"]


@admin.register(Workbot)
class WorkbotAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "owner", "database_slug", "enabled", "next_run_at"]
    list_filter = ["enabled", "database_slug"]
    search_fields = ["name", "instruction", "owner__email"]
    readonly_fields = ["owner", "created_at", "updated_at", "last_run_at"]
    inlines = [WorkbotRunInline]


@admin.register(WorkbotRun)
class WorkbotRunAdmin(admin.ModelAdmin):
    list_display = ["id", "workbot", "status", "summary_preview", "created_at"]
    list_filter = ["status"]
    search_fields = ["summary", "workbot__name"]
    readonly_fields = ["workbot", "status", "summary", "record_ids", "payload", "created_at", "updated_at"]

    @admin.display(description="요약")
    def summary_preview(self, obj):
        text = " ".join((obj.summary or "").split())
        if len(text) <= 80:
            return text
        return text[:80] + "…"
