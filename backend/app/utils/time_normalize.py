from dataclasses import dataclass
from datetime import date, datetime, time
import re


SLASH_DATE_RE = re.compile(
    r"^(?P<year>\d{4})/(?P<month>\d{1,2})/(?P<day>\d{1,2})"
    r"(?:[ T](?P<hour>\d{1,2}):(?P<minute>\d{1,2})(?::(?P<second>\d{1,2}))?)?$"
)
TIME_ONLY_RE = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?$")
CHINESE_DATE_RE = re.compile(
    r"^(?:(?P<year>\d{4})年)?(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
    r"(?:\s*(?P<hour>\d{1,2})(?:[:：时])(?P<minute>\d{1,2})(?:[:：分]?(?P<second>\d{1,2}))?秒?)?$"
)


@dataclass(frozen=True)
class ParsedTime:
    kind: str
    value: datetime | date | time


def _int_group(match: re.Match[str], name: str, default: int = 0) -> int:
    raw = match.group(name)
    return default if raw is None else int(raw)


def parse_time_value(value: str | None, *, default_year: int | None = None) -> ParsedTime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")
    try:
        if len(normalized) == 10 and normalized[4] == "-" and normalized[7] == "-":
            return ParsedTime(kind="date", value=date.fromisoformat(normalized))
        return ParsedTime(kind="datetime", value=datetime.fromisoformat(normalized))
    except ValueError:
        pass

    slash_match = SLASH_DATE_RE.match(text)
    if slash_match:
        try:
            year = _int_group(slash_match, "year")
            month = _int_group(slash_match, "month")
            day = _int_group(slash_match, "day")
            if slash_match.group("hour") is None:
                return ParsedTime(kind="date", value=date(year, month, day))
            return ParsedTime(
                kind="datetime",
                value=datetime(
                    year,
                    month,
                    day,
                    _int_group(slash_match, "hour"),
                    _int_group(slash_match, "minute"),
                    _int_group(slash_match, "second"),
                ),
            )
        except ValueError:
            return None

    time_match = TIME_ONLY_RE.match(text)
    if time_match:
        try:
            return ParsedTime(
                kind="time",
                value=time(
                    _int_group(time_match, "hour"),
                    _int_group(time_match, "minute"),
                    _int_group(time_match, "second"),
                ),
            )
        except ValueError:
            return None

    chinese_match = CHINESE_DATE_RE.match(text)
    if chinese_match:
        try:
            year = int(chinese_match.group("year") or default_year or date.today().year)
            month = _int_group(chinese_match, "month")
            day = _int_group(chinese_match, "day")
            if chinese_match.group("hour") is None:
                return ParsedTime(kind="date", value=date(year, month, day))
            return ParsedTime(
                kind="datetime",
                value=datetime(
                    year,
                    month,
                    day,
                    _int_group(chinese_match, "hour"),
                    _int_group(chinese_match, "minute"),
                    _int_group(chinese_match, "second"),
                ),
            )
        except ValueError:
            return None

    return None
