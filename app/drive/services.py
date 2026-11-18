from drive.models import DriveRelease
from drive.storage import (
    clean_version,
    delete_release_object,
    hash_package,
    release_object_key,
    upload_release,
)


def publish_release(*, version: str, notes: str, package, make_current: bool) -> DriveRelease:
    cleaned = clean_version(version)
    header = package.read(2)
    package.seek(0)
    if header != b"MZ":
        raise ValueError("Windows 실행 파일(KOC ERP.exe)만 올릴 수 있습니다.")
    sha256, size = hash_package(package)
    key = release_object_key(cleaned)
    upload_release(key, package)
    text = (notes or "").strip()
    if len(text) > 2000:
        text = text[:2000]
    return DriveRelease.objects.create(
        version=cleaned,
        notes=text,
        object_key=key,
        sha256=sha256,
        size=size,
        is_current=make_current,
    )


def discard_releases(releases) -> None:
    items = list(releases)
    removed_ids = {item.pk for item in items}
    for key in {item.object_key for item in items if item.object_key}:
        still_used = DriveRelease.objects.filter(object_key=key).exclude(pk__in=removed_ids).exists()
        if still_used:
            continue
        delete_release_object(key)
    for item in items:
        item.delete()
