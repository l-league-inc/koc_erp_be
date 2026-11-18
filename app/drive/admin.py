from django import forms
from django.contrib import admin, messages
from django.http import Http404, HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html

from drive.models import DriveRelease
from drive.services import discard_releases, publish_release
from drive.storage import presign_release


class DriveReleaseAdminForm(forms.ModelForm):
    package = forms.FileField(
        required=False,
        label="설치 파일",
        help_text="publish.sh가 만든 KOC ERP.exe 입니다. 압축 파일은 올리지 않습니다.",
    )

    class Meta:
        model = DriveRelease
        fields = ("version", "notes", "is_current")

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk or "package" not in self.fields:
            return cleaned
        package = cleaned.get("package")
        if package is None:
            raise forms.ValidationError("설치 파일이 필요합니다.")
        header = package.read(2)
        package.seek(0)
        if header != b"MZ":
            raise forms.ValidationError("Windows 실행 파일(KOC ERP.exe)만 올릴 수 있습니다.")
        return cleaned


@admin.register(DriveRelease)
class DriveReleaseAdmin(admin.ModelAdmin):
    form = DriveReleaseAdminForm
    list_display = ("version", "is_current", "size", "download_link", "created_at")
    list_filter = ("is_current",)
    search_fields = ("version", "notes", "sha256")
    readonly_fields = ("sha256", "size", "object_key", "download_link", "created_at", "updated_at")

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:object_id>/download/",
                self.admin_site.admin_view(self.download_view),
                name="drive_driverelease_download",
            ),
        ]
        return custom + urls

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("version", "notes", "is_current", "package")
        return (
            "version",
            "notes",
            "is_current",
            "download_link",
            "sha256",
            "size",
            "object_key",
            "created_at",
            "updated_at",
        )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields.append("version")
        return fields

    def save_model(self, request, obj, form, change):
        package = form.cleaned_data.get("package")
        if not change and package is not None:
            stored = publish_release(
                version=form.cleaned_data["version"],
                notes=form.cleaned_data.get("notes") or "",
                package=package,
                make_current=bool(form.cleaned_data.get("is_current")),
            )
            obj.pk = stored.pk
            obj.version = stored.version
            obj.object_key = stored.object_key
            obj.sha256 = stored.sha256
            obj.size = stored.size
            return
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        discard_releases([obj])

    def delete_queryset(self, request, queryset):
        discard_releases(queryset)

    @admin.display(description="파일")
    def download_link(self, obj):
        if not getattr(obj, "pk", None) or not obj.object_key:
            return "-"
        url = reverse("admin:drive_driverelease_download", args=[obj.pk])
        return format_html('<a class="button" href="{}">다운로드</a>', url)

    def download_view(self, request, object_id):
        release = self.get_object(request, object_id)
        if release is None:
            raise Http404
        try:
            url = presign_release(release.object_key, filename=f"KOC ERP {release.version}.exe")
        except Exception:
            messages.error(request, "설치 파일을 받지 못했습니다.")
            return HttpResponseRedirect(reverse("admin:drive_driverelease_change", args=[release.pk]))
        return HttpResponseRedirect(url)
