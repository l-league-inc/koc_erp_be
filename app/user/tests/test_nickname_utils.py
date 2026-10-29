from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from user.models import User
from user.nickname_utils import (
    MAX_NICKNAME_LENGTH,
    NICKNAME_ADJECTIVES,
    NICKNAME_NOUNS,
    build_nickname_candidate,
    generate_unique_nickname,
    get_users_without_nickname,
    is_missing_nickname,
    is_nickname_taken,
    user_has_nickname,
)


def assert_nickname_format(test_case: TestCase, nickname: str) -> None:
    test_case.assertGreater(len(nickname), 0)
    test_case.assertLessEqual(len(nickname), MAX_NICKNAME_LENGTH)

    if any(char.isdigit() for char in nickname):
        return

    adjective = next(
        (word for word in NICKNAME_ADJECTIVES if nickname.startswith(word)),
        None,
    )
    test_case.assertIsNotNone(
        adjective,
        f"닉네임이 형용사로 시작하지 않습니다: {nickname}",
    )

    remainder = nickname[len(adjective) :]
    matched_nouns = [noun for noun in NICKNAME_NOUNS if noun in remainder]
    test_case.assertGreaterEqual(
        len(matched_nouns),
        2,
        f"닉네임에 명사 2개가 포함되어야 합니다: {nickname}",
    )


class TestNicknameUtils(TestCase):
    def test_build_nickname_candidate_format(self):
        for _ in range(30):
            nickname = build_nickname_candidate()
            assert_nickname_format(self, nickname)

    def test_build_nickname_candidate_uses_two_different_nouns(self):
        with patch("user.nickname_utils.random.sample", return_value=["하늘", "바다"]):
            with patch("user.nickname_utils.random.choice", return_value="맑은"):
                nickname = build_nickname_candidate()

        self.assertEqual(nickname, "맑은하늘바다")

    def test_generate_unique_nickname_is_unique(self):
        nickname = generate_unique_nickname()

        assert_nickname_format(self, nickname)
        self.assertFalse(User.objects.filter(nickname=nickname).exists())

    def test_generate_unique_nickname_avoids_existing_nickname(self):
        existing_nickname = "행복한부케하트"
        User.objects.create_user(
            email="existing@example.com",
            password="password123",
            nickname=existing_nickname,
        )

        for _ in range(20):
            nickname = generate_unique_nickname()
            self.assertNotEqual(nickname, existing_nickname)

    def test_generate_unique_nickname_respects_exclude_user_id(self):
        user = User.objects.create_user(
            email="exclude@example.com",
            password="password123",
            nickname="행복한부케하트",
        )

        with patch(
            "user.nickname_utils.build_nickname_candidate",
            return_value="행복한부케하트",
        ):
            nickname = generate_unique_nickname(exclude_user_id=user.id)

        self.assertEqual(nickname, "행복한부케하트")
        self.assertTrue(is_nickname_taken("행복한부케하트"))
        self.assertFalse(
            is_nickname_taken("행복한부케하트", exclude_user_id=user.id)
        )

    def test_generate_unique_nickname_uses_numeric_suffix_when_candidates_taken(self):
        def taken_side_effect(nickname: str, exclude_user_id: int | None = None) -> bool:
            return not any(char.isdigit() for char in nickname)

        with patch(
            "user.nickname_utils.build_nickname_candidate",
            return_value="행복한부케하트",
        ):
            with patch(
                "user.nickname_utils.is_nickname_taken",
                side_effect=taken_side_effect,
            ):
                with patch("user.nickname_utils.random.randint", return_value=5678):
                    nickname = generate_unique_nickname()

        self.assertTrue(nickname.endswith("5678"))
        self.assertLessEqual(len(nickname), MAX_NICKNAME_LENGTH)

    def test_is_nickname_taken(self):
        user = User.objects.create_user(
            email="taken@example.com",
            password="password123",
            nickname="테스트닉네임하나",
        )

        self.assertTrue(is_nickname_taken("테스트닉네임하나"))
        self.assertFalse(is_nickname_taken("없는닉네임"))
        self.assertFalse(
            is_nickname_taken("테스트닉네임하나", exclude_user_id=user.id)
        )

    def test_is_missing_nickname(self):
        self.assertTrue(is_missing_nickname(None))
        self.assertTrue(is_missing_nickname(""))
        self.assertTrue(is_missing_nickname("   "))
        self.assertFalse(is_missing_nickname("테스트닉네임둘"))

    def test_user_has_nickname(self):
        user_with_nickname = User(
            email="with@example.com",
            nickname="테스트닉네임둘",
        )
        user_without_nickname = User(email="without@example.com", nickname=None)
        user_with_blank_nickname = User(email="blank@example.com", nickname="  ")

        self.assertTrue(user_has_nickname(user_with_nickname))
        self.assertFalse(user_has_nickname(user_without_nickname))
        self.assertFalse(user_has_nickname(user_with_blank_nickname))

    def test_get_users_without_nickname(self):
        with_nickname = User.objects.create_user(
            email="with@example.com",
            password="password123",
            nickname="직접설정닉네임",
        )
        without_nickname = User.objects.create_user(
            email="without@example.com",
            password="password123",
        )
        User.objects.filter(pk=without_nickname.pk).update(nickname=None)

        blank_nickname = User.objects.create_user(
            email="blank@example.com",
            password="password123",
        )
        User.objects.filter(pk=blank_nickname.pk).update(nickname="")

        queryset = get_users_without_nickname()
        user_ids = set(queryset.values_list("id", flat=True))

        self.assertNotIn(with_nickname.id, user_ids)
        self.assertIn(without_nickname.id, user_ids)
        self.assertIn(blank_nickname.id, user_ids)


class TestCreateUserNickname(TestCase):
    def test_create_user_auto_assigns_nickname_when_missing(self):
        user = User.objects.create_user(
            email="auto@example.com",
            password="password1234!",
        )

        self.assertFalse(is_missing_nickname(user.nickname))
        assert_nickname_format(self, user.nickname)

    def test_create_user_keeps_explicit_nickname(self):
        user = User.objects.create_user(
            email="manual@example.com",
            password="password1234!",
            nickname="내가정한닉네임",
        )

        self.assertEqual(user.nickname, "내가정한닉네임")

    def test_create_user_generates_nickname_for_blank_string(self):
        user = User.objects.create_user(
            email="blank@example.com",
            password="password1234!",
            nickname="   ",
        )

        self.assertFalse(is_missing_nickname(user.nickname))
        assert_nickname_format(self, user.nickname)
        self.assertNotEqual(user.nickname.strip(), "")


class TestGenerateNicknamesCommand(TestCase):
    def _create_user_without_nickname(self, email: str) -> User:
        user = User.objects.create_user(
            email=email,
            password="password1234!",
        )
        User.objects.filter(pk=user.pk).update(nickname=None)
        user.refresh_from_db()
        return user

    def test_generatenicknames_dry_run_does_not_save(self):
        user = self._create_user_without_nickname("dryrun@example.com")
        out = StringIO()

        call_command("generatenicknames", "--dry-run", stdout=out)

        user.refresh_from_db()
        self.assertTrue(is_missing_nickname(user.nickname))
        self.assertIn("dry-run", out.getvalue())

    def test_generatenicknames_assigns_nickname(self):
        user = self._create_user_without_nickname("assign@example.com")
        out = StringIO()

        call_command("generatenicknames", stdout=out)

        user.refresh_from_db()
        self.assertFalse(is_missing_nickname(user.nickname))
        assert_nickname_format(self, user.nickname)
        self.assertIn("assign@example.com", out.getvalue())

    def test_generatenicknames_skips_users_with_nickname(self):
        user = User.objects.create_user(
            email="skip@example.com",
            password="password1234!",
            nickname="유지할닉네임",
        )
        out = StringIO()

        call_command("generatenicknames", stdout=out)

        user.refresh_from_db()
        self.assertEqual(user.nickname, "유지할닉네임")

    def test_generatenicknames_when_no_targets(self):
        User.objects.all().delete()
        out = StringIO()

        call_command("generatenicknames", stdout=out)

        self.assertIn("닉네임이 없는 유저가 없습니다", out.getvalue())
