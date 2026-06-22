#!/usr/bin/env python3
"""Run EviTrace demo cases through the real API and compare expected labels."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
DEMO_ROOT = ROOT / "demo_data"
OUTPUT_PATH = ROOT / "evaluation_result.md"
CASE_DIRS = [
    "case_01_time_conflict",
    "case_02_location_conflict",
    "case_03_quantity_conflict",
]
UPLOAD_FILES = [
    ("brief.txt", "text/plain"),
    ("report.pdf", "application/pdf"),
    ("image.png", "image/png"),
    ("audio.wav", "audio/wav"),
    ("video.mp4", "video/mp4"),
]
SIDECARS = [
    "image.ocr.json",
    "image.caption.json",
    "audio.asr.json",
    "video.video.json",
    "video.caption.json",
]


def configure_environment(temp_root: Path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{temp_root / 'evaluation.db'}"
    os.environ["DATA_ROOT"] = str(temp_root / "data")
    os.environ["SECRET_KEY"] = "evaluation-secret-key-with-at-least-32-bytes"
    os.environ["FIRST_ADMIN_USERNAME"] = "admin"
    os.environ["FIRST_ADMIN_PASSWORD"] = "admin-password"
    os.environ["MOCK_AI"] = "true"
    os.environ["ENV"] = "test"
    sys.path.insert(0, str(BACKEND_ROOT))


def require_demo_files() -> None:
    missing: list[str] = []
    for case_name in CASE_DIRS:
        case_dir = DEMO_ROOT / case_name
        for filename, _ in UPLOAD_FILES:
            if not (case_dir / filename).is_file():
                missing.append(str((case_dir / filename).relative_to(ROOT)))
        for filename in SIDECARS + ["extraction.json", "expected.json"]:
            if not (case_dir / filename).is_file():
                missing.append(str((case_dir / filename).relative_to(ROOT)))
    if missing:
        joined = "\n".join(f"- {item}" for item in missing)
        raise RuntimeError(f"Demo data is incomplete. Run scripts/build_demo_data.py first.\n{joined}")


def login(client: Any, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_analyst(client: Any, admin_headers: dict[str, str]) -> dict[str, str]:
    response = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"username": "demo_analyst", "password": "demo-password", "role": "analyst"},
    )
    response.raise_for_status()
    return login(client, "demo_analyst", "demo-password")


def create_task(client: Any, headers: dict[str, str], case_name: str) -> str:
    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "name": case_name,
            "objective": "Find planted cross-modal conflicts and produce cited report.",
        },
    )
    response.raise_for_status()
    return response.json()["data"]["id"]


def upload_case_files(client: Any, headers: dict[str, str], task_id: str, case_dir: Path) -> list[dict[str, Any]]:
    with ExitStack() as stack:
        files = []
        for filename, content_type in UPLOAD_FILES:
            handle = stack.enter_context((case_dir / filename).open("rb"))
            files.append(("files", (filename, handle, content_type)))
        response = client.post(f"/api/v1/tasks/{task_id}/files", headers=headers, files=files)
    response.raise_for_status()
    return response.json()["data"]


def install_fixtures(task_id: str, case_dir: Path, data_root: Path) -> None:
    task_dir = data_root / "tasks" / task_id
    original_dir = task_dir / "original"
    mock_dir = task_dir / "mock"
    mock_dir.mkdir(parents=True, exist_ok=True)
    for filename in SIDECARS:
        shutil.copy2(case_dir / filename, original_dir / filename)
    shutil.copy2(case_dir / "extraction.json", mock_dir / "extraction.json")


def wait_for_completion(client: Any, headers: dict[str, str], task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/tasks/{task_id}/runs/latest", headers=headers)
        response.raise_for_status()
        latest = response.json()["data"]
        if latest["status"] in {"succeeded", "failed"}:
            return latest
        time.sleep(0.1)
    raise TimeoutError(f"Task {task_id} did not finish; latest={latest}")


def normalize(value: object) -> str:
    return str(value).strip().casefold()


def conflict_matches(conflict: dict[str, Any], expected: dict[str, Any]) -> bool:
    if conflict.get("type") != expected.get("type"):
        return False
    expected_sides = {normalize(expected.get("left")), normalize(expected.get("right"))}
    actual_sides = {
        normalize((conflict.get("left") or {}).get("value")),
        normalize((conflict.get("right") or {}).get("value")),
    }
    return expected_sides == actual_sides


def count_expected_found(conflicts: list[dict[str, Any]], expected_conflicts: list[dict[str, Any]]) -> int:
    found = 0
    used_indexes: set[int] = set()
    for expected in expected_conflicts:
        for index, conflict in enumerate(conflicts):
            if index in used_indexes:
                continue
            if conflict_matches(conflict, expected):
                used_indexes.add(index)
                found += 1
                break
    return found


def evaluate_case(client: Any, headers: dict[str, str], case_name: str, data_root: Path) -> dict[str, Any]:
    case_dir = DEMO_ROOT / case_name
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    task_id = create_task(client, headers, case_name)
    upload_case_files(client, headers, task_id, case_dir)
    install_fixtures(task_id, case_dir, data_root)

    start_response = client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)
    start_response.raise_for_status()
    latest = wait_for_completion(client, headers, task_id)

    task_response = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    task_response.raise_for_status()
    task = task_response.json()["data"]

    evidence_response = client.get(f"/api/v1/tasks/{task_id}/evidence?page_size=50", headers=headers)
    evidence_response.raise_for_status()
    evidence_items = evidence_response.json()["data"]["items"]

    results_response = client.get(f"/api/v1/tasks/{task_id}/results", headers=headers)
    results_response.raise_for_status()
    results = results_response.json()["data"]

    download_response = client.get(f"/api/v1/tasks/{task_id}/report/download", headers=headers)
    download_response.raise_for_status()

    conflicts = list(results.get("conflicts") or [])
    expected_conflicts = list(expected.get("expected_conflicts") or [])
    expected_found = count_expected_found(conflicts, expected_conflicts)
    expected_count = len(expected_conflicts)
    citation_check = results.get("citation_check") or {}
    used_citations = list(citation_check.get("used_citations") or [])
    invalid_citations = list(citation_check.get("invalid_citations") or [])
    uncited_fact_count = int(citation_check.get("uncited_fact_count") or 0)
    modalities = sorted({item.get("modality") for item in evidence_items if item.get("modality")})
    required_modalities = set(expected.get("required_evidence_modalities") or [])
    modal_complete = required_modalities.issubset(set(modalities))

    return {
        "case": case_name,
        "task_id": task_id,
        "task_status": task["status"],
        "run_status": latest["status"],
        "expected_conflict_count": expected_count,
        "found_conflict_count": expected_found,
        "total_detected_conflicts": len(conflicts),
        "conflict_recall": expected_found / expected_count if expected_count else 1.0,
        "report_reference_count": len(used_citations),
        "valid_reference_count": int(citation_check.get("valid_citation_count") or 0),
        "citation_coverage": float(citation_check.get("citation_coverage") or 0),
        "invalid_reference_count": len(invalid_citations),
        "invalid_citations": invalid_citations,
        "uncited_fact_count": uncited_fact_count,
        "uncited_sections": list(citation_check.get("uncited_sections") or []),
        "modalities": modalities,
        "all_required_modalities": modal_complete,
        "matched_expected_conflicts": [
            expected
            for expected in expected_conflicts
            if any(conflict_matches(conflict, expected) for conflict in conflicts)
        ],
    }


def markdown_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Case | Expected | Found | Recall | Report refs | Valid refs | Citation coverage | Invalid refs | Uncited facts | Four modalities |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {case} | {expected_conflict_count} | {found_conflict_count} | {conflict_recall:.2f} | "
            "{report_reference_count} | {valid_reference_count} | {citation_coverage:.2f} | "
            "{invalid_reference_count} | {uncited_fact_count} | {modalities_ok} |".format(
                **row,
                modalities_ok="yes" if row["all_required_modalities"] else "no",
            )
        )
    return "\n".join(lines)


def write_result(rows: list[dict[str, Any]]) -> None:
    aggregate = {
        "case_count": len(rows),
        "all_completed": all(row["task_status"] == "awaiting_review" and row["run_status"] == "succeeded" for row in rows),
        "overall_conflict_recall": (
            sum(row["found_conflict_count"] for row in rows) / sum(row["expected_conflict_count"] for row in rows)
            if sum(row["expected_conflict_count"] for row in rows)
            else 1.0
        ),
        "min_citation_coverage": min((row["citation_coverage"] for row in rows), default=1.0),
        "invalid_reference_count": sum(row["invalid_reference_count"] for row in rows),
        "uncited_fact_count": sum(row["uncited_fact_count"] for row in rows),
        "all_required_modalities": all(row["all_required_modalities"] for row in rows),
    }
    body = "\n\n".join(
        [
            "# EviTrace M5 Demo Evaluation",
            "## Summary JSON",
            "```json\n" + json.dumps({"summary": aggregate, "cases": rows}, ensure_ascii=False, indent=2) + "\n```",
            "## Case Table",
            markdown_table(rows),
            "",
        ]
    )
    OUTPUT_PATH.write_text(body, encoding="utf-8")
    print(json.dumps({"summary": aggregate, "cases": rows}, ensure_ascii=False, indent=2))
    print()
    print(markdown_table(rows))
    print(f"\nSaved {OUTPUT_PATH.relative_to(ROOT)}")


def main() -> int:
    require_demo_files()
    with tempfile.TemporaryDirectory(prefix="evitrace-eval-") as temp_name:
        temp_root = Path(temp_name)
        configure_environment(temp_root)

        from fastapi.testclient import TestClient

        from app.config import settings
        from app.main import app

        data_root = settings.data_root_path
        rows: list[dict[str, Any]] = []
        with TestClient(app) as client:
            admin_headers = login(client, "admin", "admin-password")
            analyst_headers = create_analyst(client, admin_headers)
            for case_name in CASE_DIRS:
                rows.append(evaluate_case(client, analyst_headers, case_name, data_root))
        write_result(rows)

        failed = [
            row["case"]
            for row in rows
            if row["task_status"] != "awaiting_review"
            or row["run_status"] != "succeeded"
            or row["conflict_recall"] < 0.8
            or row["citation_coverage"] < 0.9
            or row["invalid_reference_count"] != 0
            or row["uncited_fact_count"] != 0
            or not row["all_required_modalities"]
        ]
        if failed:
            print("Failed cases: " + ", ".join(failed), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
