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
        self.assertNotIn(("DELETE", "/api/v1/workspace/record/{record_id}"), self.endpoints)
        self.assertNotIn(("POST", "/api/v1/workspace/database"), self.endpoints)
        self.assertNotIn(
            ("PATCH", "/api/v1/workspace/database/{database_id}"),
            self.endpoints,
        )
        self.assertFalse(
            any(method == "DELETE" and path.startswith("/api/v1/workspace") for method, path in self.endpoints)
        )

    def test_tool_names_are_unique(self):
        names = [spec.name for spec in self.specs]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(names)
