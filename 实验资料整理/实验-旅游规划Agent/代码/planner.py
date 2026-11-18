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


# ---------------------------------------------------------------- 时长解析
def parse_minutes(text: str) -> int | None:
    """从中文里解析可用时长（分钟）。解析不到返回 None，交给 Agent 追问。"""
    if not text:
        return None
    t = text.strip()

    # 半天 / 一天
    if "半天" in t:
        return 240
    if "一天" in t or "整天" in t or "全天" in t:
        return 480

    # 一个半小时 / 两个半小时 / 1.5小时 里的"半"要先吃掉，否则会先命中"半小时"变成 30
    m = re.search(r"(\d+(?:\.\d+)?|[零一两二三四五六七八九十]{1,3})\s*个?\s*半\s*(?:个)?\s*(?:小时|钟头)", t)
    if m:
        base = m.group(1)
        hours = float(base) if re.fullmatch(r"\d+(?:\.\d+)?", base) else float(_cn_to_int(base))
        if hours:
            return int(hours * 60 + 30)

    # 90分钟 / 45 分钟
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:分钟|min)", t)
    if m:
        return int(float(m.group(1)))

    # 2.5小时 / 1.5 个小时
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:个)?\s*(?:小时|钟头|h\b)", t)
    if m:
        return int(float(m.group(1)) * 60)

    # 两个小时 / 三小时 / 一小时
    m = re.search(r"([零一两二三四五六七八九十]{1,3})\s*(?:个)?\s*(?:小时|钟头)", t)
    if m:
        return _cn_to_int(m.group(1)) * 60 if _cn_to_int(m.group(1)) else None

    # 半小时
    if "半小时" in t or "半个小时" in t:
        return 30
    return None


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
    scenic = None
    for alias, canonical in SCENIC_ALIASES.items():
        if alias in text:
            scenic = canonical
            break

    audience = "通用"
    for keys, val in AUDIENCE_RULES:
        if any(k in text for k in keys):
            audience = val
            break

    pace = "常规"
    for keys, val in PACE_RULES:
        if any(k in text for k in keys):
            pace = val
            break

    interests = [val for keys, val in INTEREST_RULES if any(k in text for k in keys)]

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
    }


def missing(constraints: dict) -> list[str]:
    """哪些关键约束还没给（Agent 据此追问）。"""
    gaps = []
    if not constraints.get("scenic"):
        gaps.append("景区")
    if not constraints.get("minutes"):
        gaps.append("可用时长")
    return gaps


# ---------------------------------------------------------------- 路线规划
def _route_cost(steps: list[dict]) -> int:
    n = len(steps)
    return n * MIN_PER_POI + max(0, n - 1) * MIN_TRANSFER


def fit_route(steps: list[dict], budget: int) -> dict:
    """在时间预算内截断一条路线：优先保住前半程（入口→核心景点），末尾给出取舍说明。"""
    if not steps or budget <= 0:
        return {"steps": [], "minutes": 0, "leftover": budget, "truncated": False}
    kept, cum = [], 0
    for s in steps:
        cost = MIN_PER_POI + (MIN_TRANSFER if kept else 0)
        if cum + cost > budget:
            break
        kept.append(s)
        cum += cost
    if len(kept) < 2 and len(steps) >= 2:
        # 至少给两个点，否则"路线"没有意义；同时把预算冲突如实报出来
        kept = steps[:2]
        cum = _route_cost(kept)
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
    if not constraints.get("scenic"):
        result["reason"] = "缺少景区，无法规划"
        return result
    if not constraints.get("minutes"):
        result["reason"] = "缺少可用时长，无法判断该走几步"
        return result

    budget = int(constraints["minutes"])
    routes = kg_tools.query_route(scenic=constraints["scenic"], with_steps=True)
    if not routes["ok"] or not routes["data"]:
        result["reason"] = f"{constraints['scenic']} 在图谱里没有可用路线"
        return result

    scored = []
    for r in routes["data"]:
        steps = r.get("steps", [])
        full = _route_cost(steps)
        # 目标：整条路线估算时长尽量贴近预算（不超预算优先，其次别浪费预算）；
        # 超预算重罚，剩余时间多也算浪费；游记路线额外加 45 分让官方路线优先。
        over = max(0, full - budget)
        idle = max(0, budget - full)
        scored.append(
            {
                "route_id": r["route_id"],
                "name": r["name"],
                "route_type": r["route_type"],
                "step_count": len(steps),
                "full_minutes": full,
                "over_budget": over,
                "idle_minutes": idle,
                "score": over * 10 + idle,
                "steps": steps,
            }
        )
    # 官方路线优先（游记链路是单篇游记抽出来的，实验6 已标注可能有拼接问题），
    # 同类里再比"离预算多近"。
    scored.sort(key=lambda x: (0 if x["route_type"] == "official" else 1, x["score"], -x["step_count"]))
    result["candidates"] = [
        {k: c[k] for k in ("route_id", "name", "route_type", "step_count", "full_minutes", "over_budget")}
        for c in scored[:5]
    ]

    best = scored[0]
    fitted = fit_route(best["steps"], budget)
    result.update(
        {
            "ok": bool(fitted["steps"]),
            "route": {k: best[k] for k in ("route_id", "name", "route_type", "step_count", "full_minutes")},
            "steps": [
                {
                    "order": s["order"],
                    "poi_name": s["poi_name"],
                    "poi_id": s["poi_id"],
                    "est_min": MIN_PER_POI,
                    "transport_min": MIN_TRANSFER if i else 0,
                }
                for i, s in enumerate(fitted["steps"])
            ],
            "minutes_used": fitted["minutes"],
            "leftover": fitted["leftover"],
            "reason": (
                f"选 {best['name']}（{best['route_type']}，共 {best['step_count']} 步，"
                f"整条估算 {best['full_minutes']} 分钟），按 {budget} 分钟预算截取前 {len(fitted['steps'])} 步"
            ),
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
        f"时间来自估算（每景点 {MIN_PER_POI} 分钟、转场 {MIN_TRANSFER} 分钟），"
        "图谱里 time_slot/duration_min 上游为空，不是实测"
    )
    if constraints.get("audience") not in (None, "通用"):
        result["caveats"].append(
            f"图谱没有{constraints['audience']}受众标签（建议的 audience 全是“通用”），"
            "该人群适配只能靠常识补充，不能算图谱结论"
        )
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
