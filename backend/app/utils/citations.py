import re
from typing import Any

from app.schemas_analysis import CitationCheck

CITATION_RE = re.compile(r"E-\d{4,}")
SECTION_RE = re.compile(r"^##\s+", re.MULTILINE)
CONCLUSION_HEADING_RE = re.compile(r"^##\s*五、\s*综合分析结论", re.MULTILINE)
TIMELINE_HEADING_RE = re.compile(r"^##\s*三、\s*事件时间线", re.MULTILINE)
CONFLICT_HEADING_RE = re.compile(r"^##\s*四、\s*主要冲突", re.MULTILINE)
FACT_SECTION_PATTERNS = [
    ("三、事件时间线", TIMELINE_HEADING_RE),
    ("四、主要冲突", CONFLICT_HEADING_RE),
]
FIELD_CITATION_KEYS = ("time_citation", "location_citation", "quantity_citation")


def ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def extract_section_body(markdown: str, heading_re: re.Pattern[str]) -> str:
    match = heading_re.search(markdown)
    if match is None:
        return ""
    body_start = match.end()
    next_match = SECTION_RE.search(markdown, body_start)
    return markdown[body_start : next_match.start() if next_match else len(markdown)]


def extract_conclusion_paragraphs(markdown: str) -> list[str]:
    body = extract_section_body(markdown, CONCLUSION_HEADING_RE)
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()]


def extract_fact_lines(markdown: str, heading_re: re.Pattern[str]) -> list[str]:
    body = extract_section_body(markdown, heading_re)
    return [line.strip() for line in body.splitlines() if line.strip()]


def field_citation_stats(events: list[dict[str, Any]]) -> dict[str, int | float | None]:
    total = 0
    explicit = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        for key in FIELD_CITATION_KEYS:
            citation = event.get(key)
            if not isinstance(citation, dict):
                continue
            if not citation.get("value"):
                continue
            total += 1
            if citation.get("citation_origin") == "explicit":
                explicit += 1

    # None means there were no field-level citations to evaluate.
    ratio = explicit / total if total else None
    return {
        "field_citation_total": total,
        "field_citation_explicit": explicit,
        "field_explicit_ratio": ratio,
    }


def validate_report_citations(markdown: str, valid_ids: set[str]) -> CitationCheck:
    used = ordered_unique(CITATION_RE.findall(markdown))
    invalid = sorted(citation for citation in used if citation not in valid_ids)
    paragraphs = extract_conclusion_paragraphs(markdown)
    cited = [paragraph for paragraph in paragraphs if CITATION_RE.search(paragraph)]
    coverage = len(cited) / len(paragraphs) if paragraphs else 1.0
    uncited_sections: list[str] = []
    uncited_fact_count = 0
    for section_name, heading_re in FACT_SECTION_PATTERNS:
        section_uncited = 0
        for line in extract_fact_lines(markdown, heading_re):
            line_citations = set(CITATION_RE.findall(line))
            if line_citations & valid_ids:
                continue
            section_uncited += 1
        if section_uncited:
            uncited_sections.append(section_name)
            uncited_fact_count += section_uncited

    return CitationCheck(
        used_citations=used,
        invalid_citations=invalid,
        valid_citation_count=len([citation for citation in used if citation in valid_ids]),
        invalid_citation_count=len(invalid),
        citation_coverage=coverage,
        conclusion_paragraph_count=len(paragraphs),
        cited_conclusion_paragraph_count=len(cited),
        uncited_sections=uncited_sections,
        uncited_fact_count=uncited_fact_count,
    )
