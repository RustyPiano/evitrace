#!/usr/bin/env python3
"""Run A/B evaluation: direct LLM report vs EviTrace evidence-chain pipeline."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import evaluate_demo


ROOT = evaluate_demo.ROOT
BACKEND_ROOT = evaluate_demo.BACKEND_ROOT
OUTPUT_PATH = ROOT / "scripts" / "ab_result.md"
ENV_TO_PRESERVE = [
    "MOCK_AI",
    "MOCK_LLM",
    "MOCK_MEDIA",
    "MOCK_VISION",
    "LOCAL_LLM_BASE_URL",
    "LOCAL_LLM_API_KEY",
    "LOCAL_LLM_MODEL",
    "LLM_TIMEOUT_SEC",
    "LLM_MAX_RETRIES",
    "VLM_BASE_URL",
    "VLM_API_KEY",
    "VLM_MODEL",
    "OCR_BASE_URL",
    "ASR_BASE_URL",
]
EVIDENCE_ID_RE = re.compile(r"E-\d{4,}")


def configure_ab_environment(temp_root: Path, preserved_env: dict[str, str | None]) -> None:
    evaluate_demo.configure_environment(temp_root)
    for key, value in preserved_env.items():
        if value is None:
            continue
        os.environ[key] = value


def normalized_text(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


def heuristic_conflict_recall(report_text: str, expected_conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_report = normalized_text(report_text)
    found = 0
    for expected in expected_conflicts:
        left = normalized_text(expected.get("left"))
        right = normalized_text(expected.get("right"))
        if left and right and left in normalized_report and right in normalized_report:
            found += 1
    total = len(expected_conflicts)
    return {"found": found, "total": total, "recall": found / total if total else 1.0}


def valid_citation_ratio(markdown: str, valid_ids: set[str]) -> dict[str, Any]:
    used = EVIDENCE_ID_RE.findall(markdown)
    valid = [citation for citation in used if citation in valid_ids]
    return {
        "used": len(used),
        "valid": len(valid),
        "ratio": len(valid) / len(used) if used else None,
    }


def split_paragraphs(markdown: str) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", markdown):
        cleaned = "\n".join(
            line.strip()
            for line in paragraph.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ).strip()
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def looks_like_fact_assertion(paragraph: str) -> bool:
    if EVIDENCE_ID_RE.search(paragraph):
        return False
    if re.search(r"\d|[:：]|[年月日时分辆个名处]", paragraph):
        return True
    return bool(
        re.search(
            r"\b(arrived|reported|observed|located|mentions|says|shows|indicates|conflict|vehicles?)\b",
            paragraph,
            flags=re.IGNORECASE,
        )
    )


def count_free_text_ungrounded_conclusions(report_text: str) -> int:
    return sum(1 for paragraph in split_paragraphs(report_text) if looks_like_fact_assertion(paragraph))


def matched_conflict_indexes(
    conflicts: list[dict[str, Any]],
    expected_conflicts: list[dict[str, Any]],
) -> set[int]:
    used_indexes: set[int] = set()
    for expected in expected_conflicts:
        for index, conflict in enumerate(conflicts):
            if index in used_indexes:
                continue
            if evaluate_demo.conflict_matches(conflict, expected):
                used_indexes.add(index)
                break
    return used_indexes


def format_ratio(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def run_b_case(client: Any, headers: dict[str, str], case_name: str, data_root: Path) -> dict[str, Any]:
    row = evaluate_demo.evaluate_case(client, headers, case_name, data_root)
    case_dir = evaluate_demo.DEMO_ROOT / case_name
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    expected_conflicts = list(expected.get("expected_conflicts") or [])

    results_response = client.get(f"/api/v1/tasks/{row['task_id']}/results", headers=headers)
    results_response.raise_for_status()
    results = results_response.json()["data"]

    evidence_response = client.get(f"/api/v1/tasks/{row['task_id']}/evidence?page_size=50", headers=headers)
    evidence_response.raise_for_status()
    evidence_items = evidence_response.json()["data"]["items"]
    run_id = results.get("run_id")
    full_evidence: list[dict[str, Any]] = []
    for item in evidence_items:
        detail_response = client.get(f"/api/v1/evidence/{item['id']}?run_id={run_id}", headers=headers)
        detail_response.raise_for_status()
        full_evidence.append(detail_response.json()["data"])

    valid_ids = {item["display_id"] for item in full_evidence}
    report_markdown = results.get("report_markdown") or ""

    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.utils.citations import validate_report_citations

    citation_check = validate_report_citations(report_markdown, valid_ids)
    citation_ratio = valid_citation_ratio(report_markdown, valid_ids)
    conflicts = list(results.get("conflicts") or [])
    matched_indexes = matched_conflict_indexes(conflicts, expected_conflicts)

    return {
        "case": case_name,
        "task_id": row["task_id"],
        "expected_conflicts": expected_conflicts,
        "evidence": full_evidence,
        "report_markdown": report_markdown,
        "conflict_recall": row["conflict_recall"],
        "conflict_found": row["found_conflict_count"],
        "conflict_total": row["expected_conflict_count"],
        "spurious_conflicts": len(conflicts) - len(matched_indexes),
        "valid_citation_ratio": citation_ratio["ratio"],
        "citation_used": citation_ratio["used"],
        "citation_valid": citation_ratio["valid"],
        "ungrounded_conclusions": (
            citation_check.conclusion_paragraph_count - citation_check.cited_conclusion_paragraph_count
        ),
        "task_status": row["task_status"],
        "run_status": row["run_status"],
    }


def build_direct_prompt(case_name: str, evidence: list[dict[str, Any]]) -> str:
    evidence_text = "\n\n".join(
        f"资料 {index}（{item.get('modality')}/{item.get('evidence_type')}）：\n{item.get('content') or ''}"
        for index, item in enumerate(evidence, start=1)
    )
    return (
        "请根据以下资料写一份情报分析报告。要求综合判断主要事实、可疑矛盾与结论，"
        "但不要使用任何外部资料。\n\n"
        f"案例：{case_name}\n\n"
        f"{evidence_text}"
    )


def run_a_case(case_name: str, expected_conflicts: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    from app.services.llm_client import LocalLLMClient

    client = LocalLLMClient()
    report_text = client.generate_text(
        "你是情报分析助手。根据用户给出的资料直接生成一份完整 Markdown 报告。",
        build_direct_prompt(case_name, evidence),
    )
    recall = heuristic_conflict_recall(report_text, expected_conflicts)
    evidence_ids = {item["display_id"] for item in evidence}
    citation_ratio = valid_citation_ratio(report_text, evidence_ids)
    return {
        "case": case_name,
        "report_markdown": report_text,
        "conflict_recall": recall["recall"],
        "conflict_found": recall["found"],
        "conflict_total": recall["total"],
        "valid_citation_ratio": citation_ratio["ratio"],
        "citation_used": citation_ratio["used"],
        "citation_valid": citation_ratio["valid"],
        "ungrounded_conclusions": count_free_text_ungrounded_conclusions(report_text),
    }


def summarize_b(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected_total = sum(row["conflict_total"] for row in rows)
    found_total = sum(row["conflict_found"] for row in rows)
    citation_used = sum(row["citation_used"] for row in rows)
    citation_valid = sum(row["citation_valid"] for row in rows)
    return {
        "conflict_recall": found_total / expected_total if expected_total else 1.0,
        "conflict_found": found_total,
        "conflict_total": expected_total,
        "spurious_conflicts": sum(row["spurious_conflicts"] for row in rows),
        "valid_citation_ratio": citation_valid / citation_used if citation_used else None,
        "ungrounded_conclusions": sum(row["ungrounded_conclusions"] for row in rows),
    }


def summarize_a(rows: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if rows is None:
        return None
    expected_total = sum(row["conflict_total"] for row in rows)
    found_total = sum(row["conflict_found"] for row in rows)
    citation_used = sum(row["citation_used"] for row in rows)
    citation_valid = sum(row["citation_valid"] for row in rows)
    return {
        "conflict_recall": found_total / expected_total if expected_total else 1.0,
        "conflict_found": found_total,
        "conflict_total": expected_total,
        "valid_citation_ratio": citation_valid / citation_used if citation_used else None,
        "ungrounded_conclusions": sum(row["ungrounded_conclusions"] for row in rows),
    }


def markdown_table(b_rows: list[dict[str, Any]], a_rows: list[dict[str, Any]] | None) -> str:
    a_by_case = {row["case"]: row for row in a_rows or []}
    lines = [
        "| Case | A conflict recall | B conflict recall | B spurious conflicts | A valid citation ratio | B valid citation ratio | A ungrounded conclusions | B ungrounded conclusions |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for b_row in b_rows:
        a_row = a_by_case.get(b_row["case"])
        lines.append(
            "| {case} | {a_recall} | {b_recall:.2f} | {spurious} | {a_citation} | {b_citation} | {a_ungrounded} | {b_ungrounded} |".format(
                case=b_row["case"],
                a_recall="N/A" if a_row is None else f"{a_row['conflict_recall']:.2f}",
                b_recall=b_row["conflict_recall"],
                spurious=b_row["spurious_conflicts"],
                a_citation="N/A" if a_row is None else format_ratio(a_row["valid_citation_ratio"]),
                b_citation=format_ratio(b_row["valid_citation_ratio"]),
                a_ungrounded="N/A" if a_row is None else str(a_row["ungrounded_conclusions"]),
                b_ungrounded=b_row["ungrounded_conclusions"],
            )
        )
    b_summary = summarize_b(b_rows)
    a_summary = summarize_a(a_rows)
    lines.append(
        "| **Summary** | {a_recall} | {b_recall:.2f} | {spurious} | {a_citation} | {b_citation} | {a_ungrounded} | {b_ungrounded} |".format(
            a_recall="N/A" if a_summary is None else f"{a_summary['conflict_recall']:.2f}",
            b_recall=b_summary["conflict_recall"],
            spurious=b_summary["spurious_conflicts"],
            a_citation="N/A" if a_summary is None else format_ratio(a_summary["valid_citation_ratio"]),
            b_citation=format_ratio(b_summary["valid_citation_ratio"]),
            a_ungrounded="N/A" if a_summary is None else str(a_summary["ungrounded_conclusions"]),
            b_ungrounded=b_summary["ungrounded_conclusions"],
        )
    )
    return "\n".join(lines)


def write_result(
    run_mode: dict[str, Any],
    b_rows: list[dict[str, Any]],
    a_rows: list[dict[str, Any]] | None,
    a_skip_reason: str | None,
) -> None:
    body_parts = [
        "# EviTrace A/B Evaluation",
        "",
        "由 evaluate_ab.py 生成。",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 案例数：{len(b_rows)}",
        f"- 运行模式：`{run_mode.get('mode')}`",
        f"- LLM：`{'real' if (run_mode.get('llm') or {}).get('real') else 'mock'}`"
        + (
            f" / `{(run_mode.get('llm') or {}).get('model')}`"
            if (run_mode.get("llm") or {}).get("model")
            else ""
        ),
        f"- Vision：`{'real' if (run_mode.get('vision') or {}).get('real') else 'mock'}`",
        f"- OCR：`{(run_mode.get('ocr') or {}).get('source')}`",
        f"- ASR：`{(run_mode.get('asr') or {}).get('source')}`",
    ]
    if a_skip_reason:
        body_parts.append(f"- A 臂状态：N/A，{a_skip_reason}")
    body_parts.extend(
        [
            "",
            "A 臂为同案证据文本一次性直出报告；冲突召回为宽松启发式上界，只判断两个预期冲突取值是否同时出现，不判断是否真正指出矛盾。",
            "B 臂为 EviTrace 证据链完整管线，统计结构化冲突、报告引用合法性和结论段落引用覆盖。",
            "",
            "## A vs B",
            "",
            markdown_table(b_rows, a_rows),
            "",
        ]
    )
    OUTPUT_PATH.write_text("\n".join(body_parts), encoding="utf-8")


def print_run_mode(run_mode: dict[str, Any]) -> None:
    print(json.dumps(run_mode, ensure_ascii=False, indent=2))


def main() -> int:
    evaluate_demo.require_demo_files()
    preserved_env = {key: os.environ.get(key) for key in ENV_TO_PRESERVE}
    with tempfile.TemporaryDirectory(prefix="evitrace-ab-") as temp_name:
        temp_root = Path(temp_name)
        configure_ab_environment(temp_root, preserved_env)

        if str(BACKEND_ROOT) not in sys.path:
            sys.path.insert(0, str(BACKEND_ROOT))
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.main import app
        from app.utils.run_mode import run_mode_metadata

        run_mode = run_mode_metadata()
        print_run_mode(run_mode)

        a_skip_reason = None
        run_a = not settings.effective_mock_llm
        if not run_a:
            a_skip_reason = "A 臂需真实 LLM，已跳过；仅运行 B 臂与管线指标"
            print(a_skip_reason)

        data_root = settings.data_root_path
        b_rows: list[dict[str, Any]] = []
        a_rows: list[dict[str, Any]] | None = [] if run_a else None
        with TestClient(app) as client:
            admin_headers = evaluate_demo.login(client, "admin", "admin-password")
            analyst_headers = evaluate_demo.create_analyst(client, admin_headers)
            for case_name in evaluate_demo.CASE_DIRS:
                b_row = run_b_case(client, analyst_headers, case_name, data_root)
                b_rows.append(b_row)
                if a_rows is not None:
                    a_rows.append(run_a_case(case_name, b_row["expected_conflicts"], b_row["evidence"]))

        print()
        print("A vs B")
        print(markdown_table(b_rows, a_rows))
        write_result(run_mode, b_rows, a_rows, a_skip_reason)
        print(f"\nSaved {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
