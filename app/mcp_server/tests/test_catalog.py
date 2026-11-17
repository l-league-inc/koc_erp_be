from django.test import SimpleTestCase

from mcp_server.catalog import (
    OPEN_WORLD_POSTS,
    PUBLIC_ENDPOINTS,
    VIEW_COUNT_GETS,
    build_catalog,
    tool_safety,
)
from mcp_server.server import _annotations, _meta


class CatalogFilterTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.specs = build_catalog()
        cls.endpoints = {(spec.method, spec.path) for spec in cls.specs}

    def test_includes_notice_and_me(self):
        self.assertIn(("GET", "/api/v1/notice"), self.endpoints)
        self.assertIn(("GET", "/api/v1/auth/me"), self.endpoints)

    def test_excludes_admin_payment_auth_and_writes(self):
        forbidden_prefixes = (
            "/api/v1/payment",
            "/api/v1/verify",
            "/api/v1/scheduling",
            "/api/v1/google-analytics",
            "/api/v1/lab",
            "/api/v1/product/secret",
            "/api/v1/kakao",
            "/api/v1/apple",
            "/api/v1/toss",
        )
        for method, path in self.endpoints:
            if method == "PATCH":
                self.assertIn(
                    path,
                    {
                        "/api/v1/workspace/record/{record_id}",
                        "/api/v1/workbot/{workbot_id}",
                    },
                )
            else:
                self.assertIn(method, {"GET", "POST"})
            self.assertFalse(
                any(path == prefix or path.startswith(prefix + "/") for prefix in forbidden_prefixes),
                path,
            )
            self.assertNotIn("{user_id}", path)
        self.assertNotIn(("POST", "/api/v1/auth/login"), self.endpoints)
        self.assertNotIn(("PATCH", "/api/v1/todo/{todo_id}"), self.endpoints)
        self.assertNotIn(("DELETE", "/api/v1/todo/{todo_id}"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/generate"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/train"), self.endpoints)
        self.assertNotIn(("GET", "/api/v1/cost/admin"), self.endpoints)
        self.assertNotIn(("GET", "/api/v1/myrealtrip/v1/revenues"), self.endpoints)
        self.assertNotIn(("GET", "/api/v1/notification/test"), self.endpoints)
        self.assertFalse(
            any("AI 메시지" in spec.summary for spec in self.specs)
        )

    def test_only_skill_endpoints_are_public(self):
        self.assertTrue(self.endpoints <= PUBLIC_ENDPOINTS)
        self.assertNotIn(("POST", "/api/v1/order"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/rental/order"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/rental/inquiry"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/aws/upload"), self.endpoints)

    def test_annotations_and_justifications(self):
        for spec in self.specs:
            safety = tool_safety(spec.method, spec.path)
            annotations = _annotations(spec)
            meta = _meta(spec)["justifications"]
            self.assertEqual(annotations.read_only_hint, safety["read_only"])
            self.assertEqual(annotations.open_world_hint, safety["open_world"])
            self.assertEqual(annotations.destructive_hint, safety["destructive"])
            self.assertEqual(annotations.idempotent_hint, safety["read_only"])
            self.assertTrue(meta["read_only_justification"])
            self.assertTrue(meta["open_world_justification"])
            self.assertTrue(meta["destructive_justification"])
            if (spec.method, spec.path) in OPEN_WORLD_POSTS:
                self.assertTrue(safety["open_world"])
                self.assertTrue(safety["destructive"])
            elif (spec.method, spec.path) in VIEW_COUNT_GETS:
                self.assertFalse(safety["read_only"])
                self.assertFalse(safety["destructive"])
            elif spec.method == "GET":
                self.assertTrue(safety["read_only"])
                self.assertFalse(safety["open_world"])
                self.assertFalse(safety["destructive"])

    def test_review_findings_match_real_side_effects(self):
        by_path = {(spec.method, spec.path): spec for spec in self.specs}
        self.assertNotIn(("GET", "/api/v1/flower"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/todo"), self.endpoints)
        for key in VIEW_COUNT_GETS:
            self.assertIn("조회수를 1", by_path[key].description)

    def test_auth_me_tells_email_and_name_without_user_id(self):
        spec = next(item for item in self.specs if item.path == "/api/v1/auth/me")
        self.assertIn("email", spec.description)
        self.assertIn("name", spec.description)
        self.assertIn("정수 사용자 id", spec.description)

    def test_workspace_tools_allow_read_create_update_not_delete(self):
        self.assertIn(("GET", "/api/v1/workspace"), self.endpoints)
        self.assertIn(("GET", "/api/v1/workspace/database"), self.endpoints)
        self.assertIn(
            ("GET", "/api/v1/workspace/database/{database_id}"),
            self.endpoints,
        )
        self.assertIn(("GET", "/api/v1/workspace/record/{record_id}"), self.endpoints)
        self.assertIn(("POST", "/api/v1/workspace/query"), self.endpoints)
        self.assertIn(
            ("POST", "/api/v1/workspace/database/{database_id}/record"),
            self.endpoints,
        )
        self.assertIn(("PATCH", "/api/v1/workspace/record/{record_id}"), self.endpoints)
        self.assertIn(("GET", "/api/v1/workspace/{workspace_id}/member"), self.endpoints)
        self.assertIn(("GET", "/api/v1/workbot"), self.endpoints)
        self.assertIn(("GET", "/api/v1/workbot/stats"), self.endpoints)
        self.assertIn(("GET", "/api/v1/workbot/run"), self.endpoints)
        self.assertIn(("POST", "/api/v1/workbot"), self.endpoints)
        self.assertIn(("PATCH", "/api/v1/workbot/{workbot_id}"), self.endpoints)
        self.assertIn(("POST", "/api/v1/workbot/{workbot_id}/run"), self.endpoints)
        self.assertNotIn(("DELETE", "/api/v1/workbot/{workbot_id}"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/workbot/draft"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/workbot/run/{run_id}/confirm"), self.endpoints)
        self.assertNotIn(("GET", "/api/v1/agent/session"), self.endpoints)
        self.assertNotIn(("GET", "/api/v1/agent/session/{session_id}"), self.endpoints)
        self.assertFalse(any(path.startswith("/api/v1/agent") for _method, path in self.endpoints))
        self.assertIn(("POST", "/api/v1/workspace/search"), self.endpoints)
        self.assertIn(("GET", "/api/v1/workspace/{workspace_id}/page"), self.endpoints)
        self.assertIn(("GET", "/api/v1/workspace/page/{page_id}"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/workspace/{workspace_id}/page"), self.endpoints)
        self.assertNotIn(("PATCH", "/api/v1/workspace/page/{page_id}"), self.endpoints)
        self.assertNotIn(("DELETE", "/api/v1/workspace/page/{page_id}"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/workspace/page/{page_id}/block"), self.endpoints)
        self.assertNotIn(("GET", "/api/v1/workspace/page/{page_id}/block"), self.endpoints)
        search = next(
            item for item in self.specs if (item.method, item.path) == ("POST", "/api/v1/workspace/search")
        )
        self.assertNotIn("데이터를 만들 수 있습니다", search.description)
        self.assertIn("저장하지 않습니다", search.description)
        self.assertIn("문서 페이지", search.description)
        safety = tool_safety(search.method, search.path)
        self.assertTrue(safety["read_only"])
        self.assertFalse(safety["open_world"])
        self.assertFalse(safety["destructive"])
        self.assertNotIn(("DELETE", "/api/v1/workspace/record/{record_id}"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/workspace/database"), self.endpoints)
        self.assertNotIn(
            ("PATCH", "/api/v1/workspace/database/{database_id}"),
            self.endpoints,
        )
        self.assertFalse(
            any(method == "DELETE" and path.startswith("/api/v1/workspace") for method, path in self.endpoints)
        )

    def test_estimate_json_tools_are_public(self):
        self.assertIn(("POST", "/api/v1/estimate/documents/json"), self.endpoints)
        self.assertIn(
            ("POST", "/api/v1/estimate/documents/from-instruction/json"),
            self.endpoints,
        )
        self.assertIn(("POST", "/api/v1/estimate/documents/pdf/json"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/estimate/documents"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/estimate/documents/from-instruction"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/estimate/documents/pdf"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/estimate/documents/send"), self.endpoints)
        spec = next(item for item in self.specs if item.path == "/api/v1/estimate/documents/json")
        self.assertIn("docx_base64", spec.description)
        self.assertIn("body", spec.input_schema["properties"])
        self.assertIn("devices", spec.input_schema["properties"]["body"]["properties"])
        safety = tool_safety(spec.method, spec.path)
        self.assertFalse(safety["read_only"])
        self.assertFalse(safety["open_world"])
        self.assertFalse(safety["destructive"])
        self.assertIn("저장소에는 쓰지 않습니다", safety["justifications"]["read_only_justification"])

    def test_web_search_is_public_read_of_the_open_web(self):
        self.assertIn(("POST", "/api/v1/search"), self.endpoints)
        self.assertFalse(any(path.startswith("/api/v1/agent") for _method, path in self.endpoints))
        spec = next(item for item in self.specs if item.path == "/api/v1/search")
        self.assertEqual(spec.method, "POST")
        self.assertEqual(spec.name, "post_api_v1_search")
        self.assertIn("body", spec.input_schema["properties"])
        self.assertIn("query", spec.input_schema["properties"]["body"]["properties"])
        self.assertIn("results", spec.description)
        safety = tool_safety(spec.method, spec.path)
        self.assertTrue(safety["read_only"])
        self.assertTrue(safety["open_world"])
        self.assertFalse(safety["destructive"])
        self.assertIn("워크스페이스에는 쓰지 않습니다", safety["justifications"]["read_only_justification"])
        self.assertIn("공개 웹을 조회합니다", safety["justifications"]["open_world_justification"])

    def test_tool_names_are_unique(self):
        names = [spec.name for spec in self.specs]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(names)
