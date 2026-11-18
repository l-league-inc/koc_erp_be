from ninja import Router, Schema

from drive.models import DriveRelease
from drive.storage import presign_release

router = Router(tags=["Drive"])


class DriveReleaseSchema(Schema):
    version: str
    url: str
    sha256: str
    notes: str


@router.get(
    "/release",
    summary="KOC Drive 현재 버전",
    description="로그인 없이 현재 설치 파일 정보를 받습니다. 배포 버전이 없으면 빈 버전을 돌려줍니다.",
    response=DriveReleaseSchema,
    auth=None,
)
def current_release(request):
    release = DriveRelease.objects.filter(is_current=True).order_by("-id").first()
    if release is None:
        return {"version": "", "url": "", "sha256": "", "notes": ""}
    return {
        "version": release.version,
        "url": presign_release(release.object_key),
        "sha256": release.sha256,
        "notes": release.notes,
    }
