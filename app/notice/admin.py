from django.contrib import admin
from django.utils.html import format_html
from asgiref.sync import async_to_sync
from notice.models import Notice
from notice.utils import make_notitication_from_notice


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "title_display",
        "type_badge",
        "render_badge",
        "author",
        "view_count_display",
        "status_badge",
        "created_at",
    ]

    list_filter = [
        "type",
        "render",
        "hidden",
        "is_notification_sent",
        "created_at",
        "updated_at",
    ]

    search_fields = [
        "title",
        "content",
        "user__name",
        "user__email",
        "id",
    ]

    date_hierarchy = "created_at"
    ordering = ["-created_at"]
    list_per_page = 30

    # N+1 쿼리 문제 해결
    list_select_related = ("user",)  # ForeignKey 관계

    autocomplete_fields = ["user"]

    readonly_fields = [
        "created_at",
        "updated_at",
        "view_count",
        "is_notification_sent",
    ]

    fieldsets = (
        ("기본 정보", {"fields": ("title", "type", "content", "render")}),
        ("작성자 및 설정", {"fields": ("user", "hidden", "is_notification_sent")}),
        ("통계", {"fields": ("view_count",), "classes": ("collapse",)}),
        (
            "생성/수정 일시",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    actions = [
        "hide_notices",
        "show_notices",
        "publish_notices_and_send_notifications",
        "mark_as_urgent",
    ]

    def title_display(self, obj):
        """제목 표시"""
        max_length = 50
        if len(obj.title) > max_length:
            return format_html(
                '<strong title="{}">{}</strong>',
                obj.title,
                obj.title[:max_length] + "...",
            )
        return format_html("<strong>{}</strong>", obj.title)

    title_display.short_description = "제목"

    def type_badge(self, obj):
        """타입 뱃지"""
        colors = {
            "notice": "#0d6efd",
            "event": "#198754",
            "urgent": "#dc3545",
        }
        color = colors.get(obj.type, "#6c757d")
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px; white-space: nowrap;">{}</span>',
            color,
            obj.get_type_display(),
        )

    type_badge.short_description = "타입"

    def render_badge(self, obj):
        """렌더링 방식 뱃지"""
        colors = {
            "editor": "#6f42c1",
            "url": "#fd7e14",
        }
        color = colors.get(obj.render, "#6c757d")
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">{}</span>',
            color,
            obj.get_render_display(),
        )

    render_badge.short_description = "렌더링"

    def author(self, obj):
        """작성자"""
        if obj.user:
            return format_html(
                '<a href="/admin/user/user/{}/change/">{}</a>',
                obj.user.id,
                obj.user.name or obj.user.email,
            )
        return format_html('<span style="color: #999;">-</span>')

    author.short_description = "작성자"

    def view_count_display(self, obj):
        """조회수 표시"""
        # 일부 데이터/직렬화 케이스에서 문자열로 들어와도 안전하게 렌더링한다.
        view_count = int(obj.view_count or 0)
        return format_html("<strong>{}</strong>", f"{view_count:,}")

    view_count_display.short_description = "조회수"
    view_count_display.admin_order_field = "view_count"

    def status_badge(self, obj):
        """상태 뱃지"""
        if obj.hidden:
            return format_html(
                '<span style="background: #dc3545; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">숨김</span>'
            )
        return format_html(
            '<span style="background: #28a745; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">공개</span>'
        )

    status_badge.short_description = "상태"

    # Actions
    def hide_notices(self, request, queryset):
        """공지 숨기기"""
        updated = queryset.update(hidden=True)
        self.message_user(request, f"{updated}개의 공지를 숨김 처리했습니다.")

    hide_notices.short_description = "선택된 공지 숨기기"

    def show_notices(self, request, queryset):
        """공지 공개하기"""
        updated = queryset.update(hidden=False)
        self.message_user(request, f"{updated}개의 공지를 공개 처리했습니다.")

    show_notices.short_description = "선택된 공지 공개하기"

    def publish_notices_and_send_notifications(self, request, queryset):
        """선택 공지를 발행하고, 아직 전송되지 않은 경우 알림 생성"""
        published_count = 0
        notification_sent_count = 0
        already_sent_count = 0

        for notice in queryset:
            updated_fields = []

            if notice.hidden:
                notice.hidden = False
                updated_fields.append("hidden")
                published_count += 1

            if notice.hidden is False and notice.is_notification_sent is False:
                async_to_sync(make_notitication_from_notice)(notice)
                notice.is_notification_sent = True
                updated_fields.append("is_notification_sent")
                notification_sent_count += 1
            elif notice.is_notification_sent:
                already_sent_count += 1

            if updated_fields:
                notice.save(update_fields=updated_fields)

        self.message_user(
            request,
            (
                f"발행 {published_count}건, 알림 전송 {notification_sent_count}건, "
                f"기전송으로 스킵 {already_sent_count}건"
            ),
        )

    publish_notices_and_send_notifications.short_description = (
        "선택 공지 발행 + 알림 생성"
    )

    def mark_as_urgent(self, request, queryset):
        """긴급공지로 변경"""
        updated = queryset.update(type=Notice.TypeChoices.urgent)
        self.message_user(request, f"{updated}개의 공지를 긴급공지로 변경했습니다.")

    mark_as_urgent.short_description = "선택된 공지를 긴급공지로 변경"
