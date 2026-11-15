import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from estimate.calculate import CalculatedEstimate, MoneyLine, format_amount, format_issued_on
from estimate.errors import EstimateError
from estimate.formio import FORM_PATH, cell_text, load_document, logical_cells

PDF_MIME = "application/pdf"
_FONT_PATH = Path(__file__).resolve().parent / "fonts" / "NanumGothic.ttf"
_PAGE_SIZE = (1190, 1684)
_MARGIN = 56


def render_pdf(docx: bytes, calculated: CalculatedEstimate) -> bytes:
    converted = _soffice_pdf(docx)
    if converted is not None:
        return converted
    return _sheet_pdf(calculated)


def _soffice_pdf(docx: bytes) -> bytes | None:
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if binary is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source = folder / "estimate.docx"
        source.write_bytes(docx)
        completed = subprocess.run(
            [
                binary,
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(folder),
                str(source),
            ],
            check=False,
            capture_output=True,
            timeout=60,
        )
        pdf = folder / "estimate.pdf"
        if completed.returncode != 0 or not pdf.is_file():
            raise EstimateError("PDF 변환에 실패했습니다.")
        return pdf.read_bytes()


def _sheet_pdf(calculated: CalculatedEstimate) -> bytes:
    pages = _draw_pages(calculated)
    buffer = BytesIO()
    first, *rest = pages
    first.save(buffer, format="PDF", resolution=144.0, save_all=True, append_images=rest)
    return buffer.getvalue()


def _draw_pages(calculated: CalculatedEstimate) -> list[Image.Image]:
    if not _FONT_PATH.is_file():
        raise EstimateError("PDF 글꼴이 없습니다.")
    title_font = ImageFont.truetype(str(_FONT_PATH), 42)
    body_font = ImageFont.truetype(str(_FONT_PATH), 24)
    small_font = ImageFont.truetype(str(_FONT_PATH), 20)
    pages: list[Image.Image] = []
    image, draw, y = _new_page()
    y = _draw_text(draw, y, "견 적 서", title_font, gap=18)
    for line in _company_lines():
        y = _draw_text(draw, y, line, small_font, fill=(80, 80, 80), gap=4)
    y += 16
    for line in (
        f"{calculated.client} {calculated.department}",
        f"{calculated.contact} 님 귀중",
        f"견적일자 : {format_issued_on(calculated.issued_on)}",
        f"품명 : {calculated.product_name}",
    ):
        y = _draw_text(draw, y, line, body_font)
    y += 12
    columns = (520, 90, 90, 150, 150, 140)
    headers = ("구분", "단위", "수량", "단가", "금액", "비고")
    y = _draw_table_row(draw, y, headers, columns, body_font, header=True)
    for line in _money_lines(calculated):
        if y > _PAGE_SIZE[1] - 160:
            pages.append(image)
            image, draw, y = _new_page()
            y = _draw_table_row(draw, y, headers, columns, body_font, header=True)
        values = (
            line.description,
            line.unit,
            str(line.qty) if line.unit else "",
            format_amount(line.unit_price) if line.unit_price is not None else "",
            format_amount(line.amount) if line.unit or line.amount else "",
            line.note,
        )
        y = _draw_table_row(draw, y, values, columns, small_font)
    y += 18
    for label, amount in (
        ("공급가액", calculated.supply_amount),
        ("부가세", calculated.vat),
        ("합계", calculated.total),
    ):
        y = _draw_text(draw, y, f"{label}    {format_amount(amount)}", body_font)
    pages.append(image)
    return pages


def _new_page() -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    image = Image.new("RGB", _PAGE_SIZE, "white")
    return image, ImageDraw.Draw(image), _MARGIN


def _draw_text(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill: tuple[int, int, int] = (20, 20, 20),
    gap: int = 8,
) -> int:
    draw.text((_MARGIN, y), text, font=font, fill=fill)
    return y + font.size + gap


def _draw_table_row(
    draw: ImageDraw.ImageDraw,
    y: int,
    values: tuple[str, ...],
    widths: tuple[int, ...],
    font: ImageFont.FreeTypeFont,
    *,
    header: bool = False,
) -> int:
    x = _MARGIN
    height = font.size + 16
    for value, width in zip(values, widths, strict=True):
        draw.rectangle((x, y, x + width, y + height), outline=(180, 180, 180), width=1)
        if header:
            draw.rectangle((x + 1, y + 1, x + width - 1, y + height - 1), fill=(245, 245, 245))
        draw.text((x + 8, y + 6), _fit(draw, value, font, width - 16), font=font, fill=(20, 20, 20))
        x += width
    return y + height


def _fit(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    clipped = text
    while clipped and draw.textlength(f"{clipped}…", font=font) > width:
        clipped = clipped[:-1]
    return f"{clipped}…"


def _money_lines(calculated: CalculatedEstimate) -> list[MoneyLine]:
    lines: list[MoneyLine] = []
    for device in calculated.devices:
        lines.extend((device.serial_line, device.part_line, device.labor_line))
    if calculated.shipping is not None:
        lines.append(calculated.shipping)
    return lines


def _company_lines() -> list[str]:
    document = load_document(FORM_PATH)
    text = cell_text(logical_cells(document.tables[0].rows[0])[2])
    return [line.strip() for line in text.splitlines() if line.strip()]
