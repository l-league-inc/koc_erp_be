import base64

from estimate.calculate import CalculatedEstimate, calculate
from estimate.compose import draft_from_instruction
from estimate.pdf import PDF_MIME, render_pdf
from estimate.render import render_document
from estimate.schema import EstimateDraft, EstimateSendSchema
from estimate.validate import verify_document

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def document_name(client: str, issued_on, suffix: str = "docx") -> str:
    safe_client = "".join(char for char in client if char not in '\\/:*?"<>|').strip() or "견적"
    return f"견적서_{safe_client}_{issued_on.isoformat()}.{suffix}"


def build_document(draft: EstimateDraft) -> bytes:
    content, _calculated = _verified(draft)
    return content


def build_from_instruction(user, instruction: str, model: str = "") -> tuple[bytes, EstimateDraft]:
    draft = draft_from_instruction(user, instruction, model)
    return build_document(draft), draft


def document_payload(draft: EstimateDraft) -> dict:
    content, calculated = _verified(draft)
    return _payload(content, calculated, draft)


def document_payload_from_instruction(user, instruction: str, model: str = "") -> dict:
    draft = draft_from_instruction(user, instruction, model)
    return document_payload(draft)


def build_pdf(draft: EstimateDraft) -> bytes:
    content, calculated = _verified(draft)
    return render_pdf(content, calculated)


def pdf_payload(draft: EstimateDraft) -> dict:
    content, calculated = _verified(draft)
    pdf = render_pdf(content, calculated)
    return {
        "filename": document_name(calculated.client, calculated.issued_on, "pdf"),
        "content_type": PDF_MIME,
        "supply_amount": calculated.supply_amount,
        "vat": calculated.vat,
        "total": calculated.total,
        "draft": draft.model_dump(mode="json"),
        "pdf_base64": base64.b64encode(pdf).decode("ascii"),
    }


def send_estimate(user, payload: EstimateSendSchema) -> dict:
    content, calculated = _verified(payload.draft)
    pdf = render_pdf(content, calculated)
    filename = document_name(calculated.client, calculated.issued_on, "pdf")
    subject = payload.subject.strip() or f"견적서 {calculated.client} {calculated.issued_on.isoformat()}"
    body = payload.body.strip() or (
        f"{calculated.client} {calculated.department} 견적서를 첨부합니다.\n"
        f"합계 {calculated.total:,}원"
    )
    from mail.service import send_message

    result = send_message(
        user,
        to=payload.to,
        subject=subject,
        body=body,
        cc=payload.cc,
        bcc=payload.bcc,
        attachments=[(filename, pdf, PDF_MIME)],
    )
    return {**result, "filename": filename}


def _verified(draft: EstimateDraft) -> tuple[bytes, CalculatedEstimate]:
    calculated = calculate(draft)
    content = render_document(calculated)
    verify_document(content, calculated)
    return content, calculated


def _payload(content: bytes, calculated: CalculatedEstimate, draft: EstimateDraft) -> dict:
    return {
        "filename": document_name(calculated.client, calculated.issued_on),
        "content_type": DOCX_MIME,
        "supply_amount": calculated.supply_amount,
        "vat": calculated.vat,
        "total": calculated.total,
        "draft": draft.model_dump(mode="json"),
        "docx_base64": base64.b64encode(content).decode("ascii"),
    }
