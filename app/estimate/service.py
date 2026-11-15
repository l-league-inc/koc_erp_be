import base64

from estimate.calculate import CalculatedEstimate, calculate
from estimate.compose import draft_from_instruction
from estimate.render import render_document
from estimate.schema import EstimateDraft
from estimate.validate import verify_document

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def document_name(client: str, issued_on) -> str:
    safe_client = "".join(char for char in client if char not in '\\/:*?"<>|').strip() or "견적"
    return f"견적서_{safe_client}_{issued_on.isoformat()}.docx"


def build_document(draft: EstimateDraft) -> bytes:
    content, _calculated = _verified(draft)
    return content


def build_from_instruction(user, instruction: str, model: str = "") -> tuple[bytes, EstimateDraft]:
    draft = draft_from_instruction(user, instruction, model)
    return build_document(draft), draft


def document_payload(draft: EstimateDraft) -> dict:
    content, calculated = _verified(draft)
    return _payload(content, calculated)


def document_payload_from_instruction(user, instruction: str, model: str = "") -> dict:
    draft = draft_from_instruction(user, instruction, model)
    return document_payload(draft)


def _verified(draft: EstimateDraft) -> tuple[bytes, CalculatedEstimate]:
    calculated = calculate(draft)
    content = render_document(calculated)
    verify_document(content, calculated)
    return content, calculated


def _payload(content: bytes, calculated: CalculatedEstimate) -> dict:
    return {
        "filename": document_name(calculated.client, calculated.issued_on),
        "content_type": DOCX_MIME,
        "supply_amount": calculated.supply_amount,
        "vat": calculated.vat,
        "total": calculated.total,
        "docx_base64": base64.b64encode(content).decode("ascii"),
    }
