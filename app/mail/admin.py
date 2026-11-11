from django.contrib import admin

from mail.models import UserMailAccount


@admin.register(UserMailAccount)
class UserMailAccountAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "provider",
        "username",
        "is_verified",
        "last_verified_at",
        "created_at",
    )
    list_filter = ("provider", "is_verified")
    search_fields = ("username", "user__email")
    readonly_fields = (
        "password_encrypted",
        "last_verified_at",
        "last_error",
        "created_at",
        "updated_at",
        "deleted_at",
    )
