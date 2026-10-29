from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import User
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.contrib.auth.models import Group, Permission
from django.db.models import Prefetch
from django import forms


class UserChangeForm(forms.ModelForm):
    """Admin에서 사용자 정보를 변경할 때 사용하는 폼"""

    password = ReadOnlyPasswordHashField(
        label="비밀번호",
        help_text=(
            "원시 비밀번호는 저장되지 않으므로 이 사용자의 비밀번호를 볼 방법이 없습니다. "
            "다음을 사용하여 비밀번호를 변경할 수 있습니다. "
            '<a href="../password/">이 폼</a>.'
        ),
    )

    class Meta:
        model = User
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 이메일 필드를 완전히 재정의해서 검증 제거
        self.fields["email"] = forms.CharField(
            label="이메일",
            max_length=254,
            required=True,
            validators=[],
            help_text="소셜 로그인 유저의 경우 고유 식별자가 저장됩니다.",
        )
        if self.instance and self.instance.email:
            self.fields["email"].initial = self.instance.email

    def clean_email(self):
        """이메일 검증 완전히 제거"""
        return self.cleaned_data.get("email")

    def full_clean(self):
        """폼 전체 검증을 오버라이드해서 이메일 검증 무시"""
        super().full_clean()
        # 이메일 관련 에러 제거
        if "email" in self.errors:
            del self.errors["email"]

    def save(self, commit=True):
        """폼 저장 시 모델 검증 바이패스"""
        user = super().save(commit=False)
        if commit:
            user.save()
        return user


class UserAddForm(forms.ModelForm):
    """Admin에서 사용자를 새로 생성할 때 사용하는 폼"""

    password1 = forms.CharField(
        label="비밀번호",
        widget=forms.PasswordInput,
    )
    password2 = forms.CharField(
        label="비밀번호 확인",
        widget=forms.PasswordInput,
    )

    login_method = forms.ChoiceField(
        label="로그인 방식",
        choices=User.LoginMethodChoices.choices,
        initial=User.LoginMethodChoices.EMAIL,
    )

    class Meta:
        model = User
        fields = ("email", "login_method")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 이메일 필드를 완전히 재정의해서 검증 제거
        self.fields["email"] = forms.CharField(
            label="이메일",
            max_length=254,
            required=True,
            validators=[],
            help_text="소셜 로그인 유저의 경우 고유 식별자를 입력하세요.",
        )

    def clean_email(self):
        """이메일 검증 완전히 제거"""
        return self.cleaned_data.get("email")

    def full_clean(self):
        """폼 전체 검증을 오버라이드해서 이메일 검증 무시"""
        super().full_clean()
        # 이메일 관련 에러 제거
        if "email" in self.errors:
            del self.errors["email"]

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("비밀번호가 일치하지 않습니다.")
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            # 모델 검증 건너뛰고 직접 저장
            user.save()
        return user


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    form = UserChangeForm  # 수정 폼 지정
    add_form = UserAddForm  # 생성 폼 지정

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "login_method", "password1", "password2"),
            },
        ),
    )

    fieldsets = (
        (
            "프로필 정보",
            {
                "fields": (
                    "email",
                    "social_email",
                    "social_user_id",
                    "login_method",
                    "name",
                    "phone_number",
                    "password",
                ),
                "classes": ("wide",),
            },
        ),
        (
            "추가 정보",
            {
                "fields": (
                    "status",
                    "withdraw_at",
                    "withdraw_reason",
                    "is_withdrawn",
                    "toss_user_key",
                    "toss_access_token",
                    "toss_refresh_token",
                    "toss_ci",
                ),
            },
        ),
        (
            "권한 유형",
            {
                "fields": (
                    "type",
                    "permission_type",
                ),
            },
        ),
        (
            "권한",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_employee",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "중요 날짜",
            {
                "fields": ("last_login", "date_joined"),
                "classes": ("collapse",),
            },
        ),
    )

    list_display = (
        "__str__",
        "user_info",
        "type_badge",
        "login_method_badge",
        "status_badge",
        "is_staff",
        "is_employee",
        "date_joined",
    )

    list_filter = (
        "type",
        "login_method",
        "permission_type",
        "is_active",
        "is_staff",
        "is_employee",
        "date_joined",
    )

    search_fields = ("name", "email", "phone_number", "social_email", "nickname", "id")

    def get_queryset(self, request):
        """N+1 쿼리 방지를 위한 최적화 (list/change view 공통)"""
        qs = super().get_queryset(request)
        return qs.prefetch_related(
            "groups",
            Prefetch(
                "user_permissions",
                queryset=Permission.objects.select_related("content_type"),
            ),
        )

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """
        filter_horizontal의 Permission 목록 렌더 시
        Permission.__str__ → content_type 접근으로 인한 N+1 방지
        """
        if db_field.name == "user_permissions":
            kwargs["queryset"] = Permission.objects.select_related("content_type")
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        """admin에서 저장할 때 이메일 검증을 건너뛰기"""
        # 모델 검증을 수행하지 않고 직접 저장
        obj.save()

    date_hierarchy = "date_joined"
    ordering = ("-date_joined",)
    list_per_page = 30

    readonly_fields = ("last_login", "date_joined")

    def user_info(self, obj):
        """사용자 정보"""
        phone = obj.phone_number if obj.phone_number else "-"
        return format_html(
            "<strong>{}</strong><br/>"
            '<small style="color: #666;">{}</small><br/>'
            '<small style="color: #999;">{}</small>',
            obj.name or "이름없음",
            obj.email,
            phone,
        )

    user_info.short_description = "사용자 정보"

    def type_badge(self, obj):
        """사용자 타입 뱃지"""
        colors = {
            "member": "#0d6efd",
        }
        color = colors.get(obj.type, "#6c757d")
        display = obj.get_type_display() if obj.type else "미설정"
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">{}</span>',
            color,
            display,
        )

    type_badge.short_description = "타입"

    def login_method_badge(self, obj):
        """로그인 방법 뱃지"""
        colors = {
            "email": "#198754",
            "kakao": "#fee500",
            "naver": "#03c75a",
            "google": "#4285f4",
            "apple": "#000000",
        }
        text_colors = {
            "kakao": "#000000",
            "apple": "#ffffff",
        }
        color = colors.get(obj.login_method, "#6c757d")
        text_color = text_colors.get(obj.login_method, "#ffffff")
        display = obj.get_login_method_display() if obj.login_method else "미설정"
        return format_html(
            '<span style="background: {}; color: {}; padding: 3px 8px; border-radius: 3px; font-size: 11px;">{}</span>',
            color,
            text_color,
            display,
        )

    login_method_badge.short_description = "로그인"

    def status_badge(self, obj):
        """활성화 상태"""
        if obj.status == obj.UserStatusChoice.ACTIVE:
            return format_html('<span style="color: #28a745;">●</span> 활성')
        elif obj.status == obj.UserStatusChoice.INACTIVE:
            return format_html('<span style="color: #dc3545;">●</span> 비활성')
        elif obj.status == obj.UserStatusChoice.WITHDRAW:
            return format_html('<span style="color: #6c757d;">●</span> 탈퇴')
        elif obj.status == obj.UserStatusChoice.SUSPENDED:
            return format_html('<span style="color: #ffc107;">●</span> 정지')
        elif obj.status == obj.UserStatusChoice.DORMANT:
            return format_html('<span style="color: #17a2b8;">●</span> 휴면')
        else:
            return format_html('<span style="color: #dc3545;">●</span> 알 수 없음')

    status_badge.short_description = "상태"


# Django 기본 GroupAdmin의 permissions filter_horizontal content_type N+1 방지
admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin):
    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "permissions":
            kwargs["queryset"] = Permission.objects.select_related("content_type")
        return super().formfield_for_manytomany(db_field, request, **kwargs)
