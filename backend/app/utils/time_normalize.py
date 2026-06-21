from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class ParsedTime:
    kind: str
    value: datetime | date


def parse_time_value(value: str | None) -> ParsedTime | None:
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
        return None
