from django.http import HttpResponseNotFound
from django.test import RequestFactory, SimpleTestCase

from config.middleware import BlockScannerPathsMiddleware
from config.sentry_utils import (
    before_send,
    before_send_transaction,
    extract_request_path,
    is_scanner_request,
)


class TestScannerPathDetection(SimpleTestCase):
    def test_extract_request_path(self):
        self.assertEqual(extract_request_path("/.env"), "/.env")
        self.assertEqual(
            extract_request_path("https://api.example.com/.env?x=1"),
            "/.env",
        )

    def test_is_scanner_request_detects_common_paths(self):
        self.assertTrue(is_scanner_request("/.env"))
        self.assertTrue(is_scanner_request("/.env.local"))
        self.assertTrue(is_scanner_request("/.git/config"))
        self.assertTrue(is_scanner_request("/wp-admin/login.php"))

    def test_is_scanner_request_allows_normal_api_paths(self):
        self.assertFalse(is_scanner_request("/"))
        self.assertFalse(is_scanner_request("/api/v1/notice"))
        self.assertFalse(is_scanner_request("/api/health-checker"))

    def test_before_send_filters_scanner_events(self):
        event = {"request": {"url": "https://api.example.com/.env"}}
        self.assertIsNone(before_send(event, {}))

        normal_event = {"request": {"url": "https://api.example.com/api/v1/notice"}}
        self.assertEqual(before_send(normal_event, {}), normal_event)

    def test_before_send_transaction_filters_scanner_events(self):
        event = {"transaction": "/.env", "request": {"url": "/.env"}}
        self.assertIsNone(before_send_transaction(event, {}))

        normal_event = {
            "transaction": "GET /api/v1/notice",
            "request": {"url": "/api/v1/notice"},
        }
        self.assertEqual(before_send_transaction(normal_event, {}), normal_event)


class TestBlockScannerPathsMiddleware(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = BlockScannerPathsMiddleware(lambda request: HttpResponseNotFound())

    def test_blocks_env_scan(self):
        request = self.factory.get("/.env")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 404)

    def test_allows_normal_request(self):
        request = self.factory.get("/api/v1/notice")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 404)
