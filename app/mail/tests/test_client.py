from unittest.mock import MagicMock, patch

import smtplib
from django.test import SimpleTestCase
from ninja.errors import HttpError

from mail.daum import _smtp_login, send_message
from mail.servers import DAUM, NAVER


class SmtpLoginTests(SimpleTestCase):
    def test_daum_uses_ssl(self):
        client = MagicMock()
        with patch("mail.daum.smtplib.SMTP_SSL", return_value=client) as ssl:
            logged = _smtp_login("user", "secret", DAUM)
        self.assertIs(logged, client)
        ssl.assert_called_once()
        self.assertEqual(ssl.call_args.args[:2], ("smtp.daum.net", 465))
        client.login.assert_called_once_with("user", "secret")

    def test_naver_uses_starttls_on_587(self):
        client = MagicMock()
        client.has_extn.return_value = True
        with (
            patch("mail.daum.smtplib.SMTP", return_value=client) as plain,
            patch("mail.daum.smtplib.SMTP_SSL") as ssl,
        ):
            logged = _smtp_login("user", "secret", NAVER)
        self.assertIs(logged, client)
        plain.assert_called_once()
        self.assertEqual(plain.call_args.args[:2], ("smtp.naver.com", 587))
        client.starttls.assert_called_once()
        client.login.assert_called_once_with("user", "secret")
        ssl.assert_not_called()

    def test_naver_falls_back_to_ssl_when_starttls_is_missing(self):
        plain = MagicMock()
        plain.has_extn.return_value = False
        ssl_client = MagicMock()
        with (
            patch("mail.daum.smtplib.SMTP", return_value=plain),
            patch("mail.daum.smtplib.SMTP_SSL", return_value=ssl_client) as ssl,
        ):
            logged = _smtp_login("user", "secret", NAVER)
        self.assertIs(logged, ssl_client)
        self.assertEqual(ssl.call_args.args[:2], ("smtp.naver.com", 465))
        ssl_client.login.assert_called_once_with("user", "secret")

    def test_naver_auth_failure_does_not_fall_back(self):
        plain = MagicMock()
        plain.has_extn.return_value = True
        plain.login.side_effect = smtplib.SMTPAuthenticationError(535, b"no")
        with (
            patch("mail.daum.smtplib.SMTP", return_value=plain),
            patch("mail.daum.smtplib.SMTP_SSL") as ssl,
        ):
            with self.assertRaises(HttpError):
                _smtp_login("user", "secret", NAVER)
        ssl.assert_not_called()

    def test_sender_domain_follows_provider(self):
        client = MagicMock()
        with patch("mail.daum._smtp_login", return_value=client):
            daum_sent = send_message(
                "daumid",
                "secret",
                DAUM,
                to=["a@example.com"],
                subject="안녕",
                body="본문",
            )
            naver_sent = send_message(
                "naverid",
                "secret",
                NAVER,
                to=["a@example.com"],
                subject="안녕",
                body="본문",
            )
        self.assertEqual(daum_sent["sender"], "daumid@daum.net")
        self.assertEqual(naver_sent["sender"], "naverid@naver.com")
