from urllib.parse import quote

from asgiref.sync import sync_to_async
from django.http import HttpResponse
from ninja import Router
from ninja.errors import HttpError

from api.security import jwt_auth
from estimate import service
from estimate.errors import EstimateError
from estimate.schema import (
    EstimateDocumentSchema,
    EstimateDraft,
    EstimatePdfSchema,
    EstimateSendResultSchema,
    EstimateSendSchema,
    InstructionSchema,
)

router = Router(tags=["Estimate"])


@router.post(
    "/documents",
    summary="[C] 견적서 작성",
    description="양식에 행 금액과 부가세, 합계를 계산해 넣고 정합성을 확인한 뒤 docx를 반환합니다.",
    auth=jwt_auth,
)
async def create_document_api(request, payload: EstimateDraft):
    content = await sync_to_async(_document)(payload)
    return _response(content, payload.client, payload.issued_on)


@router.post(
    "/documents/from-instruction",
    summary="[C] 지시로 견적서 작성",
    description="자연어 지시에서 행을 만들고, 금액은 계산해 넣은 뒤 docx를 반환합니다. 말하지 않은 단가는 만들지 않습니다.",
    auth=jwt_auth,
)
async def create_document_from_instruction_api(request, payload: InstructionSchema):
    content, draft = await sync_to_async(_document_from_instruction)(
        request.auth,
        payload.instruction,
        payload.model,
    )
    return _response(content, draft.client, draft.issued_on)


@router.post(
    "/documents/json",
    summary="[C] 견적서 JSON 작성",
    description=(
        "양식에 금액을 계산해 넣고 정합성을 확인한 뒤 파일명, 합계, docx base64를 반환합니다. "
        "견적 레코드는 저장하지 않습니다. 금액 키는 받지 않습니다."
    ),
    response=EstimateDocumentSchema,
    auth=jwt_auth,
)
async def create_document_json_api(request, payload: EstimateDraft):
    return await sync_to_async(_document_payload)(payload)


@router.post(
    "/documents/from-instruction/json",
    summary="[C] 지시로 견적서 JSON 작성",
    description=(
        "자연어 지시에서 행만 만들고 금액은 계산합니다. 말하지 않은 단가는 만들지 않습니다. "
        "응답은 파일명, 합계, docx base64입니다. 견적 레코드는 저장하지 않습니다."
    ),
    response=EstimateDocumentSchema,
    auth=jwt_auth,
)
async def create_document_json_from_instruction_api(request, payload: InstructionSchema):
    return await sync_to_async(_document_payload_from_instruction)(
        request.auth,
        payload.instruction,
        payload.model,
    )


@router.post(
    "/documents/pdf",
    summary="[C] 견적서 PDF 작성",
    description="편집한 초안을 다시 계산하고 정합성을 확인한 뒤 PDF를 반환합니다.",
    auth=jwt_auth,
)
async def create_pdf_api(request, payload: EstimateDraft):
    content = await sync_to_async(_pdf)(payload)
    filename = service.document_name(payload.client, payload.issued_on, "pdf")
    return _file_response(content, service.PDF_MIME, filename)


@router.post(
    "/documents/pdf/json",
    summary="[C] 견적서 PDF JSON 작성",
    description=(
        "편집한 초안을 다시 계산하고 정합성을 확인한 뒤 파일명, 합계, pdf base64를 반환합니다. "
        "견적 레코드는 저장하지 않습니다."
    ),
    response=EstimatePdfSchema,
    auth=jwt_auth,
)
async def create_pdf_json_api(request, payload: EstimateDraft):
    return await sync_to_async(_pdf_payload)(payload)


@router.post(
    "/documents/send",
    summary="[C] 견적서 메일 발송",
    description=(
        "편집한 초안으로 PDF를 만들고 등록된 Daum 계정에서 첨부해 보냅니다. "
        "받는 사람이 있을 때만 호출합니다. 견적 레코드는 저장하지 않습니다."
    ),
    response=EstimateSendResultSchema,
    auth=jwt_auth,
)
async def send_estimate_api(request, payload: EstimateSendSchema):
    return await sync_to_async(_send)(request.auth, payload)


def _document(payload: EstimateDraft) -> bytes:
    try:
        return service.build_document(payload)
    except EstimateError as exc:
        raise HttpError(400, str(exc)) from None


def _document_from_instruction(user, instruction: str, model: str) -> tuple[bytes, EstimateDraft]:
    try:
        return service.build_from_instruction(user, instruction, model)
    except EstimateError as exc:
        raise HttpError(400, str(exc)) from None


def _document_payload(payload: EstimateDraft) -> dict:
    try:
        return service.document_payload(payload)
    except EstimateError as exc:
        raise HttpError(400, str(exc)) from None


def _document_payload_from_instruction(user, instruction: str, model: str) -> dict:
    try:
        return service.document_payload_from_instruction(user, instruction, model)
    except EstimateError as exc:
        raise HttpError(400, str(exc)) from None


def _pdf(payload: EstimateDraft) -> bytes:
    try:
        return service.build_pdf(payload)
    except EstimateError as exc:
        raise HttpError(400, str(exc)) from None


def _pdf_payload(payload: EstimateDraft) -> dict:
    try:
        return service.pdf_payload(payload)
    except EstimateError as exc:
        raise HttpError(400, str(exc)) from None


def _send(user, payload: EstimateSendSchema) -> dict:
    try:
        return service.send_estimate(user, payload)
    except EstimateError as exc:
        raise HttpError(400, str(exc)) from None


def _response(content: bytes, client: str, issued_on) -> HttpResponse:
    return _file_response(content, service.DOCX_MIME, service.document_name(client, issued_on))


def _file_response(content: bytes, content_type: str, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    return response
