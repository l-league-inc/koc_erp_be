from unittest.mock import patch

from django.test import SimpleTestCase

from estimate.calculate import calculate
from estimate.compose import draft_from_instruction, draft_from_payload
from estimate.errors import EstimateError
from estimate.service import build_from_instruction
from estimate.tests.samples import example_payload
from estimate.validate import parse_document


class ComposeTests(SimpleTestCase):
    def test_model_totals_are_ignored(self):
        payload = example_payload()
        payload["total"] = 1
        payload["supply_amount"] = 9
        payload["vat"] = 9
        payload["devices"][0]["amount"] = 1
        payload["devices"][0]["part_unit_price"] = "260,000"
        draft = draft_from_payload(payload)
        result = calculate(draft)
        self.assertEqual(result.supply_amount, 616000)
        self.assertEqual(result.vat, 61600)
        self.assertEqual(result.total, 677600)

    def test_omitted_shipping_stays_empty(self):
        payload = example_payload()
        payload["devices"] = payload["devices"][:1]
        payload["shipping_qty"] = None
        payload["shipping_unit_price"] = None
        draft = draft_from_payload(payload)
        result = calculate(draft)
        self.assertIsNone(result.shipping)
        self.assertEqual(result.supply_amount, 320000)
        self.assertEqual(result.vat, 32000)
        self.assertEqual(result.total, 352000)

    def test_missing_price_is_rejected(self):
        payload = example_payload()
        payload["devices"][0]["part_unit_price"] = None
        with self.assertRaisesMessage(EstimateError, "부품 단가가 필요합니다."):
            draft_from_payload(payload)

    def test_empty_instruction_is_rejected(self):
        with self.assertRaisesMessage(EstimateError, "지시가 필요합니다."):
            draft_from_instruction(object(), "  ")

    def test_instruction_uses_calculated_document(self):
        payload = example_payload()
        payload["total"] = 999999
        with (
            patch("estimate.compose.llm.use_model", return_value="gpt-6-luna") as use_model,
            patch("estimate.compose.llm.complete_json", return_value=payload) as complete_json,
        ):
            content, draft = build_from_instruction(object(), "수원운영팀 견적서를 작성해줘")
        use_model.assert_called_once()
        complete_json.assert_called_once()
        parsed = parse_document(content)
        self.assertEqual(parsed.header_total, 677600)
        self.assertEqual(parsed.supply_amount, 616000)
        self.assertEqual(parsed.vat, 61600)
        self.assertEqual(calculate(draft).total, 677600)
        self.assertNotEqual(parsed.header_total, payload["total"])

    def test_routes_are_registered(self):
        from config.urls import base_api

        paths = []
        for prefix, router in base_api._routers:
            for path in router.path_operations:
                paths.append(f"/{prefix}{path}")
        self.assertIn("/api/v1/estimate/documents", paths)
        self.assertIn("/api/v1/estimate/documents/from-instruction", paths)
