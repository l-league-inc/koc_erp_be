import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from estimate.errors import EstimateError

PDF_MIME = "application/pdf"


def render_pdf(docx: bytes) -> bytes:
    """양식 docx를 다시 그리지 않고 그대로 PDF로 변환합니다. 직인 이미지도 유지됩니다."""
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if binary is None:
        raise EstimateError("PDF 변환 도구가 없습니다.")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source = folder / "estimate.docx"
        source.write_bytes(docx)
        profile = folder / "profile"
        profile.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(folder)
        env["SAL_USE_VCLPLUGIN"] = "svp"
        completed = subprocess.run(
            [
                binary,
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--nologo",
                f"-env:UserInstallation=file://{profile}",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(folder),
                str(source),
            ],
            check=False,
            capture_output=True,
            timeout=90,
            env=env,
        )
        pdf = folder / "estimate.pdf"
        if completed.returncode != 0 or not pdf.is_file():
            raise EstimateError("PDF 변환에 실패했습니다.")
        return pdf.read_bytes()
