# -*- coding: utf-8 -*-
"""Experiment 3: extract route-step mentions, hierarchy, and comparisons."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .common import DATA, OUT, ensure_outputs, iter_poi_mentions, load_poi_terms, read_jsonl, split_sentences_with_offsets, write_json


TIME_PATTERNS = [
    ("上午", re.compile(r"上午|早上|清晨")),
    ("中午", re.compile(r"中午")),
    ("下午", re.compile(r"下午|傍晚")),
    ("晚上", re.compile(r"晚上|夜间")),
    ("全天", re.compile(r"全天|一日游|一天")),
]
CLOCK_RE = re.compile(r"(?P<hour>\d{1,2}):\d{2}|(?P<hour_cn>\d{1,2})点(?:\d{1,2}分)?")
ACTIVITY_TERMS = {
    "enter": ["入馆", "入园", "进入"],
    "visit": ["参观", "游览", "游玩", "体验", "经过", "前往", "到", "去"],
    "view": ["观看", "看"],
    "walk": ["步行", "走到", "沿"],
    "transport": ["乘坐", "乘船", "坐", "乘车", "骑"],
    "eat": ["用餐", "吃饭", "午餐", "晚餐"],
    "rest": ["休息", "休息用餐"],
    "photo": ["拍照", "拍"],
    "exit": ["出馆", "出园", "离开", "离园"],
}
ARROW_RE = re.compile(r"(?:->|→|➡|➜|⇒)")
NUMBERED_RE = re.compile(r"(?m)(?:^|(?<=[。；\n]))\s*(?:第)?\d+[、．.)]\s*")


def _font(size: int = 20):
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _route_units(text: str) -> tuple[list[tuple[int, int, str]], list[str]]:
    def make_unit(start: int, end: int) -> tuple[int, int, str] | None:
        raw = text[start:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw) - len(raw.rstrip())
        left = start + leading
        right = end - trailing
        if left >= right:
            return None
        return left, right, text[left:right]

    formats = []
    numbered = list(NUMBERED_RE.finditer(text))
    if numbered:
        formats.append("numbered")
        starts = [match.start() for match in numbered]
        if starts[0] > 0 and text[: starts[0]].strip():
            starts.insert(0, 0)
        else:
            starts[0] = 0
        units = []
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(text)
            left = start
            while left < end and (text[left].isspace() or text[left].isdigit() or text[left] in "第、．.)"):
                left += 1
            unit = make_unit(left, end)
            if unit:
                units.append(unit)
        return units, formats

    arrows = list(ARROW_RE.finditer(text))
    if arrows:
        formats.append("arrow_chain")
        starts = [0] + [match.end() for match in arrows]
        ends = [match.start() for match in arrows] + [len(text)]
        units = [unit for left, right in zip(starts, ends) if (unit := make_unit(left, right))]
        return units, formats

    if re.search(r"上午|早上|中午|下午|傍晚|晚上|夜间", text):
        formats.append("time_segmented_prose")
    else:
        formats.append("prose")
    return [(0, len(text), text)], formats


def _time_at(text: str, index: int) -> tuple[str | None, str | None]:
    for bucket, pattern in TIME_PATTERNS:
        match = pattern.search(text, max(0, index - 8), min(len(text), index + 18))
        if match:
            return bucket, match.group()
    match = CLOCK_RE.search(text, max(0, index - 8), min(len(text), index + 18))
    if match:
        hour = int(match.group("hour") or match.group("hour_cn"))
        if 5 <= hour < 11:
            bucket = "上午"
        elif 11 <= hour < 14:
            bucket = "中午"
        elif 14 <= hour < 18:
            bucket = "下午"
        else:
            bucket = "晚上"
        return bucket, match.group()
    return None, None


def _activity_for(text: str, local_start: int, local_end: int) -> list[dict[str, str]]:
    hits = []
    for category, terms in ACTIVITY_TERMS.items():
        for term in terms:
            for match in re.finditer(re.escape(term), text):
                distance = 0 if match.start() <= local_start < match.end() else min(abs(match.start() - local_start), abs(match.end() - local_start))
                if distance <= 22 or (match.start() < local_start and local_start - match.end() <= 12):
                    hits.append((distance, match.start(), category, term))
    if not hits:
        return []
    hits.sort()
    selected = []
    for _, _, category, term in hits:
        if not any(item["type"] == category for item in selected):
            selected.append({"type": category, "text": term})
        if len(selected) == 2:
            break
    return selected


def parse_route(row: dict[str, Any], poi_terms: list[str]) -> tuple[dict, list[dict]]:
    text = row["content"]
    units, formats = _route_units(text)
    steps = []
    current_bucket = "未标注时段"
    current_time_text = None
    block_index = 0
    last_bucket = None

    for unit_start, unit_end, unit_text in units:
        for sentence_start, sentence_end, sentence in split_sentences_with_offsets(unit_text):
            abs_sentence_start = unit_start + sentence_start
            mentions = iter_poi_mentions(sentence, poi_terms)
            if not mentions:
                found_bucket, found_text = _time_at(sentence, 0)
                if found_bucket:
                    current_bucket, current_time_text = found_bucket, found_text
                continue
            for mention in mentions:
                found_bucket, found_text = _time_at(sentence, mention["start"])
                if found_bucket:
                    current_bucket, current_time_text = found_bucket, found_text
                bucket = current_bucket
                if bucket != last_bucket:
                    block_index += 1
                    last_bucket = bucket
                prefix = sentence[: mention["start"]]
                return_match = re.search(r"(?:返回|回到|返至|再回到)\s*$", prefix)
                context_start = max(0, mention["start"] - 32)
                context_end = min(len(sentence), mention["end"] + 32)
                source_start = abs_sentence_start + mention["start"]
                source_end = abs_sentence_start + mention["end"]
                steps.append(
                    {
                        "step_id": f"{row['record_id']}_step_{len(steps) + 1:03d}",
                        "route_id": row["record_id"],
                        "step_index": len(steps) + 1,
                        "time_block_index": block_index,
                        "time_bucket": bucket,
                        "time_evidence": current_time_text,
                        "poi_surface": mention["surface"],
                        "poi_canonical": mention["canonical"],
                        "activity": _activity_for(sentence, mention["start"], mention["end"]),
                        "event_kind": "return" if return_match else "visit",
                        "source_span": {"start": source_start, "end": source_end, "unit": "unicode_codepoint"},
                        "evidence_span": {
                            "start": abs_sentence_start + context_start,
                            "end": abs_sentence_start + context_end,
                            "text": sentence[context_start:context_end],
                            "unit": "unicode_codepoint",
                        },
                    }
                )

    route = {
        "route_id": row["record_id"],
        "attraction": row["attraction"],
        "text_type": row["text_type"],
        "title": row["title"],
        "source": row["source"],
        "source_url": row.get("source_url", ""),
        "format_detected": formats,
        "source_text": text,
        "step_count": len(steps),
        "steps": [item["step_id"] for item in steps],
    }
    return route, steps


def _unique_sequence(steps: list[dict], event_kind: str | None = "visit") -> list[str]:
    sequence = []
    for step in steps:
        if event_kind and step["event_kind"] != event_kind:
            continue
        name = step["poi_canonical"]
        if name not in sequence:
            sequence.append(name)
    return sequence


def _lcs_length(left: list[str], right: list[str]) -> int:
    row = [0] * (len(right) + 1)
    for a in left:
        previous = 0
        for j, b in enumerate(right, 1):
            old = row[j]
            row[j] = previous + 1 if a == b else max(row[j], row[j - 1])
            previous = old
    return row[-1]


def _order_consistency(official: list[str], traveler: list[str]) -> float | None:
    shared_order = [name for name in traveler if name in official]
    if len(shared_order) < 2:
        return None
    positions = [official.index(name) for name in shared_order]
    pairs = [(positions[i], positions[j]) for i in range(len(positions)) for j in range(i + 1, len(positions))]
    return round(sum(a < b for a, b in pairs) / len(pairs), 4)


def _time_shares(steps: list[dict]) -> dict[str, float]:
    counts = Counter(step["time_bucket"] for step in steps if step["event_kind"] == "visit")
    total = sum(counts.values())
    return {key: round(value / total, 4) for key, value in sorted(counts.items())} if total else {}


def build_hierarchy(routes: list[dict], steps: list[dict]) -> list[dict]:
    by_route: dict[str, list[dict]] = defaultdict(list)
    for step in steps:
        by_route[step["route_id"]].append(step)
    hierarchies = []
    for route in routes:
        blocks = []
        for step in by_route[route["route_id"]]:
            if not blocks or blocks[-1]["block_index"] != step["time_block_index"]:
                blocks.append({"block_index": step["time_block_index"], "time_bucket": step["time_bucket"], "step_ids": []})
            blocks[-1]["step_ids"].append(step["step_id"])
        hierarchies.append(
            {
                "attraction": route["attraction"],
                "route_id": route["route_id"],
                "root": route["attraction"],
                "time_blocks": blocks,
            }
        )
    return hierarchies


def compare_routes(routes: list[dict], steps: list[dict]) -> list[dict]:
    route_steps: dict[str, list[dict]] = defaultdict(list)
    for step in steps:
        route_steps[step["route_id"]].append(step)
    official = {route["attraction"]: route for route in routes if route["text_type"] == "official_route"}
    comparisons = []
    for traveler in routes:
        if traveler["text_type"] != "traveler_note" or traveler["attraction"] not in official:
            continue
        official_route = official[traveler["attraction"]]
        official_seq = _unique_sequence(route_steps[official_route["route_id"]])
        traveler_seq = _unique_sequence(route_steps[traveler["route_id"]])
        shared = [poi for poi in official_seq if poi in traveler_seq]
        coverage = len(shared) / len(official_seq) if official_seq else 0.0
        union = len(set(official_seq) | set(traveler_seq))
        lcs = _lcs_length(official_seq, traveler_seq)
        official_time = _time_shares(route_steps[official_route["route_id"]])
        traveler_time = _time_shares(route_steps[traveler["route_id"]])
        time_keys = set(official_time) | set(traveler_time)
        time_delta = 0.5 * sum(abs(official_time.get(key, 0.0) - traveler_time.get(key, 0.0)) for key in time_keys)
        comparisons.append(
            {
                "comparison_id": f"cmp_{official_route['route_id']}__{traveler['route_id']}",
                "attraction": traveler["attraction"],
                "official_route_id": official_route["route_id"],
                "traveler_route_id": traveler["route_id"],
                "official_poi_sequence": official_seq,
                "traveler_poi_sequence": traveler_seq,
                "shared_pois": shared,
                "official_coverage": round(coverage, 4),
                "sequence_lcs_similarity": round(lcs / union, 4) if union else 0.0,
                "order_consistency": _order_consistency(official_seq, traveler_seq),
                "official_time_share": official_time,
                "traveler_time_share": traveler_time,
                "time_distribution_total_variation": round(time_delta, 4),
                "interpretation": _interpret_comparison(coverage, time_delta, official_seq, traveler_seq),
            }
        )
    return comparisons


def _interpret_comparison(coverage: float, time_delta: float, official: list[str], traveler: list[str]) -> str:
    extras = [poi for poi in traveler if poi not in official]
    omitted = [poi for poi in official if poi not in traveler]
    parts = [f"官方节点覆盖率为 {coverage:.2f}"]
    if omitted:
        parts.append("游客路线未包含 " + "、".join(omitted[:4]))
    if extras:
        parts.append("游客文本额外提到 " + "、".join(extras[:4]))
    parts.append("时间层分布差异较大" if time_delta >= 0.35 else "时间层分布相对接近")
    return "；".join(parts) + "。"


def draw_hierarchy(route: dict, steps: list[dict], path) -> None:
    width, height = 1350, 720
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font, font = _font(30), _font(22)
    draw.text((45, 25), f"{route['attraction']} 路线时间层级（单景点提及一步）", fill=(25, 35, 48), font=title_font)
    colors = {"上午": (45, 111, 173), "中午": (211, 130, 47), "下午": (55, 140, 100), "晚上": (125, 85, 150), "全天": (85, 120, 140), "未标注时段": (120, 120, 120)}
    groups: dict[int, list[dict]] = defaultdict(list)
    for step in steps:
        groups[step["time_block_index"]].append(step)
    x = 45
    available_width = width - 90
    group_width = max(205, min(available_width // max(len(groups), 1), 310))
    for block_index, items in groups.items():
        x = 45 + (block_index - min(groups, default=1)) * group_width
        bucket = items[0]["time_bucket"]
        color = colors.get(bucket, colors["未标注时段"])
        draw.rounded_rectangle((x, 95, x + group_width - 18, 145), radius=7, fill=color)
        draw.text((x + 12, 107), f"{bucket} / Block {block_index}", fill="white", font=font)
        for i, step in enumerate(items):
            y = 175 + i * 56
            label = f"{step['step_index']}. {step['poi_canonical']}"
            if step["event_kind"] == "return":
                label += " (返程)"
            draw.rounded_rectangle((x + 5, y, x + group_width - 23, y + 38), radius=5, fill=(246, 249, 251), outline=color, width=2)
            draw.text((x + 15, y + 7), label[:25], fill=(35, 45, 55), font=font)
            if i:
                draw.line((x + group_width // 2 - 10, y - 14, x + group_width // 2 - 10, y), fill=(120, 130, 140), width=2)
    draw.text((45, height - 48), "排序依据：原文顺序；重复 POI 提及保留；返程事件保留但比较主路线时单独排除。", fill=(85, 95, 105), font=_font(17))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def run() -> dict[str, Any]:
    ensure_outputs()
    rows = read_jsonl(DATA / "cleaned_data.jsonl")
    poi_terms = load_poi_terms()
    route_rows = [row for row in rows if row["text_type"] in {"official_route", "traveler_note"}]
    routes, steps = [], []
    for row in route_rows:
        route, route_steps = parse_route(row, poi_terms)
        routes.append(route)
        steps.extend(route_steps)
    hierarchy = build_hierarchy(routes, steps)
    comparisons = compare_routes(routes, steps)
    official_routes = [route for route in routes if route["text_type"] == "official_route"]
    selected_route = official_routes[0] if official_routes else None
    selected_steps = [step for step in steps if selected_route and step["route_id"] == selected_route["route_id"]]
    fixture_results = validate_format_fixtures(poi_terms)
    source_by_id = {row["record_id"]: row["content"] for row in route_rows}
    span_integrity = all(
        source_by_id[step["route_id"]][step["source_span"]["start"] : step["source_span"]["end"]] == step["poi_surface"]
        and source_by_id[step["route_id"]][step["evidence_span"]["start"] : step["evidence_span"]["end"]] == step["evidence_span"]["text"]
        for step in steps
    )
    if not span_integrity:
        raise ValueError("One or more experiment 3 source spans do not resolve to their evidence text")
    out = OUT / "exp3"
    write_json(out / "route_records.json", routes)
    write_json(out / "route_steps.json", steps)
    write_json(out / "route_hierarchy.json", hierarchy)
    write_json(out / "route_comparisons.json", comparisons)
    write_json(out / "format_fixture_results.json", fixture_results)
    if selected_route:
        draw_hierarchy(selected_route, selected_steps, out / "route_hierarchy.png")
    mean_coverage = sum(item["official_coverage"] for item in comparisons) / len(comparisons) if comparisons else 0.0
    mean_order = [item["order_consistency"] for item in comparisons if item["order_consistency"] is not None]
    summary = {
        "source_records": len(route_rows),
        "route_records": len(routes),
        "route_step_mentions": len(steps),
        "source_span_integrity": {"passed": span_integrity, "checked_steps": len(steps)},
        "official_routes": len(official_routes),
        "traveler_routes": sum(route["text_type"] == "traveler_note" for route in routes),
        "route_format_counts": dict(Counter(fmt for route in routes for fmt in route["format_detected"])),
        "format_fixture_tests": fixture_results,
        "comparison_count": len(comparisons),
        "mean_official_coverage": round(mean_coverage, 4),
        "mean_order_consistency": round(sum(mean_order) / len(mean_order), 4) if mean_order else None,
    }
    write_json(out / "summary.json", summary)
    return summary


def validate_format_fixtures(poi_terms: list[str]) -> list[dict[str, Any]]:
    fixtures = json.loads((DATA / "route_format_fixtures.json").read_text(encoding="utf-8"))
    results = []
    for fixture in fixtures:
        row = {
            "record_id": fixture["fixture_id"],
            "attraction": fixture["attraction"],
            "text_type": "official_route",
            "title": fixture["fixture_id"],
            "source": "synthetic_parser_fixture",
            "source_url": "",
            "content": fixture["text"],
        }
        route, steps = parse_route(row, poi_terms)
        actual = [step["poi_canonical"] for step in steps]
        expected = fixture["expected_pois"]
        passed = route["format_detected"][0] == fixture["expected_format"] and actual == expected
        results.append(
            {
                "fixture_id": fixture["fixture_id"],
                "expected_format": fixture["expected_format"],
                "detected_formats": route["format_detected"],
                "expected_pois": expected,
                "actual_pois": actual,
                "passed": passed,
            }
        )
        if not passed:
            raise AssertionError(f"Route parser fixture failed: {fixture['fixture_id']}")
    return results


if __name__ == "__main__":
    print(run())
