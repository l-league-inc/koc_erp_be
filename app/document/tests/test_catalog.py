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
