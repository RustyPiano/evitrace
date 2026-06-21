import re

from app.schemas_analysis import CitationCheck

CITATION_RE = re.compile(r"E-\d{4}")
SECTION_RE = re.compile(r"^##\s+", re.MULTILINE)
CONCLUSION_HEADING = "## 五、综合分析结论"


def ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def extract_conclusion_paragraphs(markdown: str) -> list[str]:
    start = markdown.find(CONCLUSION_HEADING)
    if start < 0:
        return []
    body_start = start + len(CONCLUSION_HEADING)
    next_match = SECTION_RE.search(markdown, body_start)
    body = markdown[body_start : next_match.start() if next_match else len(markdown)]
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()]


def validate_report_citations(markdown: str, valid_ids: set[str]) -> CitationCheck:
    used = ordered_unique(CITATION_RE.findall(markdown))
    invalid = sorted(citation for citation in used if citation not in valid_ids)
    paragraphs = extract_conclusion_paragraphs(markdown)
    cited = [paragraph for paragraph in paragraphs if CITATION_RE.search(paragraph)]
    coverage = len(cited) / len(paragraphs) if paragraphs else 1.0
    return CitationCheck(
        used_citations=used,
        invalid_citations=invalid,
        valid_citation_count=len([citation for citation in used if citation in valid_ids]),
        invalid_citation_count=len(invalid),
        citation_coverage=coverage,
        conclusion_paragraph_count=len(paragraphs),
        cited_conclusion_paragraph_count=len(cited),
    )
