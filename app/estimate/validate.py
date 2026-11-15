import re
from dataclasses import dataclass

from estimate.calculate import (
    CalculatedEstimate,
    MoneyLine,
    client_line,
    contact_line,
    date_line,
    product_line,
    vat_amount,
)
from estimate.errors import EstimateError
from estimate.formio import (
    BLANK_ROW,
    DEVICE_COUNT,
    FIRST_DEVICE_ROW,
    FORM_PATH,
    NOTE_ROW,
    SHIPPING_ROW,
    SUPPLY_ROW,
    TOTAL_ROW,
    VAT_ROW,
    cell_text,
    load_document,
    logical_cells,
)

_DATE_LINE = re.compile(r"견적일자 : \d{4}년 \d{1,2}월 \d{1,2}일")


@dataclass(frozen=True)
class ParsedLine:
    description: str
    unit: str
    qty: int | None
    unit_price: int | None
    amount: int | None
    note: str


@dataclass(frozen=True)
class ParsedDocument:
    client_line: str
    contact_line: str
    date_line: str
    validity_line: str
    delivery_line: str
    closing_line: str
    company_lines: tuple[str, ...]
    product_line: str
    header_total: int | None
    devices: tuple[tuple[ParsedLine, ParsedLine, ParsedLine], ...]
    shipping: ParsedLine
    blank_line: ParsedLine
    supply_label: str
    supply_amount: int | None
    vat_label: str
    vat: int | None
    total_label: str
    total: int | None
    special_note: str


def verify_document(
    source: bytes | str,
    expected: CalculatedEstimate | None = None,
) -> ParsedDocument:
    parsed = parse_document(source)
    _check_static_text(parsed)
    _check_header(parsed)
    _check_arithmetic(parsed)
    if expected is not None:
        _check_matches(parsed, expected)
    return parsed


def parse_document(source: bytes | str) -> ParsedDocument:
    document = load_document(source)
    header = document.tables[0].rows[0].cells[0].paragraphs
    company = document.tables[0].rows[0].cells[2]
    table = document.tables[1]
    devices = tuple(
        (
            _parse_line(table.rows[FIRST_DEVICE_ROW + index * 3]),
            _parse_line(table.rows[FIRST_DEVICE_ROW + index * 3 + 1]),
            _parse_line(table.rows[FIRST_DEVICE_ROW + index * 3 + 2]),
        )
        for index in range(DEVICE_COUNT)
    )
    return ParsedDocument(
        client_line=header[0].text.strip(),
        contact_line=header[1].text.strip(),
        date_line=header[2].text.strip(),
        validity_line=header[3].text.strip(),
        delivery_line=header[4].text.strip(),
        closing_line=header[5].text.strip(),
        company_lines=tuple(paragraph.text.strip() for paragraph in company.paragraphs),
        product_line=cell_text(logical_cells(table.rows[1])[1]),
        header_total=_parse_int(cell_text(logical_cells(table.rows[0])[1])),
        devices=devices,
        shipping=_parse_line(table.rows[SHIPPING_ROW]),
        blank_line=_parse_line(table.rows[BLANK_ROW]),
        supply_label=cell_text(logical_cells(table.rows[SUPPLY_ROW])[1]),
        supply_amount=_parse_int(cell_text(logical_cells(table.rows[SUPPLY_ROW])[5])),
        vat_label=cell_text(logical_cells(table.rows[VAT_ROW])[1]),
        vat=_parse_int(cell_text(logical_cells(table.rows[VAT_ROW])[5])),
        total_label=cell_text(logical_cells(table.rows[TOTAL_ROW])[1]),
        total=_parse_int(cell_text(logical_cells(table.rows[TOTAL_ROW])[5])),
        special_note=cell_text(logical_cells(table.rows[NOTE_ROW])[1]),
    )


def _check_static_text(parsed: ParsedDocument) -> None:
    template = parse_document(FORM_PATH)
    if parsed.company_lines != template.company_lines:
        raise EstimateError("회사 정보가 양식과 다릅니다.")
    if parsed.validity_line != template.validity_line or parsed.delivery_line != template.delivery_line:
        raise EstimateError("유효기간 또는 납품 예정 문구가 양식과 다릅니다.")
    if parsed.closing_line != template.closing_line:
        raise EstimateError("견적 문구가 양식과 다릅니다.")
    if parsed.special_note != template.special_note:
        raise EstimateError("특기사항이 양식과 다릅니다.")
    if "공급" not in parsed.supply_label.replace(" ", ""):
        raise EstimateError("공급가액 칸을 찾지 못했습니다.")
    if "부가" not in parsed.vat_label.replace(" ", ""):
        raise EstimateError("부가세 칸을 찾지 못했습니다.")
    if "합계" not in parsed.total_label.replace(" ", ""):
        raise EstimateError("합계 칸을 찾지 못했습니다.")


def _check_header(parsed: ParsedDocument) -> None:
    if not parsed.client_line or parsed.client_line.startswith("거래처") or " " not in parsed.client_line:
        raise EstimateError("거래처가 입력되지 않았습니다.")
    contact_name = parsed.contact_line.removesuffix("님 귀중").strip()
    if not parsed.contact_line.endswith("님 귀중") or contact_name in {"", "거래처"}:
        raise EstimateError("담당자가 입력되지 않았습니다.")
    if _DATE_LINE.fullmatch(parsed.date_line) is None:
        raise EstimateError("견적일이 입력되지 않았습니다.")
    product_name = parsed.product_line.split(":", 1)[-1].strip()
    if not parsed.product_line.startswith("품명") or not product_name:
        raise EstimateError("품명이 입력되지 않았습니다.")


def _check_arithmetic(parsed: ParsedDocument) -> None:
    if _line_filled(parsed.blank_line):
        raise EstimateError("빈 행에 값이 있습니다.")
    group_amounts: list[int] = []
    for serial, part, labor in parsed.devices:
        if not _group_used(serial, part, labor):
            continue
        _require_detail(part)
        _require_detail(labor)
        if serial.unit_price is not None:
            raise EstimateError("장비 행의 공급단가는 비워야 합니다.")
        if serial.amount != part.amount + labor.amount:
            raise EstimateError("장비 금액이 부품과 작업시간의 합과 다릅니다.")
        group_amounts.append(serial.amount or 0)
    shipping_amount = 0
    if _line_filled(parsed.shipping):
        _require_detail(parsed.shipping)
        shipping_amount = parsed.shipping.amount or 0
    if parsed.supply_amount is None or parsed.vat is None or parsed.total is None or parsed.header_total is None:
        raise EstimateError("합계 금액이 비어 있습니다.")
    if parsed.supply_amount != sum(group_amounts) + shipping_amount:
        raise EstimateError("공급가액이 행 합계와 다릅니다.")
    if parsed.vat != vat_amount(parsed.supply_amount):
        raise EstimateError("부가세가 공급가액의 10%와 다릅니다.")
    if parsed.total != parsed.supply_amount + parsed.vat:
        raise EstimateError("합계 금액이 공급가액과 부가세의 합과 다릅니다.")
    if parsed.header_total != parsed.total:
        raise EstimateError("상단 합계 금액이 합계와 다릅니다.")


def _check_matches(parsed: ParsedDocument, expected: CalculatedEstimate) -> None:
    if parsed.client_line != client_line(expected):
        raise EstimateError("거래처가 요청과 다릅니다.")
    if parsed.contact_line != contact_line(expected):
        raise EstimateError("담당자가 요청과 다릅니다.")
    if parsed.date_line != date_line(expected):
        raise EstimateError("견적일이 요청과 다릅니다.")
    if parsed.product_line != product_line(expected.product_name):
        raise EstimateError("품명이 요청과 다릅니다.")
    if parsed.supply_amount != expected.supply_amount or parsed.vat != expected.vat:
        raise EstimateError("합계 금액이 계산과 다릅니다.")
    if parsed.total != expected.total or parsed.header_total != expected.total:
        raise EstimateError("합계 금액이 계산과 다릅니다.")
    for index, device in enumerate(expected.devices):
        serial, part, labor = parsed.devices[index]
        _require_same(serial, device.serial_line)
        _require_same(part, device.part_line)
        _require_same(labor, device.labor_line)
    for serial, part, labor in parsed.devices[len(expected.devices) :]:
        if _group_used(serial, part, labor):
            raise EstimateError("사용하지 않는 장비 칸에 값이 있습니다.")
    if expected.shipping is None:
        if _line_filled(parsed.shipping):
            raise EstimateError("택배비 칸에 값이 있습니다.")
    else:
        _require_same(parsed.shipping, expected.shipping)


def _require_detail(line: ParsedLine) -> None:
    if line.qty is None or line.unit_price is None or line.amount is None:
        raise EstimateError("수량, 단가, 금액이 필요합니다.")
    if line.amount != line.qty * line.unit_price:
        raise EstimateError("행 금액이 수량과 단가의 곱과 다릅니다.")


def _require_same(parsed: ParsedLine, expected: MoneyLine) -> None:
    if parsed.description != expected.description or parsed.unit != expected.unit:
        raise EstimateError("견적 행이 요청과 다릅니다.")
    if parsed.qty != expected.qty or parsed.unit_price != expected.unit_price:
        raise EstimateError("견적 행이 요청과 다릅니다.")
    if parsed.amount != expected.amount or parsed.note != expected.note:
        raise EstimateError("견적 행이 요청과 다릅니다.")


def _group_used(serial: ParsedLine, part: ParsedLine, labor: ParsedLine) -> bool:
    return _line_filled(serial) or _line_filled(part) or _line_filled(labor)


def _line_filled(line: ParsedLine) -> bool:
    return bool(
        line.description
        or line.unit
        or line.note
        or line.qty is not None
        or line.unit_price is not None
        or line.amount is not None
    )


def _parse_line(row) -> ParsedLine:
    cells = logical_cells(row)
    return ParsedLine(
        description=cell_text(cells[1]),
        unit=cell_text(cells[2]),
        qty=_parse_int(cell_text(cells[3])),
        unit_price=_parse_int(cell_text(cells[4])),
        amount=_parse_int(cell_text(cells[5])),
        note=cell_text(cells[6]),
    )


def _parse_int(text: str) -> int | None:
    cleaned = text.replace("₩", "").replace(",", "").replace(" ", "").strip()
    if not cleaned:
        return None
    if not cleaned.isdigit():
        raise EstimateError("금액을 읽지 못했습니다.")
    return int(cleaned)
