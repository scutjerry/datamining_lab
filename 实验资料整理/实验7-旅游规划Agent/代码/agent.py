# -*- coding: utf-8 -*-
"""
agent.py — 旅游规划 Agent：ReAct（思考 → 行动 → 观察）闭环 + 可观察轨迹

两个后端，同一条循环、同一份 trace 结构：
    llm  后端：真调大模型（OpenAI 兼容），由模型逐步给出 thought / action / action_input
    rule 后端：没有 API key 时的确定性兜底，用规则决定同样的"下一步调哪个工具"

四个模块对应四个 action：
    parse（内部，不产生 trace 步）→ 意图解析器  planner.parse_constraints
    query_route / query_advices / query_pois_by_scenic / query_relation → 图谱查询工具 kg_tools
    route_plan → 路线规划器 planner.plan
    finish     → LLM 集成 / 回答生成

CLI：
    python agent.py "我下午去故宫，只有两个小时，随便看看主要宫殿"
    python agent.py --offline "..."      # 强制规则后端
    python agent.py --json "..."         # 只输出 trace JSON
    python agent.py --trace out.json "..."  # 额外把 trace 落盘
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import kg_tools
import llm as llm_mod
import planner

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / "输出"
TRACE_DIR = OUT_DIR / "traces"

MAX_STEPS = 6


# ---------------------------------------------------------------- 工具注册
def _tool_route_plan(scenic=None, minutes=None, audience=None, pace=None, **kwargs) -> dict:
    """把路线规划器包成工具，让 ReAct 循环能像调图谱一样调规划。"""
    constraints = {
        "scenic": kg_tools.get_kg().resolve_scenic(scenic) if scenic else None,
        "minutes": minutes,
        "audience": audience or "通用",
        "pace": pace or "常规",
        "interests": kwargs.get("interests") or [],
        "start_hint": None,
    }
    if not constraints["scenic"]:
        return {"ok": False, "tool": "route_plan", "count": 0, "data": [], "note": "缺少景区，无法规划"}
    if not constraints["minutes"]:
        return {"ok": False, "tool": "route_plan", "count": 0, "data": [], "note": "缺少可用时长，无法规划"}
    p = planner.plan(kg_tools.get_kg(), constraints)
    return {
        "ok": bool(p.get("ok")),
        "tool": "route_plan",
        "count": len(p.get("steps") or []),
        "data": [p],
        "note": p.get("reason", ""),
    }


TOOLS = dict(kg_tools.TOOL_SPECS)
TOOLS["route_plan"] = {
    "func": _tool_route_plan,
    "desc": "按景区+可用时长+人群生成游览路线（选路线、估算时间、按预算截断、给出取舍理由）",
    "args": {
        "scenic": "景区名",
        "minutes": "可用时长（分钟）",
        "audience": "人群：通用/老人/亲子/情侣/学生",
        "pace": "节奏：快速/常规/深度",
    },
}


def call_tool(name: str, args: dict | None = None) -> dict:
    spec = TOOLS.get(name)
    if not spec:
        return {"ok": False, "tool": name, "count": 0, "data": [], "note": f"未知工具；可用：{', '.join(TOOLS)}"}
    args = dict(args or {})
    unknown = set(args) - set(spec["args"])
    if unknown:
        return {"ok": False, "tool": name, "count": 0, "data": [], "note": f"未知参数 {sorted(unknown)}"}
    try:
        return spec["func"](**args)
    except TypeError as exc:
        return {"ok": False, "tool": name, "count": 0, "data": [], "note": f"参数错误：{exc}"}


# ---------------------------------------------------------------- prompt
SYSTEM_PROMPT = """你是「景区游览规划 Agent」。你只能依据知识图谱工具返回的事实组织回答，绝不编造景点、时长、开放时间。

工作方式（严格逐步，每步只输出一个 JSON 对象，不要输出别的文字）：
1. 先想还缺什么信息；缺景区或可用时长时，直接用 {"thought":"...","action":"finish","action_input":{"followup":"...要问用户的话..."}} 反问用户。
2. 信息够时，按需调用工具收集事实，可用工具见【工具】。
3. 收集够了再输出 {"thought":"...","action":"finish","action_input":{"answer":"最终回答"}}。

【工具】
__TOOLS__

【规则】
- 一次只调一个工具；工具返回的 data 会以 observation 回给你。
- 推荐顺序：query_route 看候选路线 → query_advices 查条件建议 → route_plan 排最终行程；同一信息不要重复调。
- 工具返回 ok=false 时不要重试同样的参数，换思路或如实告诉用户查不到。
- 图谱只有 故宫博物院 / 颐和园 / 天坛公园 三个景区。用户提到别的地点（如杭州西湖、香山）时，必须先明确说“图谱里没有这个景区（它只是景区外的参照物），排不了路线”，再问是否换成这三个之一。
- 时间估算来自 route_plan 的 est_min（每景点 6 分钟 + 转场 3 分钟），必须说明是估算。
- 图谱里没有受众标签（audience 全是“通用”），涉及老人/亲子时要说清这是常识补充。
- 回答用中文，先给结论（走哪条路线、几步、多久），再给行程清单和注意事项。
"""


# ---------------------------------------------------------------- Agent
class Agent:
    def __init__(self, offline: bool = False, llm: llm_mod.LLM | None = None, max_steps: int = MAX_STEPS):
        self.llm = llm or llm_mod.LLM()
        self.forced_offline = offline
        self.max_steps = max_steps
        self.kg = kg_tools.get_kg()

    # -- 后端选择 ------------------------------------------------------
    def backend(self) -> str:
        if self.forced_offline:
            return "rule"
        return "llm" if self.llm.available else "rule"

    # -- 主入口 --------------------------------------------------------
    def run(self, question: str) -> dict:
        t0 = time.time()
        backend = self.backend()
        constraints = planner.parse_constraints(question)
        trace = {
            "question": question,
            "backend": backend,
            "llm": self.llm.status(),
            "constraints": constraints,
            "missing": planner.missing(constraints),
            "steps": [],
            "final": {},
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        if backend == "llm":
            final = self._run_llm(question, constraints, trace)
        else:
            final = self._run_rule(question, constraints, trace)
        trace["final"] = final
        trace["elapsed_ms"] = int((time.time() - t0) * 1000)
        return trace

    # -- 一个 trace 步 -------------------------------------------------
    def _step(self, trace: dict, thought: str, action: str, action_input: dict, observation: dict) -> None:
        trace["steps"].append(
            {
                "i": len(trace["steps"]) + 1,
                "thought": thought,
                "action": action,
                "action_input": action_input,
                "observation": {
                    "ok": observation.get("ok"),
                    "tool": observation.get("tool"),
                    "count": observation.get("count"),
                    "note": observation.get("note", ""),
                    "preview": _preview(observation.get("data")),
                },
            }
        )

    # -- 规则后端 ------------------------------------------------------
    def _run_rule(self, question: str, c: dict, trace: dict) -> dict:
        gaps = planner.missing(c)
        if "景区" in gaps or "可用时长" in gaps:
            ask = []
            hint = ""
            if "景区" in gaps:
                ask.append("想去哪个景区（故宫 / 颐和园 / 天坛）")
                # 用户点名的地点如果只是图谱里的“景区外参照物”，要明说不能规划，而不是装懂
                nearby = [
                    n["name"]
                    for n in self.kg.of_label("POI")
                    if n["extra"].get("scope") == "nearby" and n["name"] in question
                ]
                if nearby:
                    hint = (
                        f"另外，{'、'.join(nearby)} 在图谱里只是景区外的参照物（scope=nearby），"
                        "没有对应景区和路线，没法据此排行程；目前图谱只覆盖故宫博物院、颐和园、天坛公园三个景区。"
                    )
            if "可用时长" in gaps:
                ask.append("大概能逛多久（比如 2 小时、半天）")
            trace["steps"].append(
                {
                    "i": 1,
                    "thought": f"用户请求缺关键约束：{'、'.join(gaps)}，先追问而不是瞎猜",
                    "action": "finish",
                    "action_input": {"followup": "、".join(ask)},
                    "observation": {"ok": True, "tool": "-", "count": 0, "note": "信息不足，走回退追问分支", "preview": []},
                }
            )
            answer = f"为了排准一点，还想确认一下：{'；'.join(ask)}？"
            if hint:
                answer += "\n" + hint
            return {
                "kind": "followup",
                "answer": answer,
                "followup": ask,
            }

        scen = c["scenic"]
        # 1) 路线
        obs = call_tool("query_route", {"scenic": scen, "with_steps": bool(True)})
        self._step(
            trace,
            f"先看 {scen} 有哪些现成路线，以及每条路线的步骤数（用来估时长）",
            "query_route",
            {"scenic": scen, "with_steps": True},
            obs,
        )
        # 2) 建议
        obs2 = call_tool("query_advices", {"scenic": scen})
        self._step(
            trace,
            "再查该景区的条件性建议，看有没有和当前约束（时长/人群）对得上的取舍提醒",
            "query_advices",
            {"scenic": scen},
            obs2,
        )
        # 3) 兴趣点（可选）
        interest = (c.get("interests") or [None])[0]
        keyword_map = {"拍照": "门", "历史": "殿", "建筑": "殿", "园林": "园", "祈福": "坛"}
        kw = keyword_map.get(interest) if interest else None
        if kw:
            obs3 = call_tool("query_pois_by_scenic", {"scenic": scen, "keyword": kw, "in_route_only": True, "limit": 8})
            self._step(
                trace,
                f"用户提到“{interest}”，在已收录景点里按“{kw}”过滤一批候选",
                "query_pois_by_scenic",
                {"scenic": scen, "keyword": kw, "in_route_only": True, "limit": 8},
                obs3,
            )
        # 4) 规划
        obs4 = call_tool(
            "route_plan",
            {"scenic": scen, "minutes": c["minutes"], "audience": c["audience"], "pace": c["pace"]},
        )
        self._step(
            trace,
            f"约束齐了（{c['minutes']} 分钟、{c['audience']}、{c['pace']}），交给规划器算路线和时间预算",
            "route_plan",
            {"scenic": scen, "minutes": c["minutes"], "audience": c["audience"], "pace": c["pace"]},
            obs4,
        )
        p = (obs4.get("data") or [{}])[0]
        answer = planner.render_plan(p) if p else "没有排出行程"
        return {"kind": "plan", "answer": answer, "plan": p}

    # -- LLM 后端 ------------------------------------------------------
    def _run_llm(self, question: str, c: dict, trace: dict) -> dict:
        tools_desc = json.dumps(
            {k: {"desc": v["desc"], "args": v["args"]} for k, v in TOOLS.items()}, ensure_ascii=False, indent=2
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.replace("__TOOLS__", tools_desc)},
            {
                "role": "user",
                "content": (
                    f"{question}\n\n【已解析的约束】{json.dumps(c, ensure_ascii=False)}\n"
                    "请开始：先判断信息是否足够，再决定调工具还是反问。"
                ),
            },
        ]
        last_err = ""
        for i in range(1, self.max_steps + 1):
            try:
                reply = self.llm.chat(messages)
            except llm_mod.LLMUnavailable as exc:
                trace["llm_error"] = str(exc)
                trace["backend_fallback"] = "rule"
                trace["steps"].append(
                    {
                        "i": i,
                        "thought": f"LLM 不可用（{exc}），回退到规则后端",
                        "action": "fallback",
                        "action_input": {},
                        "observation": {"ok": False, "tool": "-", "count": 0, "note": str(exc), "preview": []},
                    }
                )
                trace["backend"] = "rule(fallback)"
                return self._run_rule(question, c, trace)

            obj = llm_mod.extract_json(reply) or {}
            thought = str(obj.get("thought", "")).strip()
            action = str(obj.get("action", "")).strip()
            action_input = obj.get("action_input") or {}
            if not action:
                last_err = reply[:200]
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": '你的上一条不是合法 JSON。只输出一个 JSON 对象，形如 {"thought":"...","action":"工具名","action_input":{...}}',
                    }
                )
                continue

            if action not in TOOLS and action != "finish":
                last_err = f"未知 action：{action}"
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": f"action 只能是 finish 或这些工具之一：{'、'.join(TOOLS)}。请只输出一个 JSON 对象重来一次。",
                    }
                )
                continue

            if action == "finish":
                trace["steps"].append(
                    {
                        "i": i,
                        "thought": thought,
                        "action": "finish",
                        "action_input": action_input,
                        "observation": {"ok": True, "tool": "-", "count": 0, "note": "结束", "preview": []},
                    }
                )
                if action_input.get("followup"):
                    return {"kind": "followup", "answer": action_input["followup"], "followup": [action_input["followup"]]}
                return {"kind": "llm_answer", "answer": action_input.get("answer", "")}

            observation = call_tool(action, action_input)
            self._step(trace, thought, action, action_input, observation)
            messages.append({"role": "assistant", "content": reply})
            messages.append(
                {
                    "role": "user",
                    "content": "observation=" + json.dumps(_compact(observation), ensure_ascii=False)[:4000],
                }
            )
            if action == "route_plan" and observation.get("ok"):
                p = (observation.get("data") or [{}])[0]
                trace["plan"] = p

        # 步数用尽
        return {
            "kind": "exhausted",
            "answer": "工具调用步数用尽，没能收敛出方案；请把需求说得更具体些（景区 + 时长）。",
            "llm_last_error": last_err,
        }


# ---------------------------------------------------------------- 辅助
def _preview(data, n: int = 3):
    if not isinstance(data, list):
        return []
    out = []
    for item in data[:n]:
        if isinstance(item, dict):
            keep = {
                k: v
                for k, v in item.items()
                if k in ("poi_name", "name", "route_id", "advice_id", "order", "step_count", "minutes_used", "source_name", "target_name", "type")
            }
            out.append(keep or {"keys": list(item)[:6]})
        else:
            out.append(item)
    return out


def _compact(observation: dict) -> dict:
    """observation 送进 prompt 前压缩：只留前 12 条数据，避免撑爆上下文。"""
    data = observation.get("data") or []
    return {
        "ok": observation.get("ok"),
        "tool": observation.get("tool"),
        "count": observation.get("count"),
        "note": observation.get("note", ""),
        "data": data[:12],
        "truncated": len(data) > 12,
    }


def render_trace(trace: dict) -> str:
    lines = [
        f"问题：{trace['question']}",
        f"后端：{trace['backend']}（LLM 可用={trace['llm']['available']}，模型={trace['llm']['model']}）",
        f"解析约束：{json.dumps(trace['constraints'], ensure_ascii=False)}",
        f"缺少：{trace['missing'] or '无'}",
        "",
    ]
    for s in trace["steps"]:
        lines.append(f"[{s['i']}] 思考：{s['thought']}")
        if s["action"] != "finish":
            lines.append(f"    行动：{s['action']}({json.dumps(s['action_input'], ensure_ascii=False)})")
            obs = s["observation"]
            lines.append(f"    观察：ok={obs['ok']} count={obs['count']} note={obs['note']}")
            for p in obs["preview"]:
                lines.append(f"          · {json.dumps(p, ensure_ascii=False)}")
        else:
            lines.append("    行动：finish（生成回答）")
        lines.append("")
    lines.append("=" * 60)
    lines.append(trace["final"].get("answer", ""))
    lines.append(f"\n耗时：{trace['elapsed_ms']} ms")
    return "\n".join(lines)


def save_trace(trace: dict, name: str | None = None) -> Path:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    if name:  # 显式命名（如 --trace real-s1.json）按用户意图覆盖
        path = TRACE_DIR / name
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    # 毫秒时间戳 + 自增序号：同一秒内跑多个场景也不会互相覆盖
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3]
    path = TRACE_DIR / f"trace-{stamp}.json"
    n = 1
    while path.exists():
        path = TRACE_DIR / f"trace-{stamp}-{n}.json"
        n += 1
        if n > 99:
            break
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="景区游览规划 Agent（ReAct）")
    ap.add_argument("question", nargs="?", default="", help="自然语言请求")
    ap.add_argument("--offline", action="store_true", help="强制规则后端（不调 LLM）")
    ap.add_argument("--json", action="store_true", help="输出 trace JSON")
    ap.add_argument("--trace", default="", help="把 trace 存到指定文件名（默认 输出/traces/trace-时间戳.json）")
    args = ap.parse_args(argv)

    question = args.question or "我想去天坛，只有一个半小时，想祈福拍照"
    agent = Agent(offline=args.offline)
    trace = agent.run(question)
    path = save_trace(trace, args.trace or None)

    if args.json:
        print(json.dumps(trace, ensure_ascii=False, indent=2))
    else:
        print(render_trace(trace))
        print(f"\n轨迹已保存：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
