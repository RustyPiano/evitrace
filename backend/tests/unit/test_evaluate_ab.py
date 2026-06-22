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


def test_free_text_ungrounded_conclusions_counts_fact_paragraphs_without_citations():
    module = load_module()

    count = module.count_free_text_ungrounded_conclusions(
        "# Report\n\nAlpha arrived at 14:00.\n\nGeneral caveat.\n\nBravo stayed at E-0001."
    )

    assert count == 1
