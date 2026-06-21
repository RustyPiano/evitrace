import json
import re
from typing import Any

CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)
TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def strip_code_fence(text: str) -> str:
    match = CODE_FENCE_RE.match(text)
    return match.group(1).strip() if match else text.strip()


def extract_json_object_text(text: str) -> str:
    cleaned = strip_code_fence(text)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("no JSON object found")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : index + 1]

    raise ValueError("unterminated JSON object")


def repair_json_text(text: str) -> str:
    repaired = extract_json_object_text(text)
    previous = None
    while previous != repaired:
        previous = repaired
        repaired = TRAILING_COMMA_RE.sub(r"\1", repaired)
    return repaired


def loads_repaired_json(text: str) -> Any:
    return json.loads(repair_json_text(text))
