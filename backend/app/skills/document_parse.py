import re
from time import perf_counter
from typing import Any

from .base import SkillContext, SkillManifest, SkillResult
from .utils import original_file_path

MAX_BLOCK_CHARS = 1000
SCANNED_PDF_WARNING = "PDF 未提取到文本，可能是扫描件"


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


def _chunk_text(text: str) -> list[tuple[str, int, int]]:
    chunks: list[tuple[str, int, int]] = []
    for start in range(0, len(text), MAX_BLOCK_CHARS):
        raw = text[start : start + MAX_BLOCK_CHARS]
        if not raw.strip():
            continue
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        chunk_start = start + leading
        chunk_end = start + trailing
        chunks.append((text[chunk_start:chunk_end], chunk_start, chunk_end))
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
        for index, (content, start, end) in enumerate(_paragraph_spans(text), start=1):
            items.append(_evidence(content, None, index, start, end))
        return items

    def _parse_docx(self, path) -> list[dict]:
        from docx import Document

        document = Document(path)
        items: list[dict] = []
        paragraph_number = 0
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            paragraph_number += 1
            items.append(_evidence(text, None, paragraph_number, 0, len(text)))
        return items

    def _parse_pdf(self, path) -> tuple[list[dict], list[str]]:
        import fitz

        items: list[dict] = []
        with fitz.open(path) as document:
            for page_index, page in enumerate(document, start=1):
                text = page.get_text("text")
                # PDF offsets are page-relative; TXT/MD offsets are full-document offsets.
                for content, start, end in _chunk_text(text):
                    items.append(_evidence(content, page_index, None, start, end))

        warnings = [SCANNED_PDF_WARNING] if not items else []
        return items, warnings
