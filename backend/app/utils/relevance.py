from __future__ import annotations

from collections import Counter, defaultdict
import math
import re
import unicodedata
from typing import Any, Callable


HIGH_SIGNAL_BOOST = 0.25
MIN_IDF = 1e-9
TOKEN_RE = re.compile(r"[\u3400-\u9fff]+|[a-z0-9]+")
HIGH_SIGNAL_RE = re.compile(
    r"(\d{4}-\d{1,2}-\d{1,2})|"
    r"(\d{1,2}:\d{2})|"
    r"(\d{1,2}\s*[月/]\s*\d{1,2}\s*[日号]?)|"
    r"(\d+(?:\.\d+)?\s*(?:辆|人|枚|架|艘|公里|千米|米|时|小时|分钟|分|秒|吨|公斤|千克|个|处|批|次|%))"
)


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    tokens: list[str] = []
    for match in TOKEN_RE.finditer(normalized):
        value = match.group(0)
        if re.fullmatch(r"[a-z0-9]+", value):
            tokens.append(value)
        elif len(value) == 1:
            tokens.append(value)
        else:
            tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
    return tokens


def _has_high_signal(text: str) -> bool:
    return HIGH_SIGNAL_RE.search(unicodedata.normalize("NFKC", text or "")) is not None


def score_documents(objective: str, docs: list[str]) -> list[float]:
    query_terms = set(tokenize(objective))
    if not query_terms:
        return [0.0 for _doc in docs]

    tokenized_docs = [tokenize(doc) for doc in docs]
    if not tokenized_docs:
        return []

    doc_count = len(tokenized_docs)
    avgdl = sum(len(tokens) for tokens in tokenized_docs) / doc_count
    if avgdl <= 0:
        return [0.0 for _doc in docs]

    dfs: Counter[str] = Counter()
    for tokens in tokenized_docs:
        dfs.update(set(tokens) & query_terms)

    k1 = 1.5
    b = 0.75
    scores: list[float] = []
    for doc, tokens in zip(docs, tokenized_docs, strict=True):
        if not tokens:
            scores.append(0.0)
            continue
        counts = Counter(tokens)
        dl = len(tokens)
        score = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if tf <= 0:
                continue
            df = dfs.get(term, 0)
            idf = max(math.log((doc_count - df + 0.5) / (df + 0.5)), MIN_IDF)
            denom = tf + k1 * (1 - b + b * dl / avgdl)
            score += idf * (tf * (k1 + 1)) / denom
        if score > 0 and _has_high_signal(doc):
            score *= 1 + HIGH_SIGNAL_BOOST
        scores.append(score)
    return scores


def _item_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("content") or item.get("content_summary") or "")
    return str(item or "")


def select_relevant(
    items: list[Any],
    objective: str,
    top_k: int,
    per_doc_min: int,
    doc_key: Callable[[Any], str],
) -> tuple[list[int], dict[str, int]]:
    original = len(items)
    if original == 0:
        return [], {
            "original": 0,
            "kept": 0,
            "dropped": 0,
            "top_k": top_k,
            "per_doc_min": per_doc_min,
        }

    scores = score_documents(objective, [_item_text(item) for item in items])
    initial_count = min(max(top_k, 0), original)
    ranked = sorted(range(original), key=lambda index: (-scores[index], index))
    selected = set(ranked[:initial_count])

    target_per_doc = max(per_doc_min, 0)
    if target_per_doc > 0:
        by_doc: dict[str, list[int]] = defaultdict(list)
        for index, item in enumerate(items):
            by_doc[str(doc_key(item))].append(index)
        for indices in by_doc.values():
            selected_count = sum(1 for index in indices if index in selected)
            missing = min(target_per_doc, len(indices)) - selected_count
            if missing <= 0:
                continue
            doc_ranked = sorted(indices, key=lambda index: (-scores[index], index))
            for index in doc_ranked:
                if index in selected:
                    continue
                selected.add(index)
                missing -= 1
                if missing <= 0:
                    break

    kept_indices = sorted(selected)
    return kept_indices, {
        "original": original,
        "kept": len(kept_indices),
        "dropped": original - len(kept_indices),
        "top_k": top_k,
        "per_doc_min": per_doc_min,
    }
