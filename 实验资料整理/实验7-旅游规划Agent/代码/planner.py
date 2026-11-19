# -*- coding: utf-8 -*-
"""
planner.py — 意图解析 + 路线规划（确定性算法，不含任何"大模型猜"）

职责边界：
    意图解析器  parse_constraints(text) -> {scenic, minutes, audience, pace, interests, start_hint}
    路线规划器  plan(kg, constraints)   -> 选路线、按时间预算截断、给出取舍理由与缺口说明
LLM 只负责"想下一步调哪个工具 / 怎么把结果讲成人话"，绝不负责算数。

为什么时间要靠估算：
    实验6 图谱里 STEP 边的 time_slot / duration_min 100% 为空（上游实验3 未落时间维度），
    所以这里用显式常量做可审计的估算，并写进 caveats，绝不假装是抓来的真实数据。
"""

from __future__ import annotations

import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import kg_tools

# 估算常量（可审计、可改）：一个景点停留 6 分钟、相邻景点间步行/排队 3 分钟
MIN_PER_POI = 6
MIN_TRANSFER = 3

SCENIC_ALIASES = {
    "故宫": "故宫博物院",
    "紫禁城": "故宫博物院",
    "故宫博物院": "故宫博物院",
    "天坛": "天坛公园",
    "天坛公园": "天坛公园",
    "颐和园": "颐和园",
    "清漪园": "颐和园",
}

CN_NUM = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

AUDIENCE_RULES = [
    (("老人", "老年", "长辈", "爷爷", "奶奶", "父母", "爸妈"), "老人"),
    (("孩子", "小孩", "儿童", "亲子", "带娃", "小朋友"), "亲子"),
    (("情侣", "约会", "两个人"), "情侣"),
    (("学生", "穷游", "预算"), "学生"),
]

PACE_RULES = [
    (("走马观花", "随便看看", "打卡", "赶时间", "快速", "紧凑"), "快速"),
    (("深度", "慢慢", "仔细", "认真看", "细看"), "深度"),
]

INTEREST_RULES = [
    (("拍照", "摄影", "出片", "机位"), "拍照"),
    (("历史", "文物", "展览", "故事", "讲解"), "历史"),
    (("建筑", "宫殿", "大殿", "屋顶", "彩画"), "建筑"),
    (("园林", "湖", "散步", "风景", "长廊"), "园林"),
    (("祈福", "烧香", "祭天", "祈年"), "祈福"),
]

# 名称启发式，不是图谱中已有的受众/兴趣标签。
INTEREST_KEYWORDS = {
    "拍照": ("门", "桥", "湖", "园", "廊"),
    "历史": ("殿", "展", "馆", "文昌院"),
    "建筑": ("殿", "阁", "宫", "堂"),
    "园林": ("园", "湖", "廊", "石舫", "苏州街"),
    "祈福": ("祈年", "圜丘", "皇穹宇"),
}
PLAN_FIELDS = ("scenic", "minutes", "audience", "pace", "interests", "must_visit", "avoid_pois")
NUM_PATTERN = r"(?:\d+(?:\.\d+)?|[零一两二三四五六七八九十]+)"


# ---------------------------------------------------------------- 时长解析
def parse_minutes(text: str) -> int | None:
    """累计同一句中的小时与分钟；范围、负值和不明确的时长交给追问。"""
    if not text:
        return None
    t = text.strip()
    clock = re.search(r"(\d{1,2})(?:点|:)(\d{1,2})?分?\s*(?:到|至|-)\s*(\d{1,2})(?:点|:)(\d{1,2})?分?", t)
    if clock:
        h1, m1, h2, m2 = (int(x or 0) for x in clock.groups())
        if h1 < 24 and h2 < 24 and m1 < 60 and m2 < 60:
            duration = (h2 * 60 + m2) - (h1 * 60 + m1)
            return duration if duration > 0 else None
        return None
    if re.search(rf"-\s*\d|{NUM_PATTERN}\s*(?:到|至|~|～|-)\s*{NUM_PATTERN}\s*(?:小时|分钟)", t):
        return None
    units = re.compile(
        rf"(?P<h>{NUM_PATTERN})\s*个?\s*(?P<half>半)?\s*(?:小时|钟头|h\b)(?P<after>半)?"
        rf"|(?P<m>{NUM_PATTERN})\s*(?:分钟|min\b)"
        r"|(?P<only_half>半个?小时)"
    )
    total = 0
    found = False
    for match in units.finditer(t):
        found = True
        if match["only_half"]:
            total += 30
        elif match["m"]:
            total += int(_number(match["m"]))
        else:
            total += int(_number(match["h"]) * 60)
            if match["half"] or match["after"]:
                total += 30
    if found:
        return total if total > 0 else None
    if "半天" in t:
        return 240
    if "一天" in t or "整天" in t or "全天" in t:
        return 480
    return None


def _number(value: str) -> float:
    return float(value) if value[0].isdigit() else float(_cn_to_int(value))


def _cn_to_int(s: str) -> int:
    if s in CN_NUM:
        return CN_NUM[s]
    if s.startswith("十") and len(s) > 1:
        return 10 + CN_NUM.get(s[1], 0)
    if "十" in s:
        a, _, b = s.partition("十")
        return CN_NUM.get(a, 1) * 10 + (CN_NUM.get(b, 0) if b else 0)
    return 0


# ---------------------------------------------------------------- 意图解析
def parse_constraints(text: str) -> dict:
    """规则解析用户请求里的硬约束；拿不准的字段留 None，由 Agent 决定是否追问。"""
    text = text or ""
    scenic_names = []
    pattern = "|".join(re.escape(x) for x in sorted(SCENIC_ALIASES, key=len, reverse=True))
    for hit in re.finditer(pattern, text):
        prefix = re.split(r"[，,；;。]", text[:hit.start()])[-1]
        if re.search(r"(?:不去|别去|不想去|不考虑|取消|换掉)\s*$", prefix):
            continue
        scenic_names.append(SCENIC_ALIASES[hit.group()])
    scenic_names = list(dict.fromkeys(scenic_names))
    scenic = scenic_names[0] if len(scenic_names) == 1 else None
    provided = [key for key, yes in (("scenic", bool(re.search(pattern, text))), ("minutes", parse_minutes(text) is not None)) if yes]

    audience = "通用"
    for keys, val in AUDIENCE_RULES:
        if any(k in text for k in keys):
            audience = val
            provided.append("audience")
            break

    pace = "常规"
    for keys, val in PACE_RULES:
        if any(k in text for k in keys):
            pace = val
            provided.append("pace")
            break

    interests = [val for keys, val in INTEREST_RULES if any(k in text for k in keys)]
    if interests:
        provided.append("interests")
    must_visit, avoid_pois = _poi_constraints(text, scenic)
    if must_visit:
        provided.append("must_visit")
    if avoid_pois:
        provided.append("avoid_pois")

    start_hint = None
    if "上午" in text or "早上" in text or "早晨" in text:
        start_hint = "上午"
    elif "下午" in text:
        start_hint = "下午"
    elif "中午" in text:
        start_hint = "中午"

    return {
        "raw": text,
        "scenic": scenic,
        "minutes": parse_minutes(text),
        "audience": audience,
        "pace": pace,
        "interests": interests,
        "start_hint": start_hint,
        "must_visit": must_visit,
        "avoid_pois": avoid_pois,
        "scenic_candidates": scenic_names,
        "provided": provided,
    }


def _poi_constraints(text: str, scenic: str | None) -> tuple[list[str], list[str]]:
    kg = kg_tools.get_kg()
    aliases = {}
    for poi in kg.of_label("POI"):
        if scenic and poi["scenic"] != scenic:
            continue
        aliases[poi["name"]] = poi["name"]
        aliases[re.split(r"[（(]", poi["name"])[0]] = poi["name"]
    pattern = "|".join(re.escape(x) for x in sorted(aliases, key=len, reverse=True))
    selected = [[], []]
    for i, marker in enumerate((r"(?:必须|一定要|务必)(?:参观|去|看)", r"(?:不去|别去|避开|不参观|不要去)")):
        for match in re.finditer(marker + r"\s*([^，,；;。]+)", text):
            tail = match[1].strip()
            # 景区的否定由景区解析负责，避免变成景点约束。
            if tail.rstrip("了") in SCENIC_ALIASES:
                continue
            names = [aliases[m.group()] for m in re.finditer(pattern, tail)] if pattern else []
            selected[i].extend(names or [tail])
    return tuple(list(dict.fromkeys(names)) for names in selected)


def normalize_constraints(data: dict) -> dict:
    """规则、LLM 和工具共用的运行时 Schema；不接受布尔值、负时长或字符串列表。"""
    if not isinstance(data, dict):
        raise ValueError("约束必须是 JSON 对象")
    c = dict(data)
    scenic = c.get("scenic")
    if scenic is not None and not isinstance(scenic, str):
        raise ValueError("scenic 必须是字符串或 null")
    c["scenic"] = SCENIC_ALIASES.get(scenic, scenic if scenic in kg_tools.get_kg().scenics() else None)
    minutes = c.get("minutes")
    if minutes is not None:
        if isinstance(minutes, bool) or not re.fullmatch(r"\d+(?:\.0+)?", str(minutes)):
            raise ValueError("minutes 必须是正整数分钟")
        minutes = int(float(minutes))
        if not 1 <= minutes <= 1440:
            raise ValueError("minutes 必须在 1～1440 分钟之间；多日行程暂不支持")
    c["minutes"] = minutes
    for field, default, choices in (
        ("audience", "通用", ("通用", "老人", "亲子", "情侣", "学生")),
        ("pace", "常规", ("快速", "常规", "深度")),
    ):
        value = c.get(field) or default
        if value not in choices:
            raise ValueError(f"{field} 只能是 {'、'.join(choices)}")
        c[field] = value
    for field in ("interests", "must_visit", "avoid_pois"):
        value = c.get(field) or []
        if not isinstance(value, list) or len(value) > 20 or any(not isinstance(x, str) or not x.strip() for x in value):
            raise ValueError(f"{field} 必须是至多 20 个非空字符串组成的数组")
        if field == "interests" and any(x not in INTEREST_KEYWORDS for x in value):
            raise ValueError("interests 只能包含拍照、历史、建筑、园林、祈福")
        c[field] = list(dict.fromkeys(x.strip() for x in value))
    return c


def missing(constraints: dict) -> list[str]:
    """哪些关键约束还没给（Agent 据此追问）。"""
    gaps = []
    if not constraints.get("scenic"):
        gaps.append("景区")
    if not constraints.get("minutes"):
        gaps.append("可用时长")
    return gaps


# ---------------------------------------------------------------- 路线规划
def _route_cost(steps: list[dict], poi_min: int = MIN_PER_POI, transfer_min: int = MIN_TRANSFER) -> int:
    n = len(steps)
    return n * poi_min + max(0, n - 1) * transfer_min


def fit_route(steps: list[dict], budget: int, poi_min: int = MIN_PER_POI, transfer_min: int = MIN_TRANSFER) -> dict:
    """在时间预算内截断一条路线：优先保住前半程（入口→核心景点），末尾给出取舍说明。"""
    if not steps or budget <= 0:
        return {"steps": [], "minutes": 0, "leftover": budget, "truncated": False}
    kept, cum = [], 0
    for s in steps:
        cost = poi_min + (transfer_min if kept else 0)
        if cum + cost > budget:
            break
        kept.append(s)
        cum += cost
    return {
        "steps": kept,
        "minutes": cum,
        "leftover": max(0, budget - cum),
        "truncated": len(kept) < len(steps),
        "dropped": max(0, len(steps) - len(kept)),
    }


def plan(kg, constraints: dict) -> dict:
    """根据约束挑一条路线并做时间预算内编排；返回结构化计划 + 可解释理由。"""
    result = {
        "ok": False,
        "scenic": constraints.get("scenic"),
        "audience": constraints.get("audience"),
        "pace": constraints.get("pace"),
        "minutes": constraints.get("minutes"),
        "candidates": [],
        "route": None,
        "steps": [],
        "minutes_used": 0,
        "leftover": 0,
        "advices": [],
        "caveats": [],
        "reason": "",
    }
    try:
        constraints = normalize_constraints(constraints)
    except ValueError as exc:
        result["reason"] = str(exc)
        return result
    if not constraints.get("scenic"):
        result["reason"] = "缺少景区，无法规划"
        return result
    if not constraints.get("minutes"):
        result["reason"] = "缺少可用时长，无法判断该走几步"
        return result

    budget = constraints["minutes"]
    poi_min = {"快速": 4, "常规": 6, "深度": 10}[constraints["pace"]]
    transfer_min = MIN_TRANSFER
    if constraints["audience"] in ("老人", "亲子"):
        poi_min = max(poi_min, 8)
        transfer_min = 4
    result.update({key: constraints[key] for key in PLAN_FIELDS})
    result["time_policy"] = {"poi_min": poi_min, "transfer_min": transfer_min, "source": "本地启发式估算，非实测"}
    if budget < poi_min:
        result["reason"] = f"预算仅 {budget} 分钟，小于单点估算停留 {poi_min} 分钟，无法给出不超时方案；请增加时间"
        return result
    routes = kg_tools.query_route(scenic=constraints["scenic"], with_steps=True)
    if not routes["ok"] or not routes["data"]:
        result["reason"] = f"{constraints['scenic']} 在图谱里没有可用路线"
        return result

    scored = []
    for r in routes["data"]:
        steps = r.get("steps", [])
        full = _route_cost(steps, poi_min, transfer_min)
        fitted = fit_route(steps, budget, poi_min, transfer_min)
        visited = {s["poi_name"] for s in fitted["steps"]}
        if not fitted["steps"] or not set(constraints["must_visit"]).issubset(visited):
            continue
        if set(constraints["avoid_pois"]) & visited:
            continue
        hits = [
            s["poi_name"] for s in fitted["steps"]
            if any(word in s["poi_name"] for interest in constraints["interests"] for word in INTEREST_KEYWORDS[interest])
        ]
        # 先满足时间/必去/避开等硬约束；同类来源内按空余时间、截断惩罚和兴趣命中评分。
        score = fitted["leftover"] + (20 if fitted["truncated"] else 0) - 20 * len(hits)
        scored.append(
            {
                "route_id": r["route_id"],
                "name": r["name"],
                "route_type": r["route_type"],
                "step_count": len(steps),
                "full_minutes": full,
                "over_budget": max(0, full - budget),
                "idle_minutes": max(0, budget - full),
                "score": score,
                "steps": steps,
                "fitted": fitted,
                "interest_hits": hits,
                "source_doc_id": r.get("source_doc_id"),
                "quality_flag": r.get("quality_flag"),
            }
        )
    # 官方路线优先（游记链路是单篇游记抽出来的，实验6 已标注可能有拼接问题），
    # 同类里再比"离预算多近"。
    if not scored:
        result["reason"] = "现有图谱路线在时间预算内无法同时满足必去/避开约束；请调整约束或增加时间，不会自行拼造路线"
        return result
    scored.sort(key=lambda x: (0 if x["route_type"] == "official" else 1, x["score"], -len(x["fitted"]["steps"])))
    result["candidates"] = [
        {k: c[k] for k in ("route_id", "name", "route_type", "step_count", "full_minutes", "over_budget", "score", "interest_hits", "source_doc_id")}
        for c in scored[:5]
    ]

    best = scored[0]
    fitted = best["fitted"]
    result.update(
        {
            "ok": bool(fitted["steps"]),
            "route": {k: best[k] for k in ("route_id", "name", "route_type", "step_count", "full_minutes", "source_doc_id", "quality_flag")},
            "steps": [
                {
                    "order": s["order"],
                    "poi_name": s["poi_name"],
                    "poi_id": s["poi_id"],
                    "est_min": poi_min,
                    "transport_min": transfer_min if i else 0,
                }
                for i, s in enumerate(fitted["steps"])
            ],
            "minutes_used": fitted["minutes"],
            "leftover": fitted["leftover"],
            "reason": (
                f"选 {best['name']}（{best['route_type']}，共 {best['step_count']} 步，"
                f"整条估算 {best['full_minutes']} 分钟），按 {budget} 分钟预算截取前 {len(fitted['steps'])} 步"
            ),
            "personalization": {"interests": constraints["interests"], "matched_pois": best["interest_hits"], "score": best["score"]},
        }
    )
    longest = max(c["full_minutes"] for c in scored)
    if fitted.get("truncated"):
        result["caveats"].append(
            f"整条路线需要约 {best['full_minutes']} 分钟，比你的 {budget} 分钟多；"
            f"末尾 {fitted.get('dropped', 0)} 个景点被砍掉"
        )
    elif best["idle_minutes"] > 30:
        result["caveats"].append(
            f"整条路线估算 {best['full_minutes']} 分钟，比你给的 {budget} 分钟少 "
            f"{best['idle_minutes']} 分钟；图谱里该景区最长路线约 {longest} 分钟，"
            "剩余时间建议自由活动或现场加逛"
        )
    else:
        result["caveats"].append("整条路线在预算内，可以完整走完")

    adv = kg_tools.query_advices(scenic=constraints["scenic"])
    result["advices"] = adv.get("data", [])

    result["caveats"].append(
        f"时间来自估算（每景点 {poi_min} 分钟、转场 {transfer_min} 分钟），"
        "图谱里 time_slot/duration_min 上游为空，不是实测"
    )
    if constraints.get("audience") not in (None, "通用"):
        result["caveats"].append(
            f"图谱没有{constraints['audience']}受众标签（建议的 audience 全是“通用”），"
            "本方案用本地慢行耗时规则适配，不能算图谱结论，也不代表无障碍认证"
        )
    if constraints["interests"]:
        result["caveats"].append("兴趣评分来自景点名称关键词启发式，不是图谱固有标签；没有命中时不保证个性化效果")
    if fitted.get("truncated"):
        result["caveats"].append("截断方案仅保留原路线前缀，未计入离园或返回入口时间；不能据此保证完整离园预算")
    return result


# ---------------------------------------------------------------- 文本渲染
def render_plan(p: dict) -> str:
    """把计划渲染成人能读的行程单（Agent 的最终回答会在此基础上组织）。"""
    if not p.get("ok"):
        return f"暂时排不出行程：{p.get('reason')}"
    lines = [
        f"【{p['scenic']} · {p['minutes']} 分钟 · {p['audience']}】{p['reason']}",
        "",
    ]
    for i, s in enumerate(p["steps"], 1):
        move = f"，路上 {s['transport_min']} 分钟" if s["transport_min"] else ""
        lines.append(f"{i}. {s['poi_name']}（停留约 {s['est_min']} 分钟{move}）")
    lines.append("")
    lines.append(f"合计约 {p['minutes_used']} 分钟，余 {p['leftover']} 分钟。")
    lines.append(f"依据：图谱路线 {p['route']['route_id']}，来源文档 {p['route'].get('source_doc_id') or '未知'}。")
    matched = p.get("personalization", {}).get("matched_pois", [])
    if matched:
        lines.append("兴趣名称匹配：" + "、".join(matched))
    if p.get("advices"):
        lines.append("")
        lines.append("可参考的建议：")
        for a in p["advices"]:
            lines.append(f"- {a['condition']} → {a['advice']}")
    if p.get("caveats"):
        lines.append("")
        lines.append("注意：")
        for c in p["caveats"]:
            lines.append(f"- {c}")
    return "\n".join(lines)


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "我下午去故宫，只有两个小时，随便看看主要宫殿"
    c = parse_constraints(text)
    print("约束：", c)
    print("缺：", missing(c))
    print(render_plan(plan(kg_tools.get_kg(), c)))
