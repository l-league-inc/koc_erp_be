from unittest.mock import patch

from django.test import TestCase
from ninja.schema import DjangoGetter

from user.models import User
from user.response import UserTinyResponseSchema


class TestUserTinyResponseSchema(TestCase):
    def test_none_user_validates_as_none(self) -> None:
        self.assertIsNone(UserTinyResponseSchema.model_validate(None))

    def test_django_getter_none_user_validates_as_none(self) -> None:
        getter = DjangoGetter(None, UserTinyResponseSchema)
        self.assertIsNone(UserTinyResponseSchema.model_validate(getter))

    def test_user_with_email_serializes(self) -> None:
        user = User.objects.create_user(
            email="tiny@example.com",
            password="password1234!",
        )
        schema = UserTinyResponseSchema.from_orm(user)
        self.assertEqual(schema.email, "tiny@example.com")
        self.assertEqual(schema.id, user.id)

    def test_user_tiny_skips_template_lookup_for_computed_fields(self) -> None:
        user = User.objects.create_user(
            email="lookup@example.com",
            password="password1234!",
        )
        looked_up: list[str] = []
        real_variable = __import__("django.template", fromlist=["Variable"]).Variable

        class TrackingVariable(real_variable):
            def __init__(self, var: str) -> None:
                looked_up.append(var)
                super().__init__(var)

        with patch("ninja.schema.Variable", TrackingVariable):
            UserTinyResponseSchema.from_orm(user)

        self.assertNotIn("password", looked_up)
