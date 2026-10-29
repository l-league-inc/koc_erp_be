from notice.models import Notice
from notice.outbound import NoticeResponseSchema
from user.models import User
from user.response import UserTinyResponseSchema
from user.schema import UserSignupSchema

from django.test import TestCase


def _json_schema_enums(node) -> set:
    found: set = set()
    if isinstance(node, dict):
        if "enum" in node and isinstance(node["enum"], list):
            found.update(node["enum"])
        for value in node.values():
            found |= _json_schema_enums(value)
    elif isinstance(node, list):
        for item in node:
            found |= _json_schema_enums(item)
    return found


class TestChoiceOpenApi(TestCase):
    def test_model_schema_exposes_django_choices(self) -> None:
        notice = NoticeResponseSchema.model_json_schema()
        self.assertTrue(
            set(Notice.TypeChoices.values).issubset(_json_schema_enums(notice))
        )
        self.assertIn("긴급공지", str(notice))

        user = UserTinyResponseSchema.model_json_schema()
        self.assertTrue(
            set(User.UserStatusChoice.values).issubset(_json_schema_enums(user))
        )
        self.assertIn("활성유저", str(user))

    def test_plain_schema_enum_field(self) -> None:
        signup = UserSignupSchema.model_json_schema()
        self.assertTrue(
            set(User.UserTypeChoices.values).issubset(_json_schema_enums(signup))
        )
        self.assertIn("회원", str(signup))
