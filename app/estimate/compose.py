import re
from datetime import date, datetime
from typing import Any

from assistant import llm

from estimate.errors import EstimateError
from estimate.formio import DEVICE_COUNT
from estimate.schema import EstimateDraft

_KOREAN_DATE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def draft_from_instruction(user, instruction: str, model: str = "") -> EstimateDraft:
    text = (instruction or "").strip()
    if not text:
        raise EstimateError("지시가 필요합니다.")
    chosen = llm.use_model(user, model)
    parsed = llm.complete_json(
        [
            {
                "role": "system",
                "content": (
                    "당신은 KOC 견적서 작성자입니다. JSON으로만 답합니다. "
                    "금액, 공급가액, 부가세, 합계는 계산하지 않고 그 키를 넣지 않습니다. "
                    "사용자가 말하지 않은 단가, 수량, 거래처, 부서, 담당자, 날짜, 품명, 난이도를 만들지 않습니다. "
                    "말하지 않은 값은 null입니다. "
                    "키는 client, department, contact, issued_on, product_name, devices, "
                    "shipping_qty, shipping_unit_price입니다. "
                    "issued_on은 YYYY-MM-DD입니다. "
                    "devices는 최대 6대이고 한 장비는 부품 한 줄과 작업시간 한 줄입니다. "
                    "장비 키는 serial, part_name, part_unit, part_qty, part_unit_price, "
                    "labor_level, labor_hours, labor_unit_price입니다. "
                    "part_unit을 말하지 않았으면 EA입니다. labor_level은 상 또는 하입니다. "
                    "serial에는 품번만 넣고 품번 접두어는 넣지 않습니다. "
                    "part_name에는 작업 이름만 넣고 1) 접두어는 넣지 않습니다. "
                    "택배 대수와 단가를 말했으면 shipping_qty와 shipping_unit_price에 넣습니다. "
                    "택배를 말하지 않았으면 shipping_qty는 0입니다."
                ),
            },
            {"role": "user", "content": text},
        ],
        model=chosen,
    )
    return draft_from_payload(parsed)


def draft_from_payload(payload: Any) -> EstimateDraft:
    if not isinstance(payload, dict):
        raise EstimateError("견적 항목을 해석하지 못했습니다.")
    devices_raw = payload.get("devices")
    if not isinstance(devices_raw, list) or not devices_raw:
        raise EstimateError("장비가 필요합니다.")
    if len(devices_raw) > DEVICE_COUNT:
        raise EstimateError("장비는 6대까지입니다.")
    raw_shipping_qty = payload.get("shipping_qty", 0)
    if raw_shipping_qty is None or raw_shipping_qty == "":
        raw_shipping_qty = 0
    shipping_qty = _count(raw_shipping_qty, "택배 수량", allow_zero=True)
    raw_shipping_price = payload.get("shipping_unit_price")
    if shipping_qty == 0 and (raw_shipping_price is None or raw_shipping_price == ""):
        raw_shipping_price = 0
    return EstimateDraft.model_validate(
        {
            "client": _text(payload.get("client"), "거래처가 필요합니다."),
            "department": _text(payload.get("department"), "부서가 필요합니다."),
            "contact": _text(payload.get("contact"), "담당자가 필요합니다."),
            "issued_on": _issued_on(payload.get("issued_on")),
            "product_name": _text(payload.get("product_name"), "품명이 필요합니다."),
            "devices": [_device(item) for item in devices_raw],
            "shipping_qty": shipping_qty,
            "shipping_unit_price": _money(raw_shipping_price, "택배 단가가 필요합니다."),
        }
    )


def _device(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise EstimateError("장비 항목을 해석하지 못했습니다.")
    unit = item.get("part_unit")
    if unit is None or str(unit).strip() == "":
        part_unit = "EA"
    else:
        part_unit = str(unit).strip()
    level = item.get("labor_level")
    if level is None or str(level).strip() == "":
        raise EstimateError("작업 난이도가 필요합니다.")
    return {
        "serial": _text(item.get("serial"), "시리얼이 필요합니다."),
        "part_name": _text(item.get("part_name"), "부품명이 필요합니다."),
        "part_unit": part_unit,
        "part_qty": _count(item.get("part_qty"), "부품 수량", allow_zero=False),
        "part_unit_price": _money(item.get("part_unit_price"), "부품 단가가 필요합니다."),
        "labor_level": str(level).strip(),
        "labor_hours": _count(item.get("labor_hours"), "작업시간", allow_zero=False),
        "labor_unit_price": _money(item.get("labor_unit_price"), "작업 단가가 필요합니다."),
    }


def _text(value: Any, message: str) -> str:
    if value is None:
        raise EstimateError(message)
    text = str(value).strip()
    if not text or text.lower() == "null":
        raise EstimateError(message)
    return text


def _issued_on(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise EstimateError("견적일이 필요합니다.")
    text = value.strip()
    iso = text[:10] if "T" in text else text
    try:
        return date.fromisoformat(iso)
    except ValueError:
        pass
    matched = _KOREAN_DATE.fullmatch(text)
    if matched is None:
        raise EstimateError("견적일은 YYYY-MM-DD여야 합니다.")
    try:
        return date(int(matched.group(1)), int(matched.group(2)), int(matched.group(3)))
    except ValueError:
        raise EstimateError("견적일은 YYYY-MM-DD여야 합니다.") from None


def _count(value: Any, label: str, *, allow_zero: bool) -> int:
    number = _integer(value, f"{label}이 필요합니다.")
    if number < 0 or (number == 0 and not allow_zero):
        raise EstimateError(f"{label}은 1 이상이어야 합니다." if not allow_zero else f"{label}은 0 이상이어야 합니다.")
    return number


def _money(value: Any, missing: str) -> int:
    number = _integer(value, missing)
    if number < 0:
        raise EstimateError("금액은 0 이상이어야 합니다.")
    return number


def _integer(value: Any, missing: str) -> int:
    if isinstance(value, bool) or value is None or value == "":
        raise EstimateError(missing)
    if isinstance(value, float):
        if not value.is_integer():
            raise EstimateError("금액은 원 단위 정수여야 합니다.")
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if not cleaned.isdigit():
            raise EstimateError("금액은 원 단위 정수여야 합니다.")
        return int(cleaned)
    if isinstance(value, int):
        return value
    raise EstimateError(missing)
