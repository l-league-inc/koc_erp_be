from datetime import date

from ninja import Schema


class DeviceInput(Schema):
    serial: str
    part_name: str
    part_unit: str = "EA"
    part_qty: int
    part_unit_price: int
    labor_level: str
    labor_hours: int
    labor_unit_price: int


class EstimateDraft(Schema):
    client: str
    department: str
    contact: str
    issued_on: date
    product_name: str
    devices: list[DeviceInput]
    shipping_qty: int = 0
    shipping_unit_price: int = 0


class InstructionSchema(Schema):
    instruction: str
    model: str = ""


class EstimateDocumentSchema(Schema):
    filename: str
    content_type: str
    supply_amount: int
    vat: int
    total: int
    draft: EstimateDraft
    docx_base64: str


class EstimatePdfSchema(Schema):
    filename: str
    content_type: str
    supply_amount: int
    vat: int
    total: int
    draft: EstimateDraft
    pdf_base64: str


class EstimateSendSchema(Schema):
    draft: EstimateDraft
    to: list[str]
    subject: str = ""
    body: str = ""
    cc: list[str] = []
    bcc: list[str] = []


class EstimateSendResultSchema(Schema):
    sender: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
    filename: str
