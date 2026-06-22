from app.skills.base import SkillContext
from app.skills.report_generate import REPORT_NOTICE, ReportGenerateSkill


FIXED_HEADINGS = [
    "## 一、任务概述",
    "## 二、资料概况",
    "## 三、事件时间线",
    "## 四、主要冲突",
    "## 五、综合分析结论",
    "## 六、未确认事项",
]


def _context(tmp_path) -> SkillContext:
    return SkillContext(task_id="task-1", run_id="run-1", data_root=str(tmp_path))


def _payload() -> dict:
    return {
        "task": {"name": "Case", "objective": "Analyze"},
        "evidence": [
            {
                "display_id": "E-0001",
                "content": "6月1日14:00，车队在地点A发现3辆车。",
            }
        ],
        "events": [],
        "timeline": [],
        "conflicts": [],
    }


def _payload_with_structured_sections() -> dict:
    payload = _payload()
    payload["timeline"] = [
        {
            "event_id": "EV-001",
            "event_key": "convoy",
            "title": "车队到达地点A",
            "time_normalized": "2026-06-01T14:00:00",
            "time_group": "2026-06-01",
            "evidence_ids": ["E-0001"],
        }
    ]
    payload["conflicts"] = [
        {
            "conflict_id": "C-001",
            "type": "time",
            "event_key": "convoy",
            "description": "同一车队出现时间冲突",
            "left": {"value": "14:00", "event_id": "EV-001", "evidence_ids": ["E-0001"]},
            "right": {"value": "16:30", "event_id": "EV-002", "evidence_ids": ["E-0001"]},
            "status": "unreviewed",
        }
    ]
    return payload


def test_real_report_missing_fixed_heading_falls_back_to_six_section_template(monkeypatch, tmp_path):
    class FakeClient:
        def generate_text(self, _system, _user):
            return "\n\n".join(
                [
                    REPORT_NOTICE,
                    "## 一、任务概述\n任务目标。[E-0001]",
                    "## 二、资料概况\n资料概况。[E-0001]",
                    "## 三、事件时间线\n暂无。[E-0001]",
                    "## 四、主要冲突\n暂无。[E-0001]",
                    "## 五、综合分析结论\n结论。[E-0001]",
                ]
            )

    monkeypatch.setattr("app.skills.report_generate.settings.mock_ai", False)

    result = ReportGenerateSkill(llm_client=FakeClient()).run(_context(tmp_path), _payload())

    assert result.success is True
    assert result.warnings == ["模型报告结构不完整，已使用模板降级"]
    assert REPORT_NOTICE in result.data["report_markdown"]
    for heading in FIXED_HEADINGS:
        assert heading in result.data["report_markdown"]


def test_real_report_notice_is_prepended_once_when_structure_is_valid(monkeypatch, tmp_path):
    class FakeClient:
        def generate_text(self, _system, _user):
            return "\n\n".join(
                [
                    "## 一、任务概述\n任务目标。[E-0001]",
                    "## 二、资料概况\n资料概况。[E-0001]",
                    "## 三、事件时间线\n暂无。[E-0001]",
                    "## 四、主要冲突\n暂无。[E-0001]",
                    "## 五、综合分析结论\n结论。[E-0001]",
                    "## 六、未确认事项\n待复核。[E-0001]",
                ]
            )

    monkeypatch.setattr("app.skills.report_generate.settings.mock_ai", False)

    result = ReportGenerateSkill(llm_client=FakeClient()).run(_context(tmp_path), _payload())

    markdown = result.data["report_markdown"]
    assert markdown.startswith(REPORT_NOTICE)
    assert markdown.count(REPORT_NOTICE) == 1
    assert result.warnings == []


def test_real_report_replaces_model_timeline_and_conflicts_with_structured_cited_sections(
    monkeypatch, tmp_path
):
    class FakeClient:
        def generate_text(self, _system, _user):
            return "\n\n".join(
                [
                    "## 一、任务概述\n任务目标。[E-0001]",
                    "## 二、资料概况\n资料概况。[E-0001]",
                    "## 三、事件时间线\n- 模型生成的无引用时间线事实。",
                    "## 四、主要冲突\n- 模型生成的无引用冲突事实。",
                    "## 五、综合分析结论\n结论。[E-0001]",
                    "## 六、未确认事项\n待复核。[E-0001]",
                ]
            )

    monkeypatch.setattr("app.skills.report_generate.settings.mock_ai", False)

    result = ReportGenerateSkill(llm_client=FakeClient()).run(
        _context(tmp_path),
        _payload_with_structured_sections(),
    )

    markdown = result.data["report_markdown"]
    assert "模型生成的无引用时间线事实" not in markdown
    assert "模型生成的无引用冲突事实" not in markdown
    assert "- 2026-06-01T14:00:00：车队到达地点A [E-0001]" in markdown
    assert "- C-001：同一车队出现时间冲突 [E-0001]" in markdown
    assert result.data["citation_check"]["uncited_fact_count"] == 0
