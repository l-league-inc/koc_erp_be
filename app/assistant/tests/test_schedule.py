from datetime import datetime

from django.test import SimpleTestCase

from assistant.schedule import next_run_at, parse_cron


class ScheduleTests(SimpleTestCase):
    def test_rejects_bad_cron(self):
        with self.assertRaises(Exception):
            parse_cron("매일")
        with self.assertRaises(Exception):
            parse_cron("61 9 * * *")

    def test_next_daily_and_weekly(self):
        self.assertEqual(
            next_run_at("30 9 * * *", datetime(2026, 10, 30, 9, 30)),
            datetime(2026, 10, 31, 9, 30),
        )
        self.assertEqual(
            next_run_at("30 9 * * *", datetime(2026, 10, 30, 9, 29)),
            datetime(2026, 10, 30, 9, 30),
        )
        monday = next_run_at("0 10 * * 1", datetime(2026, 10, 25, 12, 0))
        self.assertEqual(monday, datetime(2026, 10, 26, 10, 0))
        self.assertEqual(monday.weekday(), 0)
