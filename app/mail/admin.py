from django import forms
from django.contrib import admin

from mail import crypto
from mail.models import UserMailAccount


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
