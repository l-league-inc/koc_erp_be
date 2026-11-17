from django.test import SimpleTestCase

from mcp_server.catalog import PUBLIC_ENDPOINTS, build_catalog


class DocumentCatalogTests(SimpleTestCase):
    def test_document_reads_and_download_are_exposed(self):
        endpoints = {(spec.method, spec.path) for spec in build_catalog()}
        expected = {
            ("GET", "/api/v1/document/{workspace_id}/space"),
            ("GET", "/api/v1/document/{workspace_id}/folder"),
            ("GET", "/api/v1/document/{workspace_id}/file"),
            ("GET", "/api/v1/document/{workspace_id}/file/search"),
            ("GET", "/api/v1/document/{workspace_id}/file/{file_id}"),
            ("GET", "/api/v1/document/{workspace_id}/file/{file_id}/mail"),
            ("POST", "/api/v1/document/{workspace_id}/file/{file_id}/download"),
        }
        self.assertTrue(expected <= endpoints)
        self.assertTrue(expected <= PUBLIC_ENDPOINTS)
        self.assertNotIn(
            ("DELETE", "/api/v1/document/{workspace_id}/file/{file_id}"),
            endpoints,
        )
        self.assertNotIn(
            ("POST", "/api/v1/document/{workspace_id}/file/{file_id}/reindex"),
            endpoints,
        )
        self.assertNotIn(("POST", "/api/v1/document/{workspace_id}/upload"), endpoints)
        self.assertNotIn(("POST", "/api/v1/document/{workspace_id}/file"), endpoints)

    def test_document_tools_explain_media_and_download_url(self):
        specs = {spec.path: spec for spec in build_catalog()}
        search = specs["/api/v1/document/{workspace_id}/file/search"]
        detail = specs["/api/v1/document/{workspace_id}/file/{file_id}"]
        download = specs["/api/v1/document/{workspace_id}/file/{file_id}/download"]
        self.assertIn("kind", search.input_schema["properties"]["query"]["properties"])
        for spec in (search, detail):
            self.assertIn("extracted_text", spec.description)
            self.assertIn("media_kind", spec.description)
            self.assertIn("개인 문서함 미디어", spec.description)
        self.assertNotIn("데이터를 만들 수 있습니다", download.description)
        self.assertIn("300초", download.description)
        self.assertIn("다운로드 이력", download.description)
        self.assertIn("extracted_text", download.description)
