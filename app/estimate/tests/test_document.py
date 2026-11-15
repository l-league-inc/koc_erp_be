import base64
from io import BytesIO
from unittest.mock import patch

from django.test import SimpleTestCase
from docx import Document

from estimate.calculate import calculate
from estimate.errors import EstimateError
from estimate.formio import (
    EXAMPLE_PATH,
    FORM_PATH,
    cell_text,
    load_document,
    logical_cells,
    set_cell_text,
)
from estimate.render import render_document
from estimate.schema import DeviceInput, EstimateDraft
from estimate.service import build_document, document_payload
from estimate.tests.samples import example_draft
from estimate.validate import parse_document, verify_document


class DocumentTests(SimpleTestCase):
    def test_example_file_passes(self):
        parsed = verify_document(EXAMPLE_PATH)
        self.assertEqual(parsed.client_line, "LG유플러스 수원운영팀")
        self.assertEqual(parsed.contact_line, "김현전 님 귀중")
        self.assertEqual(parsed.date_line, "견적일자 : 2026년 11월 10일")
        self.assertEqual(parsed.supply_amount, 616000)
        self.assertEqual(parsed.vat, 61600)
        self.assertEqual(parsed.total, 677600)
        self.assertEqual(parsed.header_total, 677600)

    def test_changed_amount_fails(self):
        document = Document(EXAMPLE_PATH)
        set_cell_text(logical_cells(document.tables[1].rows[3])[5], "1")
        buffer = BytesIO()
        document.save(buffer)
        with self.assertRaisesMessage(EstimateError, "행 금액이 수량과 단가의 곱과 다릅니다."):
            verify_document(buffer.getvalue())

    def test_render_matches_example_and_keeps_template_text(self):
        content = render_document(calculate(example_draft()))
        self.assertEqual(_item_rows(content), _item_rows(EXAMPLE_PATH))
        self.assertEqual(_header(content), _header(EXAMPLE_PATH))
        self.assertEqual(_company(content), _company(FORM_PATH))
        rendered = parse_document(content)
        template = parse_document(FORM_PATH)
        self.assertEqual(rendered.special_note, template.special_note)
        self.assertEqual(rendered.special_note, "* 수리 비용 산정은 폐사 2026년 A/S 처리 기준에 의함")
        verify_document(content, calculate(example_draft()))

    def test_unused_slots_stay_empty(self):
        draft = EstimateDraft(
            client="LG유플러스",
            department="수원운영팀",
            contact="김현전",
            issued_on="2026-11-10",
            product_name="ESLP-440P(기본형)",
            devices=[
                DeviceInput(
                    serial="S/N-1",
                    part_name="배터리 교체",
                    part_qty=1,
                    part_unit_price=1000,
                    labor_level="하",
                    labor_hours=1,
                    labor_unit_price=20000,
                )
            ],
        )
        content = build_document(draft)
        document = load_document(content)
        numbers = []
        for index in range(6):
            row = document.tables[1].rows[2 + index * 3]
            numbers.append(cell_text(logical_cells(row)[0]))
        self.assertEqual(numbers, ["1", "2", "3", "4", "5", "6"])
        parsed = parse_document(content)
        self.assertEqual(parsed.devices[0][0].amount, 21000)
        for serial, part, labor in parsed.devices[1:]:
            self.assertEqual(serial.description, "")
            self.assertEqual(part.description, "")
            self.assertEqual(labor.description, "")
        self.assertEqual(parsed.supply_amount, 21000)
        self.assertEqual(parsed.vat, 2100)
        self.assertIsNone(parsed.shipping.amount)

    def test_inconsistent_render_is_not_returned(self):
        def fake(_estimate):
            content = render_document(calculate(example_draft()))
            document = Document(BytesIO(content))
            set_cell_text(logical_cells(document.tables[1].rows[3])[5], "1")
            buffer = BytesIO()
            document.save(buffer)
            return buffer.getvalue()

        with patch("estimate.service.render_document", side_effect=fake):
            with self.assertRaises(EstimateError):
                build_document(example_draft())

    def test_json_payload_is_the_same_document(self):
        payload = document_payload(example_draft())
        self.assertEqual(payload["filename"], "견적서_LG유플러스_2026-11-10.docx")
        self.assertEqual(payload["supply_amount"], 616000)
        self.assertEqual(payload["vat"], 61600)
        self.assertEqual(payload["total"], 677600)
        parsed = verify_document(base64.b64decode(payload["docx_base64"]))
        self.assertEqual(parsed.header_total, 677600)
        self.assertEqual(parsed.client_line, "LG유플러스 수원운영팀")

    def test_too_many_devices_do_not_render(self):
        draft = example_draft()
        draft.devices = list(draft.devices) + [draft.devices[0]]
        with patch("estimate.service.render_document") as render:
            with self.assertRaisesMessage(EstimateError, "장비는 6대까지입니다."):
                build_document(draft)
            render.assert_not_called()


def _item_rows(source) -> list[tuple[str, ...]]:
    document = load_document(source)
    return [tuple(cell_text(cell) for cell in logical_cells(row)) for row in document.tables[1].rows]


def _header(source) -> tuple[str, ...]:
    paragraphs = load_document(source).tables[0].rows[0].cells[0].paragraphs
    return tuple(paragraph.text.strip() for paragraph in paragraphs)


def _company(source) -> tuple[str, ...]:
    paragraphs = load_document(source).tables[0].rows[0].cells[2].paragraphs
    return tuple(paragraph.text.strip() for paragraph in paragraphs)
