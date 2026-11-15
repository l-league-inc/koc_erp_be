from django.test import SimpleTestCase

from estimate.calculate import calculate, vat_amount
from estimate.errors import EstimateError
from estimate.schema import DeviceInput, EstimateDraft
from estimate.tests.samples import example_draft, example_payload


class CalculateTests(SimpleTestCase):
    def test_example_totals(self):
        result = calculate(example_draft())

        self.assertEqual([device.serial_line.amount for device in result.devices], [320000, 40000, 40000, 40000, 40000, 40000])
        self.assertEqual(result.devices[0].part_line.amount, 260000)
        self.assertEqual(result.devices[0].labor_line.amount, 60000)
        self.assertIsNone(result.devices[0].serial_line.unit_price)
        self.assertEqual(result.shipping.amount, 96000)
        self.assertEqual(result.supply_amount, 616000)
        self.assertEqual(result.vat, 61600)
        self.assertEqual(result.total, 677600)

    def test_vat_rounds_half_up(self):
        self.assertEqual(vat_amount(15), 2)
        self.assertEqual(vat_amount(5), 1)
        draft = EstimateDraft(
            client="케이",
            department="영업팀",
            contact="홍길동",
            issued_on="2026-01-02",
            product_name="샘플",
            devices=[
                DeviceInput(
                    serial="S/N-1",
                    part_name="부품",
                    part_qty=1,
                    part_unit_price=10,
                    labor_level="하",
                    labor_hours=1,
                    labor_unit_price=5,
                )
            ],
        )
        result = calculate(draft)
        self.assertEqual(result.supply_amount, 15)
        self.assertEqual(result.vat, 2)
        self.assertEqual(result.total, 17)

    def test_seven_devices_are_rejected(self):
        payload = example_payload()
        payload["devices"] = example_payload()["devices"] + [example_payload()["devices"][0]]
        payload["issued_on"] = "2026-11-10"
        draft = EstimateDraft(**payload)
        with self.assertRaisesMessage(EstimateError, "장비는 6대까지입니다."):
            calculate(draft)

    def test_blank_client_is_rejected(self):
        draft = example_draft()
        draft.client = "  "
        with self.assertRaisesMessage(EstimateError, "거래처와 부서가 필요합니다."):
            calculate(draft)

    def test_unknown_labor_level_is_rejected(self):
        draft = example_draft()
        draft.devices[0].labor_level = "중"
        with self.assertRaisesMessage(EstimateError, "작업 난이도는 상 또는 하입니다."):
            calculate(draft)
