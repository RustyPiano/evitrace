from pathlib import Path
import re
from time import perf_counter
from typing import Any

from app.config import settings
from app.services.llm_client import LocalLLMClient
from app.utils.citations import (
    CONCLUSION_HEADING_RE,
    CONFLICT_HEADING_RE,
    SECTION_RE,
    TIMELINE_HEADING_RE,
    ordered_unique,
    validate_report_citations,
)

from .base import SkillContext, SkillManifest, SkillResult

REPORT_NOTICE = "**AI 辅助生成，需人工复核。**"
REPORT_SECTION_PATTERNS = [
    re.compile(r"^##\s*一、\s*任务概述", re.MULTILINE),
    re.compile(r"^##\s*二、\s*资料概况", re.MULTILINE),
    re.compile(r"^##\s*三、\s*事件时间线", re.MULTILINE),
    re.compile(r"^##\s*四、\s*主要冲突", re.MULTILINE),
    CONCLUSION_HEADING_RE,
    re.compile(r"^##\s*六、\s*未确认事项", re.MULTILINE),
]


def _valid_ids(evidence_items: list[dict[str, Any]]) -> set[str]:
    return {str(item["display_id"]) for item in evidence_items}


def _first_ids(evidence_items: list[dict[str, Any]], count: int = 1) -> str:
    ids = [f"[{item['display_id']}]" for item in evidence_items[:count]]
    return "".join(ids) if ids else ""


def _format_refs(evidence_ids: list[Any]) -> str:
    ids = ordered_unique([str(evidence_id) for evidence_id in evidence_ids if evidence_id])
    return "".join(f"[{evidence_id}]" for evidence_id in ids)


def _with_refs(text: str, refs: str) -> str:
    return f"{text} {refs}" if refs else text


def _timeline_lines(payload: dict[str, Any]) -> list[str]:
    evidence = list(payload.get("evidence") or [])
    primary_ref = _first_ids(evidence, 1)
    lines = []
    for item in list(payload.get("timeline") or []):
        refs = _format_refs(list(item.get("evidence_ids") or []))
        time_text = item.get("time_normalized") or item.get("time_text") or "时间未确定"
        title = item.get("title") or item.get("event_key") or "未命名事件"
        lines.append(_with_refs(f"- {time_text}：{title}", refs))
    return lines or [f"- 暂无可排序事件。{primary_ref}"]


def _conflict_lines(payload: dict[str, Any]) -> list[str]:
    evidence = list(payload.get("evidence") or [])
    primary_ref = _first_ids(evidence, 1)
    lines = []
    for conflict in list(payload.get("conflicts") or []):
        left = conflict.get("left") or {}
        right = conflict.get("right") or {}
        refs = _format_refs(list(left.get("evidence_ids") or []) + list(right.get("evidence_ids") or []))
        conflict_id = conflict.get("conflict_id") or "C-???"
        description = conflict.get("description") or conflict.get("event_key") or "冲突待复核"
        lines.append(_with_refs(f"- {conflict_id}：{description}", refs))
    return lines or [f"- 未发现规则范围内冲突。{primary_ref}"]


def _structured_timeline_section(payload: dict[str, Any]) -> str:
    return "## 三、事件时间线\n" + "\n".join(_timeline_lines(payload))


def _structured_conflict_section(payload: dict[str, Any]) -> str:
    return "## 四、主要冲突\n" + "\n".join(_conflict_lines(payload))


def _replace_report_section(markdown: str, heading_re: re.Pattern[str], replacement: str) -> str:
    match = heading_re.search(markdown)
    if match is None:
        return markdown
    next_match = SECTION_RE.search(markdown, match.end())
    end = next_match.start() if next_match else len(markdown)
    return f"{markdown[: match.start()].rstrip()}\n\n{replacement}\n\n{markdown[end:].lstrip()}".strip()


def _with_structured_fact_sections(markdown: str, payload: dict[str, Any]) -> str:
    markdown = _replace_report_section(markdown, TIMELINE_HEADING_RE, _structured_timeline_section(payload))
    return _replace_report_section(markdown, CONFLICT_HEADING_RE, _structured_conflict_section(payload))


def _report_path(context: SkillContext) -> Path:
    reports_dir = Path(context.data_root) / "tasks" / context.task_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir / "latest.md"


def write_latest_report(context: SkillContext, markdown: str) -> Path:
    path = _report_path(context)
    path.write_text(markdown, encoding="utf-8")
    return path


def _with_report_notice(markdown: str) -> str:
    body = markdown.strip()
    if body.startswith(REPORT_NOTICE):
        return body
    return f"{REPORT_NOTICE}\n\n{body}"


def _has_required_report_sections(markdown: str) -> bool:
    return all(pattern.search(markdown) for pattern in REPORT_SECTION_PATTERNS)


def build_mock_report(payload: dict[str, Any]) -> str:
    task = payload.get("task") or {}
    evidence = list(payload.get("evidence") or [])
    events = list(payload.get("events") or [])
    primary_ref = _first_ids(evidence, 1)

    event_count = len(events)
    conflict_count = len(list(payload.get("conflicts") or []))
    return "\n\n".join(
        [
            REPORT_NOTICE,
            f"# {task.get('name') or '未命名任务'}",
            "## 一、任务概述\n"
            f"任务目标：{task.get('objective') or '未提供'}。{primary_ref}",
            "## 二、资料概况\n"
            f"本次分析使用 {len(evidence)} 条证据。{primary_ref}",
            _structured_timeline_section(payload),
            _structured_conflict_section(payload),
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
    primary_ref = _first_ids(evidence, 1)
    return "\n\n".join(
        [
            REPORT_NOTICE,
            f"# {task.get('name') or '未命名任务'}",
            f"## 一、任务概述\n任务目标：{task.get('objective') or '未提供'}。{primary_ref}",
            f"## 二、资料概况\n本次分析使用 {len(evidence)} 条证据。{primary_ref}",
            _structured_timeline_section(payload),
            _structured_conflict_section(payload),
            f"## 五、综合分析结论\n综合结论生成失败，请人工复核。{primary_ref}",
            f"## 六、未确认事项\n- 报告正文由模板降级生成，需人工补充复核。{primary_ref}",
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
                    "三、事件时间线和四、主要冲突将由系统按结构化结果重建。"
                )
                markdown = client.generate_text(system_prompt, _build_model_prompt(payload))
                if not _has_required_report_sections(markdown):
                    warnings.append("模型报告结构不完整，已使用模板降级")
                    markdown = build_fallback_report(payload)
                else:
                    markdown = _with_report_notice(markdown)
        except Exception:
            warnings.append("报告模型生成失败，已使用模板降级")
            markdown = build_fallback_report(payload)

        markdown = _with_structured_fact_sections(markdown, payload)
        citation_check = validate_report_citations(markdown, _valid_ids(list(payload.get("evidence") or [])))
        if citation_check.invalid_citations:
            warnings.append("报告存在无效证据引用")
        if citation_check.uncited_fact_count:
            warnings.append("时间线或主要冲突存在无证据编号事实")
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
