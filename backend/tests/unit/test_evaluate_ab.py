import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "evaluate_ab.py"


def load_module():
    spec = importlib.util.spec_from_file_location("evaluate_ab", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_heuristic_conflict_recall_matches_both_expected_sides_with_nfkc_casefold():
    module = load_module()

    result = module.heuristic_conflict_recall(
        "The report mentions ＡＬＰＨＡ at north pier and then places Alpha at east warehouse.",
        [{"type": "location", "left": "North Pier", "right": "East Warehouse"}],
    )

    assert result == {"found": 1, "total": 1, "recall": 1.0}


def test_valid_citation_ratio_is_none_without_any_evidence_id_mentions():
    module = load_module()

    result = module.valid_citation_ratio("No formal evidence IDs appear here.", {"E-0001"})

    assert result == {"used": 0, "valid": 0, "ratio": None}


def test_valid_citation_ratio_counts_valid_and_invalid_evidence_id_mentions():
    module = load_module()

    result = module.valid_citation_ratio(
        "Alpha arrived at 14:00 [E-0001]. Bravo reported 5 vehicles [E-9999].",
        {"E-0001", "E-0002"},
    )

    assert result == {"used": 2, "valid": 1, "ratio": 0.5}


def test_citation_presence_counts_fact_paragraphs_with_evidence_ids():
    module = load_module()

    result = module.citation_presence(
        "# Report\n\n"
        "Alpha arrived at 14:00 [E-0001].\n\n"
        "Bravo reported 5 vehicles [E-9999].\n\n"
        "Charlie departed at 15:00.\n\n"
        "General caveat."
    )

    assert result == {"fact_paragraphs": 3, "cited_fact_paragraphs": 2, "ratio": 2 / 3}


def test_free_text_ungrounded_conclusions_counts_fact_paragraphs_without_citations():
    module = load_module()

    count = module.count_free_text_ungrounded_conclusions(
        "# Report\n\nAlpha arrived at 14:00.\n\nGeneral caveat.\n\nBravo stayed at E-0001."
    )

    assert count == 1


def test_build_direct_prompt_uses_evidence_ids_and_requires_fact_citations():
    module = load_module()

    prompt = module.build_direct_prompt(
        "case-x",
        [
            {"display_id": "E-0001", "content": "Alpha arrived at 14:00."},
            {"display_id": "E-0002", "content": "Alpha arrived at 15:00."},
        ],
    )

    assert "[E-0001] Alpha arrived at 14:00." in prompt
    assert "[E-0002] Alpha arrived at 15:00." in prompt
    assert "每条事实性结论" in prompt
    assert "句末标注" in prompt
    assert "显式指出冲突" in prompt
    assert "不得编造编号" in prompt


def test_build_naive_prompt_keeps_unnumbered_no_citation_baseline():
    module = load_module()

    prompt = module.build_naive_prompt(
        "case-x",
        [{"display_id": "E-0001", "content": "Alpha arrived at 14:00."}],
    )

    assert "资料 1" in prompt
    assert "Alpha arrived at 14:00." in prompt
    assert "[E-0001]" not in prompt
    assert "每条事实性结论" not in prompt


def test_markdown_table_marks_a0_and_a_na_when_mock_skips_llm_baselines():
    module = load_module()

    table = module.markdown_table(
        [
            {
                "case": "case-x",
                "conflict_recall": 1.0,
                "conflict_found": 1,
                "conflict_total": 1,
                "spurious_conflicts": 0,
                "citation_presence": 1.0,
                "citation_fact_paragraphs": 1,
                "citation_cited_fact_paragraphs": 1,
                "valid_citation_ratio": 1.0,
                "citation_used": 1,
                "citation_valid": 1,
                "ungrounded_conclusions": 0,
            }
        ],
        None,
        None,
    )

    assert "| case-x | A0(朴素直出) | N/A | N/A | N/A | N/A | N/A |" in table
    assert "| case-x | A(带引用直出) | N/A | N/A | N/A | N/A | N/A |" in table
    assert "| case-x | B(证据链) | 1.00 | 1.00 | 0 | 1.00 | 0 |" in table
