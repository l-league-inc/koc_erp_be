from datetime import date

from estimate.schema import DeviceInput, EstimateDraft


def example_devices() -> list[dict]:
    outlets = [
        "S/N-440PTK24900025",
        "S/N-LSP2305153",
        "S/N-LP21010143",
        "S/N-LSP2305144",
        "S/N-LP21010156",
    ]
    devices = [
        {
            "serial": "S/N-LP2201211",
            "part_name": "베터리 교체",
            "part_unit": "EA",
            "part_qty": 1,
            "part_unit_price": 260000,
            "labor_level": "상",
            "labor_hours": 3,
            "labor_unit_price": 20000,
        }
    ]
    for serial in outlets:
        devices.append(
            {
                "serial": serial,
                "part_name": "AC220 콘센트 교체",
                "part_unit": "EA",
                "part_qty": 1,
                "part_unit_price": 20000,
                "labor_level": "하",
                "labor_hours": 1,
                "labor_unit_price": 20000,
            }
        )
    return devices


def example_payload() -> dict:
    return {
        "client": "LG유플러스",
        "department": "수원운영팀",
        "contact": "김현전",
        "issued_on": "2026-11-10",
        "product_name": "ESLP-440P(기본형)",
        "devices": example_devices(),
        "shipping_qty": 6,
        "shipping_unit_price": 16000,
    }


def example_draft() -> EstimateDraft:
    payload = example_payload()
    payload["issued_on"] = date(2026, 11, 10)
    payload["devices"] = [DeviceInput(**device) for device in payload["devices"]]
    return EstimateDraft(**payload)
