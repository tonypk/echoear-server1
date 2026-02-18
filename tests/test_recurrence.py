"""Tests for app/recurrence.py — recurrence rule calculations."""
from datetime import datetime
from app.recurrence import calculate_next_occurrence, parse_recurrence_from_text


class TestCalculateNextOccurrence:
    def test_daily(self):
        base = datetime(2026, 2, 18, 10, 0, 0)
        result = calculate_next_occurrence(base, "daily")
        assert result == datetime(2026, 2, 19, 10, 0, 0)

    def test_daily_chinese(self):
        base = datetime(2026, 2, 18, 10, 0, 0)
        result = calculate_next_occurrence(base, "每天")
        assert result == datetime(2026, 2, 19, 10, 0, 0)

    def test_weekly(self):
        base = datetime(2026, 2, 18, 10, 0, 0)
        result = calculate_next_occurrence(base, "weekly")
        assert result == datetime(2026, 2, 25, 10, 0, 0)

    def test_weekly_chinese(self):
        base = datetime(2026, 2, 18, 10, 0, 0)
        result = calculate_next_occurrence(base, "每周")
        assert result == datetime(2026, 2, 25, 10, 0, 0)

    def test_monthly(self):
        base = datetime(2026, 2, 18, 10, 0, 0)
        result = calculate_next_occurrence(base, "monthly")
        assert result == datetime(2026, 3, 20, 10, 0, 0)  # +30 days

    def test_monthly_chinese(self):
        base = datetime(2026, 2, 18, 10, 0, 0)
        result = calculate_next_occurrence(base, "每月")
        assert result is not None

    def test_weekdays_from_friday(self):
        # 2026-02-20 is Friday
        base = datetime(2026, 2, 20, 9, 0, 0)
        result = calculate_next_occurrence(base, "weekdays")
        # Skip Sat(21), Sun(22), land on Monday(23)
        assert result == datetime(2026, 2, 23, 9, 0, 0)

    def test_weekdays_from_monday(self):
        # 2026-02-16 is Monday
        base = datetime(2026, 2, 16, 9, 0, 0)
        result = calculate_next_occurrence(base, "weekdays")
        # Next day is Tuesday
        assert result == datetime(2026, 2, 17, 9, 0, 0)

    def test_weekdays_chinese(self):
        base = datetime(2026, 2, 20, 9, 0, 0)
        result = calculate_next_occurrence(base, "工作日")
        assert result.weekday() < 5  # Mon-Fri

    def test_specific_time_future(self):
        base = datetime(2026, 2, 18, 7, 0, 0)
        result = calculate_next_occurrence(base, "08:00")
        assert result == datetime(2026, 2, 18, 8, 0, 0)

    def test_specific_time_past(self):
        base = datetime(2026, 2, 18, 10, 0, 0)
        result = calculate_next_occurrence(base, "08:00")
        # Time passed today → schedule tomorrow
        assert result == datetime(2026, 2, 19, 8, 0, 0)

    def test_specific_time_single_digit_hour(self):
        base = datetime(2026, 2, 18, 1, 0, 0)
        result = calculate_next_occurrence(base, "8:00")
        assert result == datetime(2026, 2, 18, 8, 0, 0)

    def test_invalid_rule(self):
        base = datetime(2026, 2, 18, 10, 0, 0)
        assert calculate_next_occurrence(base, "gibberish") is None

    def test_invalid_time_format(self):
        base = datetime(2026, 2, 18, 10, 0, 0)
        assert calculate_next_occurrence(base, "25:00") is None

    def test_rule_strip_whitespace(self):
        base = datetime(2026, 2, 18, 10, 0, 0)
        result = calculate_next_occurrence(base, "  daily  ")
        assert result == datetime(2026, 2, 19, 10, 0, 0)


class TestParseRecurrenceFromText:
    def test_daily_chinese(self):
        assert parse_recurrence_from_text("每天提醒我喝水") == "daily"

    def test_daily_with_time(self):
        assert parse_recurrence_from_text("每天8点提醒我吃药") == "08:00"

    def test_daily_with_time_afternoon(self):
        assert parse_recurrence_from_text("每天3点提醒我") == "03:00"

    def test_weekly(self):
        assert parse_recurrence_from_text("每周一早上9点开会") == "weekly"

    def test_monthly(self):
        assert parse_recurrence_from_text("每月提醒我交房租") == "monthly"

    def test_weekdays(self):
        assert parse_recurrence_from_text("工作日早上提醒我") == "weekdays"

    def test_no_recurrence(self):
        assert parse_recurrence_from_text("明天下午3点开会") is None

    def test_daily_english(self):
        assert parse_recurrence_from_text("daily reminder") == "daily"

    def test_weekly_english(self):
        assert parse_recurrence_from_text("weekly meeting") == "weekly"
