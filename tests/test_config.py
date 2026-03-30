from datetime import UTC, timedelta

import pytest

from claude_session_index.config import parse_duration, since_cutoff, until_cutoff


class TestParseDuration:
    def test_days(self):
        assert parse_duration("7d") == timedelta(days=7)

    def test_hours(self):
        assert parse_duration("24h") == timedelta(hours=24)

    def test_minutes(self):
        assert parse_duration("30m") == timedelta(minutes=30)

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("abc")

    def test_no_unit_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("7")


class TestSinceCutoff:
    def test_duration_string(self):
        cutoff = since_cutoff("1d")
        from datetime import datetime

        now = datetime.now(UTC)
        diff = now - cutoff
        assert 86390 < diff.total_seconds() < 86410

    def test_iso_date(self):
        cutoff = since_cutoff("2026-03-01")
        assert cutoff.year == 2026
        assert cutoff.month == 3
        assert cutoff.day == 1


class TestUntilCutoff:
    def test_iso_date(self):
        cutoff = until_cutoff("2026-03-30")
        assert cutoff.year == 2026
        assert cutoff.month == 3
        assert cutoff.day == 30

    def test_iso_datetime(self):
        cutoff = until_cutoff("2026-03-30T18:00:00")
        assert cutoff.hour == 18

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="not a valid ISO date"):
            until_cutoff("garbage")
