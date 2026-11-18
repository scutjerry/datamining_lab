# -*- coding: utf-8 -*-
"""Experiment 5: extract atomic, evidence-linked condition/advice mappings."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .common import DATA, OUT, ensure_outputs, normalize_surface, read_json, read_jsonl, split_sentences_with_offsets, write_json


CONDITION_CLASSES = {
    "weather": ["下雨", "雨势较大", "天气不好", "天气炎热", "天气热", "天气"],
    "visitor_type": ["带父母", "带老人", "带孩子", "亲子", "情侣"],
    "time_constraint": ["只有半天", "时间紧", "想看夕阳", "想看烟花", "半天", "一天"],
    "crowd_level": ["游客多", "人多", "想少排队", "少排队", "排队"],
    "preference": ["想拍建筑"],
}
CONDITION_TERMS = sorted({term for values in CONDITION_CLASSES.values() for term in values}, key=lambda item: (-len(item), item))
CONDITION_RE = re.compile("|".join(re.escape(term) for term in CONDITION_TERMS))
EXPLICIT_RE = re.compile(r"(?P<marker>如果|假如|若是|若)(?P<condition>[^，,。；;]+)(?:[，,]|则|就)(?P<body>[^。；;]+)")
RECOMMENDATION_RE = re.compile(r"建议|最好|可以|可|优先|则|就|先|改成|减少|取消|多找|改为")
ADVICE_SPLIT_RE = re.compile(r"并且|同时|以及|并|或|；|;|，|,")
LEADING_RECOMMENDATION_RE = re.compile(r"^(?:建议|最好|可以|可|优先|则|就)\s*")


def condition_type(text: str) -> str:
    for kind, terms in CONDITION_CLASSES.items():
        if any(term in text for term in terms):
            return kind
    return "other"


def _trim_span(sentence: str, start: int, end: int) -> tuple[int, int, str]:
    while start < end and (sentence[start].isspace() or sentence[start] in " ，,：:。；;！？!?"):
        start += 1
    while end > start and (sentence[end - 1].isspace() or sentence[end - 1] in " ，,：:。；;！？!?"):
        end -= 1
    return start, end, sentence[start:end]


def _advice_atoms(sentence: str, start: int, end: int) -> list[tuple[int, int, str]]:
    start, end, _ = _trim_span(sentence, start, end)
    while True:
        marker = LEADING_RECOMMENDATION_RE.match(sentence[start:end])
        if not marker:
            break
        start += marker.end()
        start, end, _ = _trim_span(sentence, start, end)
    raw_atoms = []
    cursor = start
    for match in ADVICE_SPLIT_RE.finditer(sentence, start, end):
        left, right, text = _trim_span(sentence, cursor, match.start())
        if text:
            raw_atoms.append((left, right, text))
        cursor = match.end()
    left, right, text = _trim_span(sentence, cursor, end)
    if text:
        raw_atoms.append((left, right, text))
    atoms = []
    continuation = re.compile(
        r"^(?:并|同时|再|接着|随后|然后|也|还|先|雨小后|雨停后|改天|早点|提前|减少|取消|多|少|穿|带|避开|改成|改为|预留|预约|休息|离开|不要|不必|优先|选择|安排|确认|慢慢|把|从|乘|坐|步行|去|到|看)"
    )
    independent_recommendation = re.compile(r"建议|最好|可以|优先|记得|應当|应当|需要|不妨")
    time_led_action = re.compile(r"^(?:早上|上午|中午|下午|傍晚|晚上).*(?:先|再|可以|建议|最好|优先)")
    for index, atom in enumerate(raw_atoms):
        atom_start, atom_end, atom_text = atom
        if atom_text.endswith(("后", "时")):
            continue
        if index == 0 or atom_text.startswith("乘船") or continuation.search(atom_text) or independent_recommendation.search(atom_text) or time_led_action.search(atom_text):
            atoms.append(atom)
    return atoms


def extract_sentence(sentence: str, row: dict[str, Any], sentence_index: int, sentence_offset: int) -> list[dict[str, Any]]:
    candidates = []
    explicit = list(EXPLICIT_RE.finditer(sentence))
    if explicit:
        for match in explicit:
            c_start, c_end, condition = _trim_span(sentence, match.start("condition"), match.end("condition"))
            body_start, body_end = match.start("body"), match.end("body")
            recommendation = RECOMMENDATION_RE.search(sentence, body_start, body_end)
            if recommendation:
                advice_start = recommendation.start() if recommendation.group() in {"先", "减少", "取消", "改成", "改为", "多找"} else recommendation.end()
                atoms = _advice_atoms(sentence, advice_start, body_end)
            else:
                atoms = _advice_atoms(sentence, body_start, body_end)
            candidates.append((c_start, c_end, condition, atoms, "explicit_conditional"))
    else:
        for condition_match in CONDITION_RE.finditer(sentence):
            condition_start, condition_end, condition = _trim_span(sentence, condition_match.start(), condition_match.end())
            tail_start = condition_end
            tail_end = min(len(sentence), condition_end + 48)
            recommendation = RECOMMENDATION_RE.search(sentence, tail_start, tail_end)
            if not recommendation:
                continue
            advice_start = recommendation.start() if recommendation.group() in {"先", "减少", "取消", "改成", "改为", "多找"} else recommendation.end()
            atoms = _advice_atoms(sentence, advice_start, len(sentence))
            if atoms:
                candidates.append((condition_start, condition_end, condition, atoms, "implicit_condition_with_recommendation"))

    results = []
    seen_local = set()
    for condition_start, condition_end, condition, atoms, pattern_name in candidates:
        if not condition:
            continue
        for advice_start, advice_end, advice in atoms:
            key = (condition_start, condition_end, normalize_surface(condition), advice_start, advice_end, normalize_surface(advice))
            if key in seen_local:
                continue
            seen_local.add(key)
            results.append(
                {
                    "attraction": row["attraction"],
                    "record_id": row["record_id"],
                    "text_type": row["text_type"],
                    "sentence_index": sentence_index,
                    "condition_type": condition_type(condition),
                    "condition_text": condition,
                    "condition_span": {"start": sentence_offset + condition_start, "end": sentence_offset + condition_end, "unit": "unicode_codepoint"},
                    "advice_text": advice,
                    "advice_span": {"start": sentence_offset + advice_start, "end": sentence_offset + advice_end, "unit": "unicode_codepoint"},
                    "sentence_span": {"start": sentence_offset, "end": sentence_offset + len(sentence), "unit": "unicode_codepoint"},
                    "evidence_sentence": sentence,
                    "rule": pattern_name,
                }
            )
    return results


def aggregate_mappings(mentions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in mentions:
        key = (
            item["attraction"],
            item["condition_type"],
            normalize_surface(item["condition_text"]),
            normalize_surface(item["advice_text"]),
        )
        groups[key].append(item)
    mappings = []
    for index, (key, evidence) in enumerate(sorted(groups.items()), 1):
        attraction, kind, condition_norm, advice_norm = key
        mappings.append(
            {
                "mapping_id": f"map_{index:04d}",
                "attraction": attraction,
                "condition_type": kind,
                "condition": {"text": evidence[0]["condition_text"], "normalized": condition_norm},
                "advice": {"text": evidence[0]["advice_text"], "normalized": advice_norm},
                "evidence_count": len(evidence),
                "source_record_ids": sorted({item["record_id"] for item in evidence}),
                "evidence": evidence,
                "dedup_key": "attraction + condition_type + normalized_condition + normalized_advice",
            }
        )
    return mappings


def draw_counts(counts: Counter, output) -> None:
    width, height = 1150, max(360, 100 + 62 * len(counts))
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_path = "C:/Windows/Fonts/msyh.ttc"
    try:
        title_font = ImageFont.truetype(font_path, 30)
        font = ImageFont.truetype(font_path, 22)
    except OSError:
        title_font = font = ImageFont.load_default()
    draw.text((45, 25), "实验5 条件类型映射数量（去重后）", fill=(25, 35, 48), font=title_font)
    max_count = max(counts.values(), default=1)
    palette = [(50, 112, 173), (211, 132, 48), (55, 140, 101), (132, 91, 153), (184, 78, 74), (90, 115, 125)]
    labels = {"weather": "天气", "visitor_type": "游客类型", "time_constraint": "时间约束", "crowd_level": "拥挤程度", "preference": "游览偏好", "other": "其他"}
    for index, (kind, count) in enumerate(counts.most_common()):
        y = 90 + index * 62
        draw.text((45, y + 4), labels.get(kind, kind), fill=(45, 55, 65), font=font)
        length = int(760 * count / max_count)
        draw.rounded_rectangle((270, y, 270 + length, y + 34), radius=5, fill=palette[index % len(palette)])
        draw.text((285 + length, y + 3), str(count), fill=(40, 50, 60), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def run() -> dict[str, Any]:
    ensure_outputs()
    rows = read_jsonl(DATA / "cleaned_data.jsonl")
    mentions = []
    for row in rows:
        for sentence_index, (start, _, sentence) in enumerate(split_sentences_with_offsets(row["content"]), 1):
            mentions.extend(extract_sentence(sentence, row, sentence_index, start))
    mappings = aggregate_mappings(mentions)
    counts = Counter(item["condition_type"] for item in mappings)
    source_by_id = {row["record_id"]: row for row in rows}
    span_checks = []
    for mapping in mappings:
        for evidence in mapping["evidence"]:
            source_text = source_by_id[evidence["record_id"]]["content"]
            condition_span = evidence["condition_span"]
            advice_span = evidence["advice_span"]
            sentence_span = evidence["sentence_span"]
            span_checks.append(
                source_text[condition_span["start"] : condition_span["end"]] == evidence["condition_text"]
                and source_text[advice_span["start"] : advice_span["end"]] == evidence["advice_text"]
                and source_text[sentence_span["start"] : sentence_span["end"]] == evidence["evidence_sentence"]
            )
    if not all(span_checks):
        raise ValueError("One or more experiment 5 source spans do not resolve to their evidence text")

    manual_review = read_json(DATA / "condition_review_candidates.json")
    review_keys = {
        (item["attraction"], normalize_surface(item["condition"]), normalize_surface(item["advice"])): item
        for item in manual_review
    }
    pending = []
    candidate_count = 0
    matched_keys = set()
    for mapping in mappings:
        key = (mapping["attraction"], mapping["condition"]["normalized"], mapping["advice"]["normalized"])
        candidate = review_keys.get(key)
        if candidate:
            mapping["student_review"] = {"status": "pending_student_confirmation", "suggested_note": candidate["review_note"], "review_scope": "assistant_precheck_candidate"}
            candidate_count += 1
            matched_keys.add(key)
        else:
            mapping["student_review"] = {"status": "pending_student_confirmation", "suggested_note": None, "review_scope": "not_in_precheck_sample"}
            pending.append(
                {
                    "mapping_id": mapping["mapping_id"],
                    "review_status": "pending_student_confirmation",
                    "review_checklist": ["condition 是否构成真实约束", "advice 是否为单项建议", "原文字符区间能否复现", "是否与已有映射近重复"],
                }
            )
    unmatched_candidates = sorted(set(review_keys) - matched_keys)
    if unmatched_candidates:
        raise ValueError(f"Review candidates do not match extracted mappings: {unmatched_candidates}")
    summary = {
        "condition_advice_mentions_before_dedup": len(mentions),
        "unique_mappings_after_dedup": len(mappings),
        "mappings_by_condition_type": dict(counts),
        "source_evidence_count": sum(item["evidence_count"] for item in mappings),
        "source_span_integrity": {"passed": all(span_checks), "checked_evidence": len(span_checks)},
        "student_review": {"assistant_precheck_candidates": candidate_count, "student_confirmed": 0, "student_confirmation_pending": True, "pending_outside_precheck_sample": len(pending), "formal_precision": None},
        "granularity": "每个映射表示一个条件与一个原子建议；跨文档重复映射合并并保留全部 evidence。",
    }
    out = OUT / "exp5"
    write_json(out / "condition_advice_mentions.json", mentions)
    write_json(out / "condition_advice_mappings.json", mappings)
    write_json(out / "student_review_queue.json", pending)
    write_json(out / "summary.json", summary)
    draw_counts(counts, out / "condition_type_counts.png")
    return summary


if __name__ == "__main__":
    print(run())
