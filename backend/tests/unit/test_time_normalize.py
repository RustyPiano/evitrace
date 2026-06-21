from datetime import date, datetime, time

from app.utils.time_normalize import parse_time_value


def test_parse_time_value_accepts_slash_separated_datetime():
    parsed = parse_time_value("2026/06/01 14:00")

    assert parsed is not None
    assert parsed.kind == "datetime"
    assert parsed.value == datetime(2026, 6, 1, 14, 0)


def test_parse_time_value_accepts_space_separated_iso_datetime():
    parsed = parse_time_value("2026-06-01 14:00")

    assert parsed is not None
    assert parsed.kind == "datetime"
    assert parsed.value == datetime(2026, 6, 1, 14, 0)


def test_parse_time_value_accepts_time_only_value():
    parsed = parse_time_value("14:00")

    assert parsed is not None
    assert parsed.kind == "time"
    assert parsed.value == time(14, 0)


def test_parse_time_value_accepts_chinese_full_date_and_datetime():
    parsed_date = parse_time_value("2026年6月1日")
    parsed_datetime = parse_time_value("2026年6月1日14:00")

    assert parsed_date is not None
    assert parsed_date.kind == "date"
    assert parsed_date.value == date(2026, 6, 1)
    assert parsed_datetime is not None
    assert parsed_datetime.kind == "datetime"
    assert parsed_datetime.value == datetime(2026, 6, 1, 14, 0)


def test_parse_time_value_accepts_chinese_month_day_with_default_year():
    parsed = parse_time_value("6月1日14:00", default_year=2026)

    assert parsed is not None
    assert parsed.kind == "datetime"
    assert parsed.value == datetime(2026, 6, 1, 14, 0)


def test_parse_time_value_returns_none_for_invalid_value():
    assert parse_time_value("not a time") is None
