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
    return sum(
        1
        for paragraph in split_paragraphs(report_text)
        if looks_like_fact_assertion(paragraph) and not EVIDENCE_ID_RE.search(paragraph)
    )


def citation_presence(markdown: str) -> dict[str, Any]:
    fact_paragraphs = [paragraph for paragraph in split_paragraphs(markdown) if looks_like_fact_assertion(paragraph)]
    cited_fact_paragraphs = [paragraph for paragraph in fact_paragraphs if EVIDENCE_ID_RE.search(paragraph)]
    return {
        "fact_paragraphs": len(fact_paragraphs),
        "cited_fact_paragraphs": len(cited_fact_paragraphs),
        "ratio": len(cited_fact_paragraphs) / len(fact_paragraphs) if fact_paragraphs else None,
    }


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
    citation_presence_result = citation_presence(report_markdown)
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
        "citation_presence": citation_presence_result["ratio"],
        "citation_fact_paragraphs": citation_presence_result["fact_paragraphs"],
        "citation_cited_fact_paragraphs": citation_presence_result["cited_fact_paragraphs"],
        "valid_citation_ratio": citation_ratio["ratio"],
        "citation_used": citation_ratio["used"],
        "citation_valid": citation_ratio["valid"],
        "ungrounded_conclusions": (
            citation_check.conclusion_paragraph_count - citation_check.cited_conclusion_paragraph_count
        ),
        "task_status": row["task_status"],
        "run_status": row["run_status"],
    }


def build_naive_prompt(case_name: str, evidence: list[dict[str, Any]]) -> str:
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


def build_direct_prompt(case_name: str, evidence: list[dict[str, Any]]) -> str:
    evidence_text = "\n".join(
        f"[{item['display_id']}] {item.get('content') or ''}"
        for item in evidence
    )
    return (
        "请根据以下证据写一份情报分析报告。仍然只进行一次自由生成，不要使用任何外部资料。\n\n"
        "硬性要求：\n"
        "1. 每条事实性结论必须在句末标注支持它的证据编号，如 [E-0001]。\n"
        "2. 若发现同一事件存在时间、地点或数量矛盾，必须显式指出冲突，并分别标注各自来源。\n"
        "3. 只能使用下方给定证据，不得编造编号或引用未给出的编号。\n\n"
        f"案例：{case_name}\n\n"
        "证据：\n"
        f"{evidence_text}"
    )


def run_llm_baseline_case(
    case_name: str,
    expected_conflicts: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    prompt_builder: Any,
) -> dict[str, Any]:
    from app.services.llm_client import LocalLLMClient

    client = LocalLLMClient()
    report_text = client.generate_text(
        "你是情报分析助手。根据用户给出的资料直接生成一份完整 Markdown 报告。",
        prompt_builder(case_name, evidence),
    )
    recall = heuristic_conflict_recall(report_text, expected_conflicts)
    evidence_ids = {item["display_id"] for item in evidence}
    citation_ratio = valid_citation_ratio(report_text, evidence_ids)
    citation_presence_result = citation_presence(report_text)
    return {
        "case": case_name,
        "report_markdown": report_text,
        "conflict_recall": recall["recall"],
        "conflict_found": recall["found"],
        "conflict_total": recall["total"],
        "citation_presence": citation_presence_result["ratio"],
        "citation_fact_paragraphs": citation_presence_result["fact_paragraphs"],
        "citation_cited_fact_paragraphs": citation_presence_result["cited_fact_paragraphs"],
        "valid_citation_ratio": citation_ratio["ratio"],
        "citation_used": citation_ratio["used"],
        "citation_valid": citation_ratio["valid"],
        "ungrounded_conclusions": count_free_text_ungrounded_conclusions(report_text),
    }


def run_a0_case(case_name: str, expected_conflicts: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return run_llm_baseline_case(case_name, expected_conflicts, evidence, build_naive_prompt)


def run_a_case(case_name: str, expected_conflicts: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return run_llm_baseline_case(case_name, expected_conflicts, evidence, build_direct_prompt)


def summarize_b(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected_total = sum(row["conflict_total"] for row in rows)
    found_total = sum(row["conflict_found"] for row in rows)
    citation_used = sum(row["citation_used"] for row in rows)
    citation_valid = sum(row["citation_valid"] for row in rows)
    fact_paragraphs = sum(row["citation_fact_paragraphs"] for row in rows)
    cited_fact_paragraphs = sum(row["citation_cited_fact_paragraphs"] for row in rows)
    return {
        "conflict_recall": found_total / expected_total if expected_total else 1.0,
        "conflict_found": found_total,
        "conflict_total": expected_total,
        "spurious_conflicts": sum(row["spurious_conflicts"] for row in rows),
        "citation_presence": cited_fact_paragraphs / fact_paragraphs if fact_paragraphs else None,
        "citation_fact_paragraphs": fact_paragraphs,
        "citation_cited_fact_paragraphs": cited_fact_paragraphs,
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
    fact_paragraphs = sum(row["citation_fact_paragraphs"] for row in rows)
    cited_fact_paragraphs = sum(row["citation_cited_fact_paragraphs"] for row in rows)
    return {
        "conflict_recall": found_total / expected_total if expected_total else 1.0,
        "conflict_found": found_total,
        "conflict_total": expected_total,
        "citation_presence": cited_fact_paragraphs / fact_paragraphs if fact_paragraphs else None,
        "citation_fact_paragraphs": fact_paragraphs,
        "citation_cited_fact_paragraphs": cited_fact_paragraphs,
        "valid_citation_ratio": citation_valid / citation_used if citation_used else None,
        "ungrounded_conclusions": sum(row["ungrounded_conclusions"] for row in rows),
    }


def markdown_table(
    b_rows: list[dict[str, Any]],
    a0_rows: list[dict[str, Any]] | None,
    a_rows: list[dict[str, Any]] | None,
) -> str:
    a0_by_case = {row["case"]: row for row in a0_rows or []}
    a_by_case = {row["case"]: row for row in a_rows or []}
    lines = [
        "| Case | Group | citation_presence | valid_citation_ratio | ungrounded_conclusions | conflict_recall* | spurious_conflicts(B) |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]

    def append_row(case: str, group: str, row: dict[str, Any] | None, spurious: str = "N/A") -> None:
        lines.append(
            "| {case} | {group} | {presence} | {citation} | {ungrounded} | {recall} | {spurious} |".format(
                case=case,
                group=group,
                presence="N/A" if row is None else format_ratio(row["citation_presence"]),
                citation="N/A" if row is None else format_ratio(row["valid_citation_ratio"]),
                ungrounded="N/A" if row is None else str(row["ungrounded_conclusions"]),
                recall="N/A" if row is None else f"{row['conflict_recall']:.2f}",
                spurious=spurious,
            )
        )

    for b_row in b_rows:
        case = b_row["case"]
        append_row(case, "A0(朴素直出)", a0_by_case.get(case))
        append_row(case, "A(带引用直出)", a_by_case.get(case))
        append_row(case, "B(证据链)", b_row, str(b_row["spurious_conflicts"]))
    b_summary = summarize_b(b_rows)
    a0_summary = summarize_a(a0_rows)
    a_summary = summarize_a(a_rows)
    append_row("**Summary**", "A0(朴素直出)", a0_summary)
    append_row("**Summary**", "A(带引用直出)", a_summary)
    append_row("**Summary**", "B(证据链)", b_summary, str(b_summary["spurious_conflicts"]))
    return "\n".join(lines)


def write_result(
    run_mode: dict[str, Any],
    b_rows: list[dict[str, Any]],
    a0_rows: list[dict[str, Any]] | None,
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
        body_parts.append(f"- A0/A 状态：N/A，{a_skip_reason}")
    body_parts.extend(
        [
            "",
            "三组定义：A0(朴素直出) 为旧版无编号、无引用要求的一次 LLM 直出；A(带引用直出) 为同一证据编号、逐事实引用要求的一次 LLM 直出；B(证据链) 为 EviTrace 证据链完整管线。",
            "`citation_presence` 为事实性段落中出现 `E-xxxx` 引用的比例；`valid_citation_ratio` 为报告中合法 `E-xxxx` 引用数 / 全部 `E-xxxx` 引用数。",
            "`conflict_recall*` 为宽松启发式上界：只判断两个预期冲突取值是否同时出现，未判定报告是否真正点明矛盾。",
            "`spurious_conflicts(B)` 仅适用于 B 组结构化冲突输出。",
            "",
            "## A0 vs A vs B",
            "",
            markdown_table(b_rows, a0_rows, a_rows),
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
            a_skip_reason = "A0/A 均需真实 LLM，已跳过；仅运行 B 臂与管线指标"
            print(a_skip_reason)

        data_root = settings.data_root_path
        b_rows: list[dict[str, Any]] = []
        a0_rows: list[dict[str, Any]] | None = [] if run_a else None
        a_rows: list[dict[str, Any]] | None = [] if run_a else None
        with TestClient(app) as client:
            admin_headers = evaluate_demo.login(client, "admin", "admin-password")
            analyst_headers = evaluate_demo.create_analyst(client, admin_headers)
            for case_name in evaluate_demo.CASE_DIRS:
                b_row = run_b_case(client, analyst_headers, case_name, data_root)
                b_rows.append(b_row)
                if a0_rows is not None:
                    a0_rows.append(run_a0_case(case_name, b_row["expected_conflicts"], b_row["evidence"]))
                if a_rows is not None:
                    a_rows.append(run_a_case(case_name, b_row["expected_conflicts"], b_row["evidence"]))

        print()
        print("A0 vs A vs B")
        print(markdown_table(b_rows, a0_rows, a_rows))
        write_result(run_mode, b_rows, a0_rows, a_rows, a_skip_reason)
        print(f"\nSaved {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
