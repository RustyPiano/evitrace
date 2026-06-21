from pathlib import Path

from app.config import settings
from app.models import Task, TaskFile
from app.services.task_service import serialize_file
from app.skills.base import SkillContext
from app.skills.document_parse import DocumentParseSkill
from app.database import SessionLocal


def _task_file(path: Path, extension: str, modality: str = "document") -> TaskFile:
    task_id = path.parents[1].name
    with SessionLocal() as db:
        task = Task(name="Parse", objective="Objective", owner_id="owner", status="ready")
        task.id = task_id
        db.add(task)
        file = TaskFile(
            task_id=task_id,
            original_name=path.name,
            stored_name=path.name,
            extension=extension,
            mime_type=None,
            size_bytes=path.stat().st_size,
            modality=modality,
        )
        db.add(file)
        db.commit()
        db.refresh(file)
        return file


def _context(task_id: str) -> SkillContext:
    return SkillContext(task_id=task_id, run_id=None, data_root=str(settings.data_root_path))


def test_txt_parse_splits_on_blank_lines_and_skips_empty_blocks(tmp_path):
    task_id = "txt-task"
    original_dir = settings.data_root_path / "tasks" / task_id / "original"
    original_dir.mkdir(parents=True)
    path = original_dir / "note.txt"
    path.write_text("Alpha paragraph\n\n\nBeta paragraph\n\n", encoding="utf-8")
    file = _task_file(path, "txt", "text")

    result = DocumentParseSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    evidence = result.data["evidence"]
    assert [item["content"] for item in evidence] == ["Alpha paragraph", "Beta paragraph"]
    assert evidence[0]["locator"] == {
        "kind": "text",
        "page": None,
        "paragraph": 1,
        "char_start": 0,
        "char_end": 15,
    }


def test_docx_parse_reads_non_empty_paragraphs(tmp_path):
    from docx import Document

    task_id = "docx-task"
    original_dir = settings.data_root_path / "tasks" / task_id / "original"
    original_dir.mkdir(parents=True)
    path = original_dir / "report.docx"
    document = Document()
    document.add_paragraph("First paragraph")
    document.add_paragraph("   ")
    document.add_paragraph("Second paragraph")
    document.save(path)
    file = _task_file(path, "docx")

    result = DocumentParseSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    evidence = result.data["evidence"]
    assert [item["content"] for item in evidence] == ["First paragraph", "Second paragraph"]
    assert evidence[1]["locator"]["paragraph"] == 2


def test_pdf_parse_preserves_page_numbers(tmp_path):
    import fitz

    task_id = "pdf-task"
    original_dir = settings.data_root_path / "tasks" / task_id / "original"
    original_dir.mkdir(parents=True)
    path = original_dir / "report.pdf"
    pdf = fitz.open()
    page1 = pdf.new_page()
    page1.insert_text((72, 72), "First page text")
    page2 = pdf.new_page()
    page2.insert_text((72, 72), "Second page text")
    pdf.save(path)
    pdf.close()
    file = _task_file(path, "pdf")

    result = DocumentParseSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    evidence = result.data["evidence"]
    assert [item["locator"]["page"] for item in evidence] == [1, 2]
    assert evidence[0]["content"] == "First page text"
    assert evidence[1]["content"] == "Second page text"


def test_scanned_pdf_without_text_returns_warning(tmp_path):
    import fitz

    task_id = "empty-pdf-task"
    original_dir = settings.data_root_path / "tasks" / task_id / "original"
    original_dir.mkdir(parents=True)
    path = original_dir / "empty.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.save(path)
    pdf.close()
    file = _task_file(path, "pdf")

    result = DocumentParseSkill().run(_context(task_id), {"file": serialize_file(file)})

    assert result.success is True
    assert result.data["evidence"] == []
    assert result.warnings == ["PDF 未提取到文本，可能是扫描件"]
