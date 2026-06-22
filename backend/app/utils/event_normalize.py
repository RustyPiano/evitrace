import re
import unicodedata
from typing import Any


PUNCTUATION_RE = re.compile(r"[\s,，.。;；:：、\-_\[\]【】()（）]+")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return PUNCTUATION_RE.sub("", text)


def _alias_lookup(alias_map: dict[str, str] | None) -> dict[str, str]:
    if not alias_map:
        return {}
    return {_norm(surface): _norm(canonical) for surface, canonical in alias_map.items()}


def normalize_location_alias(value: Any, alias_map: dict[str, str] | None = None) -> str:
    normalized = _norm(value)
    if not normalized:
        return ""

    aliases = _alias_lookup(alias_map)
    return aliases.get(normalized, normalized)


def canonical_structured_key(event: dict[str, Any]) -> str:
    subject = _norm(event.get("subject"))
    action = _norm(event.get("action"))
    object_ = _norm(event.get("object"))

    if subject and (action or object_):
        return f"{subject}|{action}|{object_}"
    return ""


def canonical_event_key(event: dict[str, Any], alias_map: dict[str, str] | None = None) -> str:
    structured_key = canonical_structured_key(event)
    if structured_key:
        return structured_key

    event_key = _norm(event.get("event_key"))
    if event_key:
        return event_key
    return _norm(event.get("title"))


def group_events_for_conflict(
    events: list[dict[str, Any]],
    alias_map: dict[str, str] | None = None,
) -> list[list[dict[str, Any]]]:
    parent = list(range(len(events)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    first_by_event_key: dict[str, int] = {}
    first_by_structured_key: dict[str, int] = {}
    for index, event in enumerate(events):
        event_key = _norm(event.get("event_key"))
        if event_key:
            first = first_by_event_key.setdefault(event_key, index)
            union(first, index)

        structured_key = canonical_structured_key(event)
        if structured_key:
            first = first_by_structured_key.setdefault(structured_key, index)
            union(first, index)

    groups: dict[int, list[dict[str, Any]]] = {}
    for index, event in enumerate(events):
        groups.setdefault(find(index), []).append(event)

    return list(groups.values())
