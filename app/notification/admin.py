from django.contrib import admin
from django.utils.html import format_html
from notification.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "user_link",
        "message_preview",
        "metadata_preview",
        "read_badge",
        "created_at",
    ]
    list_filter = ["is_read", "created_at", "updated_at"]
    search_fields = ["id", "message", "user__email", "user__name", "user__nickname"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]
    list_per_page = 30
    list_select_related = ("user",)

    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("기본 정보", {"fields": ("user", "message", "is_read")}),
        ("메타데이터", {"fields": ("metadata",)}),
        (
            "생성/수정 일시",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    actions = ["mark_as_read", "mark_as_unread"]

    def user_link(self, obj):
        if obj.user_id:
            return format_html(
                '<a href="/admin/user/user/{}/change/">{}</a>',
                obj.user_id,
                obj.user.name or obj.user.nickname or obj.user.email,
            )
        return format_html('<span style="color: #999;">-</span>')

    user_link.short_description = "사용자"
    user_link.admin_order_field = "user"

    def message_preview(self, obj):
        max_length = 60
        if len(obj.message) > max_length:
            return format_html(
                '<span title="{}">{}</span>',
                obj.message,
                f"{obj.message[:max_length]}...",
            )
        return obj.message

    message_preview.short_description = "메시지"

    def metadata_preview(self, obj):
        if not obj.metadata:
            return format_html('<span style="color: #999;">-</span>')
        metadata_text = str(obj.metadata)
        max_length = 80
        if len(metadata_text) > max_length:
            return format_html(
                '<code title="{}">{}</code>',
                metadata_text,
                f"{metadata_text[:max_length]}...",
            )
        return format_html("<code>{}</code>", metadata_text)

    metadata_preview.short_description = "메타데이터"

    def read_badge(self, obj):
        if obj.is_read:
            return format_html(
                '<span style="background: #198754; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">읽음</span>'
            )
        return format_html(
            '<span style="background: #dc3545; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">안읽음</span>'
        )

    read_badge.short_description = "상태"
    read_badge.admin_order_field = "is_read"

    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f"{updated}개의 알림을 읽음 처리했습니다.")

    mark_as_read.short_description = "선택된 알림 읽음 처리"

    def mark_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False)
        self.message_user(request, f"{updated}개의 알림을 안읽음 처리했습니다.")

    mark_as_unread.short_description = "선택된 알림 안읽음 처리"
