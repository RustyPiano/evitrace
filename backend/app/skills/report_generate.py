from pathlib import Path
from time import perf_counter
from typing import Any

from app.config import settings
from app.services.llm_client import LocalLLMClient
from app.utils.citations import validate_report_citations

from .base import SkillContext, SkillManifest, SkillResult

REPORT_NOTICE = "**AI 辅助生成，需人工复核。**"


def _valid_ids(evidence_items: list[dict[str, Any]]) -> set[str]:
    return {str(item["display_id"]) for item in evidence_items}


def _first_ids(evidence_items: list[dict[str, Any]], count: int = 1) -> str:
    ids = [f"[{item['display_id']}]" for item in evidence_items[:count]]
    return "".join(ids) if ids else ""


def _report_path(context: SkillContext) -> Path:
    reports_dir = Path(context.data_root) / "tasks" / context.task_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir / "latest.md"


def write_latest_report(context: SkillContext, markdown: str) -> Path:
    path = _report_path(context)
    path.write_text(markdown, encoding="utf-8")
    return path


def build_mock_report(payload: dict[str, Any]) -> str:
    task = payload.get("task") or {}
    evidence = list(payload.get("evidence") or [])
    events = list(payload.get("events") or [])
    timeline = list(payload.get("timeline") or [])
    conflicts = list(payload.get("conflicts") or [])
    primary_ref = _first_ids(evidence, 1)

    timeline_lines = []
    for item in timeline:
        refs = "".join(f"[{evidence_id}]" for evidence_id in item.get("evidence_ids", []))
        time_text = item.get("time_normalized") or item.get("time_text") or "时间未确定"
        timeline_lines.append(f"- {time_text}：{item.get('title') or item.get('event_key')} {refs}")
    if not timeline_lines:
        timeline_lines.append(f"- 暂无可排序事件。{primary_ref}")

    conflict_lines = []
    for conflict in conflicts:
        refs = "".join(f"[{evidence_id}]" for evidence_id in conflict.get("left", {}).get("evidence_ids", []))
        refs += "".join(f"[{evidence_id}]" for evidence_id in conflict.get("right", {}).get("evidence_ids", []))
        conflict_lines.append(f"- {conflict.get('conflict_id')}：{conflict.get('description')} {refs}")
    if not conflict_lines:
        conflict_lines.append(f"- 未发现规则范围内冲突。{primary_ref}")

    event_count = len(events)
    conflict_count = len(conflicts)
    return "\n\n".join(
        [
            f"# {task.get('name') or '未命名任务'}",
            REPORT_NOTICE,
            "## 一、任务概述\n"
            f"任务目标：{task.get('objective') or '未提供'}。{primary_ref}",
            "## 二、资料概况\n"
            f"本次分析使用 {len(evidence)} 条证据。{primary_ref}",
            "## 三、事件时间线\n" + "\n".join(timeline_lines),
            "## 四、主要冲突\n" + "\n".join(conflict_lines),
            "## 五、综合分析结论\n"
            f"本次 MOCK 分析提取 {event_count} 条事件，并发现 {conflict_count} 条规则冲突，结论需人工复核。{primary_ref}\n\n"
            f"所有事实性摘要均基于当前任务证据编号，不包含外部资料。{primary_ref}",
            "## 六、未确认事项\n"
            f"- 冲突状态仍需人工审核。{primary_ref}\n"
            f"- 低置信度或资料缺失事项需结合原始文件复核。{primary_ref}",
        ]
    )


def build_fallback_report(payload: dict[str, Any]) -> str:
    task = payload.get("task") or {}
    evidence = list(payload.get("evidence") or [])
    timeline = list(payload.get("timeline") or [])
    conflicts = list(payload.get("conflicts") or [])
    primary_ref = _first_ids(evidence, 1)
    timeline_lines = [
        f"- {(item.get('time_normalized') or item.get('time_text') or '时间未确定')}：{item.get('title')} "
        + "".join(f"[{evidence_id}]" for evidence_id in item.get("evidence_ids", []))
        for item in timeline
    ] or [f"- 暂无可排序事件。{primary_ref}"]
    conflict_lines = [
        f"- {conflict.get('conflict_id')}：{conflict.get('description')} "
        + "".join(f"[{evidence_id}]" for evidence_id in conflict.get("left", {}).get("evidence_ids", []))
        + "".join(f"[{evidence_id}]" for evidence_id in conflict.get("right", {}).get("evidence_ids", []))
        for conflict in conflicts
    ] or [f"- 未发现规则范围内冲突。{primary_ref}"]
    return "\n\n".join(
        [
            f"# {task.get('name') or '未命名任务'}",
            REPORT_NOTICE,
            f"## 一、任务概述\n任务目标：{task.get('objective') or '未提供'}。{primary_ref}",
            f"## 二、资料概况\n本次分析使用 {len(evidence)} 条证据。{primary_ref}",
            "## 三、事件时间线\n" + "\n".join(timeline_lines),
            "## 四、主要冲突\n" + "\n".join(conflict_lines),
            "## 五、综合分析结论\n综合结论生成失败，请人工复核。",
            "## 六、未确认事项\n- 报告正文由模板降级生成，需人工补充复核。",
        ]
    )


def _build_model_prompt(payload: dict[str, Any]) -> str:
    evidence = list(payload.get("evidence") or [])[:30]
    evidence_lines = [
        f"[{item['display_id']}] {str(item.get('content') or item.get('content_summary') or '')[:240]}"
        for item in evidence
    ]
    return "\n".join(
        [
            f"任务：{payload.get('task')}",
            f"事件：{payload.get('events')}",
            f"时间线：{payload.get('timeline')}",
            f"冲突：{payload.get('conflicts')}",
            "证据摘要：",
            *evidence_lines,
        ]
    )


class ReportGenerateSkill:
    manifest = SkillManifest(
        id="report_generate",
        name="报告生成与引用验证",
        version="1.0.0",
        description="生成 Markdown 报告并验证证据引用",
        enabled_by_default=True,
        required=True,
        input_types=["analysis_results"],
        output_type="report_markdown",
    )

    def __init__(self, llm_client: LocalLLMClient | None = None) -> None:
        self.llm_client = llm_client

    def run(self, context: SkillContext, payload: Any) -> SkillResult:
        started = perf_counter()
        payload = dict(payload or {})
        warnings: list[str] = []
        try:
            if settings.mock_ai:
                markdown = build_mock_report(payload)
            else:
                client = self.llm_client or LocalLLMClient()
                system_prompt = (
                    "你是情报报告生成器。仅使用输入中的任务、事件、时间线、冲突和证据摘要；"
                    "不得新增事实；事实性陈述必须带 [E-xxxx]；输出固定 Markdown 六个章节。"
                )
                markdown = client.generate_text(system_prompt, _build_model_prompt(payload))
                if "## 五、综合分析结论" not in markdown:
                    warnings.append("模型报告结构不完整，已使用模板降级")
                    markdown = build_fallback_report(payload)
        except Exception:
            warnings.append("报告模型生成失败，已使用模板降级")
            markdown = build_fallback_report(payload)

        citation_check = validate_report_citations(markdown, _valid_ids(list(payload.get("evidence") or [])))
        if citation_check.invalid_citations:
            warnings.append("报告存在无效证据引用")
        if citation_check.citation_coverage < 0.9:
            warnings.append("综合分析结论引用覆盖率低于 0.90")
        write_latest_report(context, markdown)
        return SkillResult(
            success=True,
            warnings=warnings,
            data={
                "report_markdown": markdown,
                "citation_check": citation_check.model_dump(mode="json"),
            },
            metrics={"duration_ms": int((perf_counter() - started) * 1000)},
        )
