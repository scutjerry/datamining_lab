# -*- coding: utf-8 -*-
"""Experiment 4: pronoun mention detection and nearest-POI coreference."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .common import DATA, OUT, ensure_outputs, iter_poi_mentions, load_poi_terms, read_json, read_jsonl, split_sentences_with_offsets, write_json


PRONOUNS = ["那里", "这里", "此处", "这个", "那个", "他们", "她们", "它们", "它", "其", "这些", "那些", "这", "那"]


def detect_mentions(text: str) -> list[dict[str, Any]]:
    pattern = re.compile("|".join(re.escape(term) for term in sorted(PRONOUNS, key=lambda item: (-len(item), item))))
    occurrences: dict[str, int] = defaultdict(int)
    sentences = split_sentences_with_offsets(text)
    mentions = []
    for match in pattern.finditer(text):
        pronoun = match.group()
        occurrences[pronoun] += 1
        sentence_start, sentence_end, sentence = next(
            ((start, end, value) for start, end, value in sentences if start <= match.start() < end),
            (0, len(text), text),
        )
        mentions.append(
            {
                "pronoun": pronoun,
                "occurrence": occurrences[pronoun],
                "start": match.start(),
                "end": match.end(),
                "sentence_span": {"start": sentence_start, "end": sentence_end, "unit": "unicode_codepoint"},
                "sentence": sentence,
            }
        )
    return mentions


def antecedent_span(text: str, antecedent: str, before: int, poi_terms: list[str]) -> dict | None:
    candidates = [item for item in iter_poi_mentions(text[:before], poi_terms) if item["canonical"] == antecedent or item["surface"] == antecedent]
    if not candidates:
        return None
    item = candidates[-1]
    return {"start": item["start"], "end": item["end"], "text": item["surface"], "unit": "unicode_codepoint"}


def run() -> dict[str, Any]:
    ensure_outputs()
    rows = read_jsonl(DATA / "cleaned_data.jsonl")
    poi_terms = load_poi_terms()
    gold_rows = read_json(DATA / "coref_gold.json")
    gold_map = {(item["record_id"], item["pronoun"], item["occurrence"]): item for item in gold_rows}
    samples = []
    resolved = []
    for row in rows:
        text = row["content"]
        poi_mentions = iter_poi_mentions(text, poi_terms)
        for mention in detect_mentions(text):
            preceding = [item for item in poi_mentions if item["end"] <= mention["start"]]
            candidate = max(preceding, key=lambda item: item["end"], default=None)
            predicted = candidate["canonical"] if candidate else None
            gold = gold_map.get((row["record_id"], mention["pronoun"], mention["occurrence"]))
            gold_text = gold.get("antecedent") if gold else None
            prediction_correct = (predicted == gold_text) if gold else None
            sample = {
                "mention_id": f"{row['record_id']}_{mention['pronoun']}_{mention['occurrence']:02d}",
                "record_id": row["record_id"],
                "attraction": row["attraction"],
                "text_type": row["text_type"],
                "pronoun": mention["pronoun"],
                "occurrence": mention["occurrence"],
                "pronoun_span": {"start": mention["start"], "end": mention["end"], "unit": "unicode_codepoint"},
                "sentence_span": mention["sentence_span"],
                "sentence": mention["sentence"],
                "candidate_antecedent": (
                    {"text": candidate["surface"], "canonical": candidate["canonical"], "span": {"start": candidate["start"], "end": candidate["end"], "unit": "unicode_codepoint"}}
                    if candidate
                    else None
                ),
                "predicted_antecedent": predicted,
                "predicted_antecedent_span": candidate and {"start": candidate["start"], "end": candidate["end"], "text": candidate["surface"], "unit": "unicode_codepoint"},
                "gold_antecedent": gold_text,
                "gold_antecedent_span": antecedent_span(text, gold_text, mention["start"], poi_terms) if gold_text else None,
                "annotation_status": "preannotated_pending_student_review" if gold else "unlabeled",
                "annotation_origin": gold.get("annotation_source") if gold else None,
                "annotation_note": gold.get("note", "建议先行词，提交前需由学生核验") if gold else None,
                "correct": prediction_correct,
                "method": "最近的前置 POI 表面提及，名称按别名表归一化",
            }
            samples.append(sample)
            if predicted:
                resolved.append(
                    {
                        "mention_id": sample["mention_id"],
                        "record_id": row["record_id"],
                        "pronoun": mention["pronoun"],
                        "antecedent": predicted,
                        "sentence": mention["sentence"],
                        "resolved_sentence": mention["sentence"][: mention["start"] - mention["sentence_span"]["start"]]
                        + predicted
                        + mention["sentence"][mention["end"] - mention["sentence_span"]["start"] :],
                    }
                )

    preannotated = [item for item in samples if item["annotation_status"] == "preannotated_pending_student_review"]
    source_by_id = {row["record_id"]: row["content"] for row in rows}
    span_checks = []
    for item in samples:
        source_text = source_by_id[item["record_id"]]
        pspan = item["pronoun_span"]
        sspan = item["sentence_span"]
        span_checks.append(source_text[pspan["start"] : pspan["end"]] == item["pronoun"])
        span_checks.append(source_text[sspan["start"] : sspan["end"]] == item["sentence"])
    if not all(span_checks):
        raise ValueError("One or more experiment 4 source spans do not resolve to their evidence text")
    correct = sum(item["correct"] is True for item in preannotated)
    evaluated = {
        "preannotated_mentions": len(preannotated),
        "student_confirmed_mentions": 0,
        "correct_mentions": correct,
        "accuracy_against_preannotations": round(correct / len(preannotated), 4) if preannotated else None,
        "formal_student_verified_accuracy": None,
        "coverage_over_all_detected": round(len(preannotated) / len(samples), 4) if samples else 0.0,
        "detected_mentions": len(samples),
        "unlabeled_mentions": len(samples) - len(preannotated),
        "student_review_pending": True,
        "source_span_integrity": {"passed": all(span_checks), "checked_spans": len(span_checks)},
        "errors_against_preannotations": [item["mention_id"] for item in preannotated if not item["correct"]],
        "limitation": "先行词为助手预标注，尚待学生人工核验；样本量仅 5 条，且规则只查找同文档最近的前置 POI，不能据此推断跨句泛化性能。",
    }
    out = OUT / "exp4"
    write_json(out / "pronoun_mentions.json", samples)
    write_json(out / "coreference_annotations.json", preannotated)
    write_json(out / "resolved_examples.json", resolved)
    write_json(out / "evaluation.json", evaluated)
    return evaluated


if __name__ == "__main__":
    print(run())
