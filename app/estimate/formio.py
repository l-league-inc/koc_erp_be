from io import BytesIO
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import _Cell, _Row

FORM_PATH = Path(__file__).resolve().parent / "estimate_form.docx"
EXAMPLE_PATH = Path(__file__).resolve().parent / "estimate_example.docx"

DEVICE_COUNT = 6
FIRST_DEVICE_ROW = 2
SHIPPING_ROW = 20
BLANK_ROW = 21
SUPPLY_ROW = 22
VAT_ROW = 23
TOTAL_ROW = 24
NOTE_ROW = 25

_FONT = "맑은 고딕"


def load_document(source: bytes | str | Path) -> DocumentObject:
    if isinstance(source, bytes):
        return Document(BytesIO(source))
    return Document(str(source))


def save_document(document: DocumentObject) -> bytes:
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def logical_cells(row: _Row) -> list[_Cell]:
    cells: list[_Cell] = []
    seen: set[int] = set()
    for cell in row.cells:
        key = id(cell._tc)
        if key in seen:
            continue
        seen.add(key)
        cells.append(cell)
    return cells


def cell_text(cell: _Cell) -> str:
    return "\n".join(paragraph.text for paragraph in cell.paragraphs).strip()


def set_cell_text(cell: _Cell, text: str) -> None:
    set_paragraph_text(cell.paragraphs[0], text)
    for paragraph in cell.paragraphs[1:]:
        set_paragraph_text(paragraph, "")


def set_paragraph_text(paragraph, text: str) -> None:
    if not paragraph.runs:
        if text:
            _ensure_font(paragraph.add_run(text))
        return
    paragraph.runs[0].text = text
    _ensure_font(paragraph.runs[0])
    for run in paragraph.runs[1:]:
        run.text = ""


def _ensure_font(run) -> None:
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)
    for name in ("ascii", "hAnsi", "eastAsia", "cs"):
        attr = qn(f"w:{name}")
        if not r_fonts.get(attr):
            r_fonts.set(attr, _FONT)
