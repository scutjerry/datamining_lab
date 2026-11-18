# -*- coding: utf-8 -*-
"""适配层：把成员B管线在真实数据上的输出转换为成员C的接口约定格式。"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

RUN = Path("/tmp/bwork/run-real")
OUT = Path("/tmp/bwork/adapt-out")

CHAIN_SPLIT = re.compile(r"->|→|>>|－|-")
NUM_PREFIX = re.compile(r"^[（(]?\d+[）).、:：]?\s*")
TRAIL_PUNCT = "。；;，, "
TRANSPORT_PREFIX = ["乘船至", "步行至", "乘车至", "乘索道至", "坐船至", "乘缆车至"]
DURATION = re.compile(r"[（(]约?\s*(\d+(?:\.\d+)?)\s*小时(?:行程)?[）)]|[（(]约?\s*(\d+)\s*分钟[）)]")

AUDIENCE_KW = [("老人", "老人"), ("父母", "老人"), ("长辈", "老人"), ("孩子", "亲子"),
               ("亲子", "亲子"), ("儿童", "亲子"), ("情侣", "情侣"), ("二人", "情侣")]
COND_TRIGGER = re.compile(r"(如果|假如|若是|若遇|若[^，。]{0,12}，|要是)")
ADVICE_TRIGGER = re.compile(r"(建议|可以|不妨|最好|那么|则应|应|就)")
TOURISM_KW = re.compile(r"(游览|参观|游玩|路线|景点|宫殿|门票|入园|进宫|展馆|园林|逛|逛完|中轴线)")
VISIT_VERB = re.compile(r"(参观|游览|去|逛|走|看|乘|坐|穿|带|避开|安排|选择|从|沿|到|登|进|出|游|转)")


def load_rows():
    return [json.loads(l) for l in (RUN / "data/cleaned_data.jsonl").open(encoding="utf-8")]


def load_poi_terms():
    terms = []
    for line in (RUN / "data/entity_dict.txt").read_text(encoding="utf-8").splitlines():
        if line.strip().endswith("|POI"):
            terms.append(line.rsplit("|", 1)[0].strip())
    return sorted(set(terms), key=lambda t: -len(t))


def is_poi(seg, terms):
    return any(t in seg for t in terms)


def clean_segment(seg):
    seg = seg.strip()
    seg = DURATION.sub("", seg)
    seg = seg.strip().strip("。；;，, 　").rstrip("）)").strip()
    seg = seg.strip().strip(TRAIL_PUNCT)
    seg = NUM_PREFIX.sub("", seg).strip()
    transport = None
    for p in TRANSPORT_PREFIX:
        if seg.startswith(p):
            transport = p[:-1]
            seg = seg[len(p):].strip()
            break
    return seg, transport


def extract_chains(docs, terms):
    routes, unparsed = [], []
    for doc in docs:
        lines = [ln.strip() for ln in doc["content"].split("\n") if ln.strip()]
        chain_hits = []
        for line in lines:
            segments = [s for s in CHAIN_SPLIT.split(line) if s.strip()]
            if len(segments) < 3:
                continue
            segs = [clean_segment(s) for s in segments]
            poi_n = sum(1 for s, _ in segs if s and is_poi(s, terms))
            if poi_n < 3 or poi_n < len(segs) * 0.5:
                continue
            m = DURATION.search(line)
            duration = None
            if m:
                duration = int(float(m.group(1)) * 60) if m.group(1) else int(m.group(2))
            chain_hits.append({"line": line, "segs": segs, "duration_min": duration})

        if not chain_hits:
            if doc["text_type"] == "official_route":
                unparsed.append(doc["record_id"])
            continue

        for k, hit in enumerate(chain_hits, 1):
            steps = []
            segs = hit["segs"]
            for i, (poi, _t) in enumerate(segs):
                if not poi:
                    continue
                nxt_t = segs[i + 1][1] if i + 1 < len(segs) else None
                steps.append({
                    "step": len(steps) + 1,
                    "time_slot": None,
                    "poi_name": poi,
                    "activity": "",
                    "transport_to_next": nxt_t,
                    "duration_min": None,
                })
            if len(steps) < 3:
                continue
            routes.append({
                "route_id": f"{doc['record_id']}-CHAIN-{k:02d}",
                "scenic": doc["attraction"],
                "route_type": "official" if doc["text_type"] == "official_route" else "visitor",
                "source_doc_id": doc["record_id"],
                "route_title": doc["title"],
                "route_duration_min": hit["duration_min"],
                "steps": steps,
            })
    return routes, unparsed


def extract_advices_fallback(docs):
    advices = []
    for doc in docs:
        for sent in re.split(r"[。！？\n]+", doc["content"]):
            sent = sent.strip()
            if not (6 <= len(sent) <= 120):
                continue
            m = COND_TRIGGER.search(sent)
            if not m or not TOURISM_KW.search(sent):
                continue
            rest = sent[m.start():]
            am = ADVICE_TRIGGER.search(rest)
            if not am or am.start() < 2:
                continue
            condition = rest[: am.start()].strip("，, ")
            condition = re.sub(r"[你他她它]+[还再]*$", "", condition).strip("，, ")
            advice = rest[am.start():].strip("，, ")
            if not (4 <= len(advice) <= 60):
                continue
            if not VISIT_VERB.search(advice):
                continue
            if len(condition) > 30:
                continue
            audience = "通用"
            for kw, aud in AUDIENCE_KW:
                if kw in condition or kw in sent:
                    audience = aud
                    break
            if "天气" in sent or "下雨" in sent or "雨" in condition:
                ctype = "weather"
            elif "人多" in sent or "拥挤" in sent:
                ctype = "crowd"
            elif audience != "通用":
                ctype = "audience"
            elif "时间" in condition or "小时" in condition or "一天" in condition:
                ctype = "time"
            elif "季节" in sent or "夏" in sent or "冬" in sent:
                ctype = "season"
            else:
                ctype = "other"
            advices.append({
                "advice_id": f"AD-{doc['record_id']}-{len(advices)+1:03d}",
                "scenic": doc["attraction"],
                "condition_type": ctype,
                "condition": condition,
                "advice": advice,
                "audience": audience,
                "source": doc["record_id"],
                "extraction": "fallback_by_C",
            })
    return advices


def convert_b_mappings():
    ms = json.loads((RUN / "outputs/exp5/condition_advice_mappings.json").read_text(encoding="utf-8"))
    enum = {"weather": "weather", "visitor_type": "audience", "crowd_level": "crowd",
            "time_constraint": "time", "preference": "other", "other": "other"}
    out = []
    for m in ms:
        out.append({
            "advice_id": m["mapping_id"],
            "scenic": m["attraction"],
            "condition_type": enum.get(m["condition_type"], "other"),
            "condition": m["condition"]["text"],
            "advice": m["advice"]["text"],
            "audience": "通用",
            "source": m["source_record_ids"][0] if m["source_record_ids"] else None,
            "_raw_condition_type": m["condition_type"],
        })
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    docs = load_rows()
    terms = load_poi_terms()
    routes, unparsed = extract_chains(docs, terms)
    advices = extract_advices_fallback(docs)
    b_converted = convert_b_mappings()

    (OUT / "routes.json").write_text(json.dumps(routes, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "advices.json").write_text(json.dumps(advices, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "b_raw_mappings_converted.json").write_text(json.dumps(b_converted, ensure_ascii=False, indent=2), encoding="utf-8")

    exp3_steps = json.loads((RUN / "outputs/exp3/route_steps.json").read_text(encoding="utf-8"))
    steps_by_route = {}
    for s in exp3_steps:
        steps_by_route.setdefault(s["route_id"], []).append(s)
    unparsed_out = [{
        "doc_id": d,
        "scenic": next(r["attraction"] for r in docs if r["record_id"] == d),
        "b_parsed_mention_steps": len(steps_by_route.get(d, [])),
        "note": "无链式路线行；B 的提及级解析噪声大，需 B 在实验3重写路线段切分后再用",
    } for d in unparsed]
    (OUT / "unparsed_official_docs.json").write_text(json.dumps(unparsed_out, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "routes": {
            "total": len(routes),
            "by_type": dict(Counter(r["route_type"] for r in routes)),
            "by_scenic": dict(Counter(r["scenic"] for r in routes)),
            "steps_total": sum(len(r["steps"]) for r in routes),
            "steps_with_known_poi": sum(1 for r in routes for s in r["steps"] if is_poi(s["poi_name"], terms)),
            "routes_with_duration": sum(1 for r in routes if r["route_duration_min"]),
            "routes_with_transport": sum(1 for r in routes if any(s["transport_to_next"] for s in r["steps"])),
            "time_slot_all_null": all(s["time_slot"] is None for r in routes for s in r["steps"]),
        },
        "advices": {
            "fallback_extracted": len(advices),
            "by_type": dict(Counter(a["condition_type"] for a in advices)),
            "by_audience": dict(Counter(a["audience"] for a in advices)),
        },
        "b_raw_outputs": {
            "exp3_route_records": len(json.loads((RUN / "outputs/exp3/route_records.json").read_text(encoding="utf-8"))),
            "exp3_step_mentions": len(exp3_steps),
            "exp5_mappings_mechanical_converted": len(b_converted),
            "exp5_note": "机械转换后未过滤；人工抽查多为误报（如“两个桃尖→取意…”“一天→先生所书”），不建议直接入图",
        },
        "unparsed_official_docs": unparsed_out,
    }
    (OUT / "quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:2500])


if __name__ == "__main__":
    main()
