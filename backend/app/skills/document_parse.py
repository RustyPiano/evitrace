import re
from time import perf_counter
from typing import Any

from app.config import settings

from .base import SkillContext, SkillManifest, SkillResult
from .utils import original_file_path

SCANNED_PDF_WARNING = "PDF 未提取到文本，可能是扫描件"
BOUNDARY_PATTERN = re.compile(r"[\n。！？!?\.]")


def _evidence(content: str, page: int | None, paragraph: int | None, start: int, end: int) -> dict:
    return {
        "content": content,
        "modality": "text",
        "evidence_type": "paragraph",
        "locator": {
            "kind": "text",
            "page": page,
            "paragraph": paragraph,
            "char_start": start,
            "char_end": end,
        },
        "confidence": None,
    }


def _paragraph_spans(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    pattern = re.compile(r"(?:^|\n\s*\n)(?P<body>.*?)(?=\n\s*\n|\Z)", re.DOTALL)
    for match in pattern.finditer(text):
        body = match.group("body")
        if not body.strip():
            continue
        leading = len(body) - len(body.lstrip())
        trailing = len(body.rstrip())
        start = match.start("body") + leading
        end = match.start("body") + trailing
        spans.append((text[start:end], start, end))
    return spans


def _hard_split(text: str, base_start: int, max_chars: int) -> list[tuple[str, int, int]]:
    chunks: list[tuple[str, int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + max_chars, n)
        if end < n:
            window = text[i:end]
            min_boundary = int(max_chars * 0.6)
            boundary_end = None
            for match in BOUNDARY_PATTERN.finditer(window):
                if match.end() >= min_boundary:
                    boundary_end = match.end()
            if boundary_end is not None:
                end = i + boundary_end

        raw = text[i:end]
        if not raw.strip():
            i = end
            continue
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        chunk_start = i + leading
        chunk_end = i + trailing
        chunks.append((text[chunk_start:chunk_end], chunk_start, chunk_end))
        i = end
    return [(content, base_start + start, base_start + end) for content, start, end in chunks]


def _merge_to_chunks(
    spans: list[tuple[str, int, int]],
    target: int,
    max_chars: int,
    source: str | None = None,
) -> list[tuple[str, int, int]]:
    """Greedily merge consecutive paragraph spans into ~target-sized chunks.

    Chunk length is measured by the source span ``cur_end - cur_start`` (not the
    sum of paragraph text), so (a) merged chunks never exceed ``max_chars`` and
    (b) when ``source`` is given the content is the exact ``source[start:end]``
    slice — keeping the locator range a faithful pointer to ``content``. DOCX
    passes ``source=None`` (its offsets are synthetic, joined with "\\n\\n", whose
    length equals ``end - start``).
    """
    max_chars = max(max_chars, target)
    chunks: list[tuple[str, int, int]] = []
    cur: list[str] = []
    cur_start: int | None = None
    cur_end: int | None = None

    def flush() -> None:
        nonlocal cur, cur_start, cur_end
        if cur and cur_start is not None and cur_end is not None:
            content = source[cur_start:cur_end] if source is not None else "\n\n".join(cur)
            chunks.append((content, cur_start, cur_end))
        cur = []
        cur_start = None
        cur_end = None

    for text, start, end in spans:
        if len(text) > max_chars:
            flush()
            chunks.extend(_hard_split(text, start, max_chars))
            continue
        if cur and cur_start is not None:
            projected_len = end - cur_start
            current_len = (cur_end or cur_start) - cur_start
            if projected_len > max_chars or current_len >= target:
                flush()
        if not cur:
            cur_start = start
        cur.append(text)
        cur_end = end

    flush()
    return chunks


class DocumentParseSkill:
    manifest = SkillManifest(
        id="document_parse",
        name="文档解析",
        version="1.0.0",
        description="解析 TXT、MD、PDF 和 DOCX，并生成文本证据",
        enabled_by_default=True,
        required=False,
        input_types=["txt", "md", "pdf", "docx"],
        output_type="evidence_list",
    )

    def run(self, context: SkillContext, payload: Any) -> SkillResult:
        started = perf_counter()
        file_info = payload["file"]
        try:
            path = original_file_path(context, file_info)
            extension = file_info["extension"]
            if extension in {"txt", "md"}:
                evidence = self._parse_text(path)
                warnings: list[str] = []
            elif extension == "docx":
                evidence = self._parse_docx(path)
                warnings = []
            elif extension == "pdf":
                evidence, warnings = self._parse_pdf(path)
            else:
                return SkillResult(
                    success=False,
                    errors=[f"document_parse 不支持 {extension}"],
                    data={"evidence": []},
                )
        except Exception as exc:
            return SkillResult(
                success=False,
                errors=[f"文档解析失败: {type(exc).__name__}: {exc}"],
                data={"evidence": []},
                metrics={"duration_ms": int((perf_counter() - started) * 1000)},
            )

        return SkillResult(
            success=True,
            warnings=warnings,
            data={"evidence": evidence},
            metrics={"duration_ms": int((perf_counter() - started) * 1000), "evidence_count": len(evidence)},
        )

    def _parse_text(self, path) -> list[dict]:
        from charset_normalizer import from_path

        match = from_path(path).best()
        text = str(match) if match is not None else path.read_text(encoding="utf-8", errors="replace")
        items: list[dict] = []
        chunks = _merge_to_chunks(
            _paragraph_spans(text),
            settings.parse_chunk_target_chars,
            settings.parse_chunk_max_chars,
            source=text,
        )
        for index, (content, start, end) in enumerate(chunks, start=1):
            items.append(_evidence(content, None, index, start, end))
        return items

    def _parse_docx(self, path) -> list[dict]:
        from docx import Document

        document = Document(path)
        items: list[dict] = []
        spans: list[tuple[str, int, int]] = []
        offset = 0
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            start = offset
            end = offset + len(text)
            spans.append((text, start, end))
            offset = end + 2
        chunks = _merge_to_chunks(
            spans,
            settings.parse_chunk_target_chars,
            settings.parse_chunk_max_chars,
        )
        for index, (content, start, end) in enumerate(chunks, start=1):
            items.append(_evidence(content, None, index, start, end))
        return items

    def _parse_pdf(self, path) -> tuple[list[dict], list[str]]:
        import fitz

        items: list[dict] = []
        with fitz.open(path) as document:
            for page_index, page in enumerate(document, start=1):
                text = page.get_text("text")
                chunks = _merge_to_chunks(
                    _paragraph_spans(text),
                    settings.parse_chunk_target_chars,
                    settings.parse_chunk_max_chars,
                    source=text,
                )
                # PDF offsets are page-relative; TXT/MD offsets are full-document offsets.
                for content, start, end in chunks:
                    items.append(_evidence(content, page_index, None, start, end))

        warnings = [SCANNED_PDF_WARNING] if not items else []
        return items, warnings
