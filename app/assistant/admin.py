from django.contrib import admin

from assistant.models import AgentMessage, AgentSession, ProposedAction, Workbot, WorkbotRun


@admin.register(AgentSession)
class AgentSessionAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "workspace", "database_slug", "created_at"]


@admin.register(AgentMessage)
class AgentMessageAdmin(admin.ModelAdmin):
    list_display = ["id", "session", "role", "created_at"]


@admin.register(ProposedAction)
class ProposedActionAdmin(admin.ModelAdmin):
    list_display = ["id", "session", "kind", "status", "created_at"]


@admin.register(Workbot)
class WorkbotAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "database_slug", "enabled", "next_run_at"]
    list_filter = ["enabled"]


@admin.register(WorkbotRun)
class WorkbotRunAdmin(admin.ModelAdmin):
    list_display = ["id", "workbot", "status", "created_at"]
    list_filter = ["status"]
