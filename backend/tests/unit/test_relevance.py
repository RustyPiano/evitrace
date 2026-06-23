from app.utils.relevance import score_documents, select_relevant, tokenize


def test_tokenize_extracts_cjk_bigrams_ascii_words_and_normalizes_width_case():
    assert tokenize("ＡＢＣ-12 侦察车队 A镇") == [
        "abc",
        "12",
        "侦察",
        "察车",
        "车队",
        "a",
        "镇",
    ]


def test_score_documents_prefers_objective_terms_and_high_signal_without_zero_division():
    scores = score_documents(
        "车队 A镇",
        [
            "6月1日14:00，车队抵达A镇，发现3辆车。",
            "天气晴朗，附近道路通畅。",
            "",
        ],
    )

    assert len(scores) == 3
    assert scores[0] > scores[1]
    assert scores[2] == 0
    assert score_documents("", ["车队", "无关"]) == [0.0, 0.0]
    assert score_documents("车队", ["", ""]) == [0.0, 0.0]


def test_select_relevant_applies_top_k_per_doc_fallback_stable_order_and_stats():
    items = [
        {"content": "目标车队抵达A镇", "file": {"id": "doc-a"}},
        {"content": "目标车队发现车辆", "file": {"id": "doc-a"}},
        {"content": "完全无关文本", "file": {"id": "doc-b"}},
        {"content": "另一段无关文本", "file": {"id": "doc-b"}},
    ]

    kept, stats = select_relevant(
        items,
        "目标车队",
        top_k=1,
        per_doc_min=1,
        doc_key=lambda item: item["file"]["id"],
    )

    assert kept == [0, 2]
    assert stats == {
        "original": 4,
        "kept": 2,
        "dropped": 2,
        "top_k": 1,
        "per_doc_min": 1,
    }


def test_select_relevant_uses_index_tiebreaker_and_original_order_for_output():
    items = [
        {"content": "alpha", "file": {"id": "doc-a"}},
        {"content": "alpha", "file": {"id": "doc-a"}},
        {"content": "alpha", "file": {"id": "doc-a"}},
    ]

    kept, _stats = select_relevant(
        items,
        "missing",
        top_k=2,
        per_doc_min=0,
        doc_key=lambda item: item["file"]["id"],
    )

    assert kept == [0, 1]


def test_select_relevant_empty_objective_takes_first_k_then_per_doc_fallback():
    items = [
        {"content": "first", "file": {"id": "doc-a"}},
        {"content": "second", "file": {"id": "doc-a"}},
        {"content": "third", "file": {"id": "doc-b"}},
    ]

    kept, stats = select_relevant(
        items,
        "",
        top_k=1,
        per_doc_min=1,
        doc_key=lambda item: item["file"]["id"],
    )

    assert kept == [0, 2]
    assert stats["dropped"] == 1
