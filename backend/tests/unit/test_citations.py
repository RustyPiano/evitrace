from app.utils.citations import validate_report_citations


def test_validate_report_citations_finds_invalid_references():
    report = """
# 任务

## 五、综合分析结论
第一段包含有效引用。[E-0001]
第二段包含无效引用。[E-9999]
"""

    check = validate_report_citations(report, {"E-0001"})

    assert check.invalid_citations == ["E-9999"]
    assert check.used_citations == ["E-0001", "E-9999"]


def test_validate_report_citations_calculates_conclusion_coverage():
    report = """
# 任务

## 四、主要冲突
冲突描述。[E-0001]

## 五、综合分析结论
第一段有引用。[E-0001]

第二段没有引用。

## 六、未确认事项
待复核。
"""

    check = validate_report_citations(report, {"E-0001"})

    assert check.invalid_citations == []
    assert check.conclusion_paragraph_count == 2
    assert check.cited_conclusion_paragraph_count == 1
    assert check.citation_coverage == 0.5


def test_validate_report_citations_accepts_more_than_four_digit_evidence_ids():
    report = """
# 任务

## 五、综合分析结论
第一段包含长编号引用。[E-10000]
"""

    check = validate_report_citations(report, {"E-10000"})

    assert check.used_citations == ["E-10000"]
    assert check.invalid_citations == []
    assert check.citation_coverage == 1.0


def test_validate_report_citations_flags_uncited_timeline_and_conflict_facts():
    report = """
# 任务

## 三、事件时间线
- 6月1日14:00：车队到达地点A。

## 四、主要冲突
- C-001：两个来源给出的地点不同。[E-9999]

## 五、综合分析结论
结论有引用。[E-0001]
"""

    check = validate_report_citations(report, {"E-0001"})

    assert check.invalid_citations == ["E-9999"]
    assert check.uncited_sections == ["三、事件时间线", "四、主要冲突"]
    assert check.uncited_fact_count == 2


def test_validate_report_citations_accepts_spaced_conclusion_heading():
    report = """
# 任务

## 五、 综合分析结论
第一段包含有效引用。[E-0001]
"""

    check = validate_report_citations(report, {"E-0001"})

    assert check.conclusion_paragraph_count == 1
    assert check.citation_coverage == 1.0
