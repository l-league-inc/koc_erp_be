from estimate.calculate import (
    CalculatedEstimate,
    MoneyLine,
    client_line,
    contact_line,
    date_line,
    format_amount,
    format_header_total,
    product_line,
)
from estimate.formio import (
    BLANK_ROW,
    DEVICE_COUNT,
    FIRST_DEVICE_ROW,
    FORM_PATH,
    SHIPPING_ROW,
    SUPPLY_ROW,
    TOTAL_ROW,
    VAT_ROW,
    load_document,
    logical_cells,
    save_document,
    set_cell_text,
    set_paragraph_text,
)


def render_document(estimate: CalculatedEstimate) -> bytes:
    document = load_document(FORM_PATH)
    _write_header(document, estimate)
    table = document.tables[1]
    _write_product(table.rows[1], estimate.product_name)
    _write_header_total(table.rows[0], estimate.total)
    for index, device in enumerate(estimate.devices):
        start = FIRST_DEVICE_ROW + index * 3
        _write_line(table.rows[start], device.serial_line)
        _write_line(table.rows[start + 1], device.part_line)
        _write_line(table.rows[start + 2], device.labor_line)
    for index in range(len(estimate.devices), DEVICE_COUNT):
        start = FIRST_DEVICE_ROW + index * 3
        _clear_line(table.rows[start])
        _clear_line(table.rows[start + 1])
        _clear_line(table.rows[start + 2])
    if estimate.shipping is None:
        _clear_line(table.rows[SHIPPING_ROW])
    else:
        _write_line(table.rows[SHIPPING_ROW], estimate.shipping)
    _clear_line(table.rows[BLANK_ROW])
    _write_amount(table.rows[SUPPLY_ROW], estimate.supply_amount)
    _write_amount(table.rows[VAT_ROW], estimate.vat)
    _write_amount(table.rows[TOTAL_ROW], estimate.total)
    return save_document(document)


def _write_header(document, estimate: CalculatedEstimate) -> None:
    paragraphs = document.tables[0].rows[0].cells[0].paragraphs
    set_paragraph_text(paragraphs[0], client_line(estimate))
    set_paragraph_text(paragraphs[1], contact_line(estimate))
    set_paragraph_text(paragraphs[2], date_line(estimate))


def _write_product(row, name: str) -> None:
    set_cell_text(logical_cells(row)[1], product_line(name))


def _write_header_total(row, total: int) -> None:
    set_cell_text(logical_cells(row)[1], format_header_total(total))


def _write_amount(row, amount: int) -> None:
    set_cell_text(logical_cells(row)[5], format_amount(amount))


def _write_line(row, line: MoneyLine) -> None:
    cells = logical_cells(row)
    set_cell_text(cells[1], line.description)
    set_cell_text(cells[2], line.unit)
    set_cell_text(cells[3], str(line.qty))
    set_cell_text(cells[4], "" if line.unit_price is None else format_amount(line.unit_price))
    set_cell_text(cells[5], format_amount(line.amount))
    set_cell_text(cells[6], line.note)


def _clear_line(row) -> None:
    for cell in logical_cells(row)[1:]:
        set_cell_text(cell, "")
