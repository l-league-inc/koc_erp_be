from django import forms
from django.contrib import admin, messages
from ninja.errors import HttpError

from mail import crypto
from mail.models import UserMailAccount
from mail.service import verify_stored_account


@admin.action(description="선택한 계정 연결 확인")
def verify_selected_accounts(modeladmin, request, queryset):
    ok = 0
    failed: list[str] = []
    for account in queryset:
        try:
            verify_stored_account(account)
        except HttpError as exc:
            failed.append(f"{account.username}: {exc.message}")
            continue
        ok += 1
    if ok:
        modeladmin.message_user(request, f"{ok}건 연결을 확인했습니다.", messages.SUCCESS)
    if failed:
        modeladmin.message_user(
            request,
            "연결에 실패했습니다. " + " ".join(failed),
            messages.ERROR,
        )


class UserMailAccountForm(forms.ModelForm):
    """앱 비밀번호는 평문으로 받지 않고 저장 직전에 암호화합니다."""

    app_password = forms.CharField(
        label="앱 비밀번호",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="입력하면 AES로 암호화해 저장합니다. 수정할 때 비워 두면 기존 비밀번호를 유지합니다.",
    )

    class Meta:
        model = UserMailAccount
        fields = ("user", "provider", "username", "is_verified", "last_error")

    def clean_app_password(self) -> str:
        password = (self.cleaned_data.get("app_password") or "").strip()
        stored = (self.instance.password_encrypted or "").strip()
        if not stored and not password:
            raise forms.ValidationError("앱 비밀번호가 필요합니다.")
        return password

    def save(self, commit=True):
        account = super().save(commit=False)
        password = self.cleaned_data.get("app_password") or ""
        if password:
            account.password_encrypted = crypto.encrypt_secret(password)
        if commit:
            account.save()
        return account


@admin.register(UserMailAccount)
class UserMailAccountAdmin(admin.ModelAdmin):
    form = UserMailAccountForm
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
    actions = [verify_selected_accounts]
    fields = (
        "user",
        "provider",
        "username",
        "app_password",
        "password_encrypted",
        "is_verified",
        "last_verified_at",
        "last_error",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    readonly_fields = (
        "password_encrypted",
        "last_verified_at",
        "last_error",
        "created_at",
        "updated_at",
        "deleted_at",
    )
