from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from estimate.errors import EstimateError
from estimate.formio import DEVICE_COUNT
from estimate.schema import DeviceInput, EstimateDraft


@dataclass(frozen=True)
class MoneyLine:
    description: str
    unit: str
    qty: int
    unit_price: int | None
    amount: int
    note: str


@dataclass(frozen=True)
class DeviceLines:
    serial_line: MoneyLine
    part_line: MoneyLine
    labor_line: MoneyLine


@dataclass(frozen=True)
class CalculatedEstimate:
    client: str
    department: str
    contact: str
    issued_on: date
    product_name: str
    devices: tuple[DeviceLines, ...]
    shipping: MoneyLine | None
    supply_amount: int
    vat: int
    total: int


def format_amount(amount: int) -> str:
    return f"{amount:,}"


def format_header_total(amount: int) -> str:
    return f"₩ {amount:,}"


def format_issued_on(value: date) -> str:
    return f"{value.year}년 {value.month}월 {value.day}일"


def client_line(estimate: CalculatedEstimate) -> str:
    return f"{estimate.client} {estimate.department}"


def contact_line(estimate: CalculatedEstimate) -> str:
    return f"{estimate.contact} 님 귀중"


def date_line(estimate: CalculatedEstimate) -> str:
    return f"견적일자 : {format_issued_on(estimate.issued_on)}"


def product_line(name: str) -> str:
    return f"품명 : {name.strip()}"


def vat_amount(supply: int) -> int:
    amount = (Decimal(supply) * Decimal("0.1")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(amount)


def calculate(draft: EstimateDraft) -> CalculatedEstimate:
    _ensure_draft(draft)
    devices = tuple(_device_lines(device) for device in draft.devices)
    shipping = _shipping_line(draft.shipping_qty, draft.shipping_unit_price)
    supply = sum(device.serial_line.amount for device in devices)
    if shipping is not None:
        supply += shipping.amount
    vat = vat_amount(supply)
    return CalculatedEstimate(
        client=draft.client.strip(),
        department=draft.department.strip(),
        contact=draft.contact.strip(),
        issued_on=draft.issued_on,
        product_name=draft.product_name.strip(),
        devices=devices,
        shipping=shipping,
        supply_amount=supply,
        vat=vat,
        total=supply + vat,
    )


def _ensure_draft(draft: EstimateDraft) -> None:
    if not draft.client.strip() or not draft.department.strip():
        raise EstimateError("거래처와 부서가 필요합니다.")
    if not draft.contact.strip():
        raise EstimateError("담당자가 필요합니다.")
    if not draft.product_name.strip():
        raise EstimateError("품명이 필요합니다.")
    if not draft.devices:
        raise EstimateError("장비가 필요합니다.")
    if len(draft.devices) > DEVICE_COUNT:
        raise EstimateError("장비는 6대까지입니다.")
    for device in draft.devices:
        if not device.serial.strip():
            raise EstimateError("시리얼이 필요합니다.")
        if not device.part_name.strip():
            raise EstimateError("부품명이 필요합니다.")
        if device.labor_level.strip() not in {"상", "하"}:
            raise EstimateError("작업 난이도는 상 또는 하입니다.")
        if device.part_qty < 1:
            raise EstimateError("부품 수량은 1 이상이어야 합니다.")
        if device.labor_hours < 1:
            raise EstimateError("작업시간은 1 이상이어야 합니다.")
        if device.part_unit_price < 0 or device.labor_unit_price < 0:
            raise EstimateError("금액은 0 이상이어야 합니다.")
    if draft.shipping_qty < 0 or draft.shipping_unit_price < 0:
        raise EstimateError("금액은 0 이상이어야 합니다.")


def _device_lines(device: DeviceInput) -> DeviceLines:
    part_amount = device.part_qty * device.part_unit_price
    labor_amount = device.labor_hours * device.labor_unit_price
    part_unit = device.part_unit.strip() or "EA"
    part = MoneyLine(
        description=_part_description(device.part_name),
        unit=part_unit,
        qty=device.part_qty,
        unit_price=device.part_unit_price,
        amount=part_amount,
        note="부품가",
    )
    labor = MoneyLine(
        description=f"작업시간 : 난이도({device.labor_level.strip()})",
        unit="Hr",
        qty=device.labor_hours,
        unit_price=device.labor_unit_price,
        amount=labor_amount,
        note="작업시간",
    )
    serial = MoneyLine(
        description=_serial_description(device.serial),
        unit="EA",
        qty=1,
        unit_price=None,
        amount=part_amount + labor_amount,
        note="A/S",
    )
    return DeviceLines(serial_line=serial, part_line=part, labor_line=labor)


def _shipping_line(qty: int, unit_price: int) -> MoneyLine | None:
    if qty == 0:
        return None
    return MoneyLine(
        description="택배비",
        unit="EA",
        qty=qty,
        unit_price=unit_price,
        amount=qty * unit_price,
        note="",
    )


def _serial_description(serial: str) -> str:
    text = serial.strip()
    if text.startswith("품번"):
        return text
    return f"품번 : {text}"


def _part_description(name: str) -> str:
    text = name.strip()
    if text.startswith("1)") or text.startswith("1）"):
        return text
    return f"1) {text}"
