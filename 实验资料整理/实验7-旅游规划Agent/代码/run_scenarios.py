# -*- coding: utf-8 -*-
"""
run_scenarios.py — 功能测试与证据生成

跑 5 类场景，落盘 trace + 人可读测试报告：
    1. 正常需求（景区 + 时长 + 人群全给）
    2. 信息不足（只给景区）→ 必须追问而不是瞎排
    3. 无匹配（图谱写不了的景区）→ 必须明确说查不到
    4. 冲突（20 分钟逛故宫）→ 必须指出预算与路线冲突并给最小可行方案
    5. 兴趣约束（天坛祈福+拍照）

两个后端各出一份报告，互不覆盖：
    python run_scenarios.py              -> 输出/测试报告.md（规则后端，无 key 可复现）
    python run_scenarios.py --real-llm   -> 输出/测试报告-真实LLM.md（真调模型）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import agent as agent_mod
import llm as llm_mod

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / "输出"

# name, question, expectation dict
SCENARIOS = [
    ("S1-正常需求", "我下午去故宫，只有两个小时，随便看看主要宫殿", {"plan": True}),
    ("S2-信息不足-缺时长", "我想去颐和园", {"ask": True}),
    ("S3-无匹配景区", "我想去杭州西湖玩半天", {"ask": True, "refuse": True}),
    ("S4-预算冲突", "去故宫，只有20分钟", {"plan": True, "conflict": True}),
    ("S5-兴趣约束", "我想去天坛，只有一个半小时，想祈福拍照", {"plan": True, "interests": True}),
    ("S6-老人慢行", "带老人去颐和园，两个小时，慢慢走", {"plan": True, "audience": "老人", "pace": "深度"}),
    ("S7-亲子", "带孩子去天坛，一个半小时", {"plan": True, "audience": "亲子"}),
    ("S8-情侣半天", "情侣去故宫，半天，想拍照", {"plan": True, "audience": "情侣", "minutes": 240}),
    ("S9-复合时长", "去故宫，2小时30分钟", {"plan": True, "minutes": 150}),
    ("S10-极短预算", "去故宫，只有5分钟", {"no_plan": True}),
    ("S11-必去与避开", "去故宫，两小时，必须参观武英殿，不去御花园", {"plan": True, "must_visit": ["武英殿"], "avoid_pois": ["御花园"]}),
]


class MockLLM:
    """只用于验证 LLM 分支的代码路径：按脚本返回 JSON，不发网络请求。"""

    def __init__(self):
        self.calls = []
        self._script = [
            {"scenic": "故宫博物院", "minutes": 120, "audience": "通用", "pace": "快速", "interests": ["建筑"], "must_visit": [], "avoid_pois": []},
            {"thought": "用户要去故宫两小时，先看有哪些官方路线和步骤数", "action": "query_route", "action_input": {"scenic": "故宫博物院", "with_steps": False}},
            {"thought": "再看条件建议里有没有时长相关的取舍", "action": "query_advices", "action_input": {"scenic": "故宫博物院"}},
            {"thought": "约束齐全，用规划器按 120 分钟截断", "action": "route_plan", "action_input": {"scenic": "故宫博物院", "minutes": 120, "audience": "通用", "pace": "快速"}},
            {"thought": "已拿到规划结果，可以给结论了", "action": "finish", "action_input": {"answer": "结论：走官方中轴线「故宫5A景区游览攻略」，共 13 步，估算约 114 分钟，你的 120 分钟预算够完整走完、余约 6 分钟。行程：午门 → 太和门 → 太和殿 → 中和殿 → 保和殿 → 乾清门 → 乾清宫 → 交泰殿 → 坤宁宫 → 御花园 → 神武门。注意：时长为估算（每景点 6 分钟 + 转场 3 分钟），不是实测；图谱里没有老人/亲子等受众标签。"}},
        ]

    @property
    def available(self) -> bool:
        return True

    def status(self) -> dict:
        return {"available": True, "model": "mock-llm", "base_url": "mock", "api_key_set": False, "api_key_masked": "", "calls": len(self.calls)}

    def chat(self, messages, temperature=None, max_tokens=900) -> str:
        i = len(self.calls)
        self.calls.append({"i": i, "messages": len(messages)})
        obj = self._script[min(i, len(self._script) - 1)]
        return json.dumps(obj, ensure_ascii=False)


def run_one(question: str, offline: bool = True, llm=None) -> dict:
    a = agent_mod.Agent(offline=offline, llm=llm)
    trace = a.run(question)
    path = agent_mod.save_trace(trace)
    trace["trace_path"] = path.name
    return trace


def judge(expect: dict, final: dict, tools: list[str], trace: dict | None = None) -> tuple[bool, list[str]]:
    """按场景期望判定，返回 (是否通过, 证据/不通过原因)。"""
    answer = (final.get("answer") or "").strip()
    kind = final.get("kind")
    checks: dict[str, bool] = {}
    notes: list[str] = []

    if expect.get("plan"):
        p = final.get("plan") or {}
        steps = p.get("steps") or []
        checks["给出了结构化行程"] = kind in ("plan", "llm_answer") and p.get("ok") is True and bool(steps)
        checks["调了规划器"] = "route_plan" in tools
        budget = p.get("minutes")
        used = p.get("minutes_used")
        checks["严格不超预算"] = isinstance(budget, int) and isinstance(used, int) and 0 < used <= budget
        checks["耗时计算一致"] = bool(steps) and sum(s.get("est_min", 0) + s.get("transport_min", 0) for s in steps) == used
        kg = agent_mod.kg_tools.get_kg()
        route = p.get("route") or {}
        route_node = kg.nodes.get(route.get("route_id"), {})
        official_steps = kg.route_steps(route["route_id"]) if route_node else []
        checks["图谱路线与来源可追溯"] = (
            route_node.get("label") == "Route"
            and route_node.get("scenic") == p.get("scenic")
            and bool(route.get("source_doc_id"))
            and route.get("source_doc_id") == route_node.get("extra", {}).get("source_doc_id")
        )
        checks["站点保持图谱路线前缀"] = bool(steps) and [s.get("poi_id") for s in steps] == [s["target"] for s in official_steps[:len(steps)]]
        checks["景点名称与图谱一致"] = bool(steps) and all(kg.nodes.get(s.get("poi_id"), {}).get("name") == s.get("poi_name") for s in steps)
        visited = {s.get("poi_name") for s in steps}
        checks["满足必去与避开"] = set(p.get("must_visit", [])) <= visited and not (set(p.get("avoid_pois", [])) & visited)
        checks["回答确实使用工具结果"] = bool(p.get("ok")) and answer == agent_mod.planner.render_plan(p)
        for field in ("audience", "pace", "minutes"):
            if field in expect:
                checks[f"{field}约束正确"] = p.get(field) == expect[field]
        for field in ("must_visit", "avoid_pois"):
            if field in expect:
                checks[f"{field}约束已传递"] = set(expect[field]) <= set(p.get(field, []))
        if expect.get("interests"):
            personalization = p.get("personalization") or {}
            checks["兴趣参与规划评分"] = bool(personalization.get("interests")) and bool(personalization.get("matched_pois"))
        notes.append(f"kind={kind}, 回答 {len(answer)} 字, 工具={tools or '无'}")
    if expect.get("no_plan"):
        checks["拒绝不可行约束"] = kind == "no_plan" and not (final.get("plan") or {}).get("ok") and bool(answer)
    if expect.get("ask"):
        asked = bool(re.search(r"[？?]|吗|还是|想确认|请问", answer))
        checks["追问而非瞎排"] = asked and kind in ("followup", "llm_answer")
        notes.append(f"kind={kind}, 含疑问={asked}")
    if expect.get("refuse"):
        refuse = bool(re.search(r"没有|查不到|无法|不存在|不支持|只有这?三", answer))
        checks["明确说查不到"] = refuse
        notes.append(f"含拒绝/说明={refuse}")
    if expect.get("conflict"):
        conflict = bool(re.search(r"多|超|砍|删|只剩|20|分钟", answer)) and (
            "注意" in answer or "估算" in answer or "不足" in answer
        )
        checks["点明预算冲突或取舍"] = conflict
        notes.append(f"点明冲突={conflict}")
    if expect.get("real_llm"):
        checks["真实LLM无规则回退"] = bool(trace) and trace.get("backend") == "llm"
        checks["LLM实际完成意图解析"] = bool(trace) and trace.get("intent", {}).get("source") == "llm"
        checks["有实际模型调用"] = bool(trace) and trace.get("llm_calls", 0) > 0

    ok = all(checks.values()) if checks else False
    return ok, [f"{k}={'✓' if v else '✗'}" for k, v in checks.items()] + notes


def summarize(name: str, expect: dict, trace: dict) -> dict:
    final = trace["final"]
    tools = [s["action"] for s in trace["steps"] if s["action"] != "finish"]
    ok, why = judge(expect, final, tools, trace)
    return {
        "scenario": name,
        "question": trace["question"],
        "backend": trace["backend"],
        "kind": final.get("kind"),
        "pass": ok,
        "why": why,
        "steps": len(trace["steps"]),
        "tools": tools,
        "constraints": trace["constraints"],
        "answer": final.get("answer", ""),
        "elapsed_ms": trace["elapsed_ms"],
        "trace": trace.get("trace_path"),
        "llm_calls": trace.get("llm_calls", trace["llm"].get("calls")),
        "llm_model": trace["llm"].get("model"),
        "intent_source": trace.get("intent", {}).get("source"),
        "plan": final.get("plan"),
        "protocol_errors": trace.get("protocol_errors", []),
        "answer_source": final.get("answer_source"),
    }


def md_report(rows: list[dict], mock_row: dict | None, backend_label: str) -> str:
    lines = [
        "# 实验7 功能测试报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**后端**：{backend_label}",
        "",
        "## 一、场景覆盖",
        "",
        "| 场景 | 请求 | 实际收敛 | 判定 | 轨迹步数 | 调用工具 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['scenario']} | {r['question'][:26]} | {r['kind']} | {'通过' if r['pass'] else '失败'} "
            f"| {r['steps']} | {', '.join(r['tools']) or '—'} |"
        )
    lines += ["", "## 二、判定依据", ""]
    lines += [
        "规划场景检查结构化计划、预算、耗时加和、图谱来源、路线前缀、必去/避开与最终文本一致性；",
        "真实模式还要求 LLM 意图解析成功、实际调用模型且无规则回退。上述断言不验证现实距离、开放时间或离园耗时。",
        "",
    ]
    for r in rows:
        lines.append(f"- **{r['scenario']}**（{'通过' if r['pass'] else '失败'}）：{'；'.join(r['why'])}")
    lines += ["", "## 三、逐场景回答", ""]
    for r in rows:
        lines += [
            f"### {r['scenario']}",
            "",
            f"- 请求：{r['question']}",
            f"- 解析约束：`{json.dumps(r['constraints'], ensure_ascii=False)}`",
            f"- 耗时：{r['elapsed_ms']} ms；本轮模型调用 {r['llm_calls']} 次；意图来源 {r['intent_source']}",
            f"- 轨迹：`输出/traces/{r['trace']}`；回答来源 {r['answer_source']}",
            "",
            "```",
            r["answer"],
            "```",
            "",
        ]
    if mock_row:
        lines += [
            "## 四、LLM 分支联通性（MockLLM）",
            "",
            "验证「模型回复 JSON → 解析 → 调工具 → observation 回灌 → finish」这条链路，"
            "用脚本化 MockLLM 跑同一套 `agent.py`（代码零改动）：",
            "",
            f"- 收敛：{mock_row['kind']}（{'通过' if mock_row['pass'] else '失败'}），步数 {mock_row['steps']}，"
            f"工具序列 {', '.join(mock_row['tools'])}，模型侧调用 {mock_row['llm_calls']} 次",
            f"- 轨迹：`输出/traces/{mock_row['trace']}`",
            "",
        ]
    fails = [r for r in rows if not r["pass"]]
    lines += ["## 五、失败与边界分析", ""]
    if fails:
        for r in fails:
            lines.append(f"- **{r['scenario']} 未达预期**：{'；'.join(r['why'])}")
    else:
        lines.append(f"- {len(rows)} 类预定义场景通过全部结构化断言；这不等于现实旅游可行性已通过验证。")
    lines += [
        "- 边界 1：上游时长为空；默认 6+3 分钟，快速/深度与老人/亲子使用显式本地估算参数，均不是实测。",
        "- 边界 2：建议只有 3 条且全在故宫、`audience` 全是“通用”，非故宫场景 `query_advices` 返回空并说明。",
        "- 边界 3：景区外参照物（杭州西湖/香山等）是 `scope=nearby` 的 POI，不是景区，无法规划。",
        "- 边界 4：`route_type=visitor` 的路线来自单篇游记，实验6 已标可能拼接，规划器默认官方路线优先。",
        "",
    ]
    return "\n".join(lines)


def demo_markdown(trace: dict) -> str:
    """把一条 trace 渲染成「一次请求的完整链路」文档，供报告直接引用。"""
    lines = [
        "# 示范用例：一次请求的完整链路",
        "",
        f"- 请求：`{trace['question']}`",
        f"- 后端：{trace['backend']}（模型 {trace['llm'].get('model')}）",
        f"- 意图来源：{trace.get('intent', {}).get('source')}；本轮调用：{trace.get('llm_calls')} 次",
        f"- 耗时：{trace['elapsed_ms']} ms，共 {len(trace['steps'])} 步",
        "",
        "## 1. 意图解析（planner.parse_constraints）",
        "",
        "```json",
        json.dumps(trace["constraints"], ensure_ascii=False, indent=2),
        "```",
        "",
        f"缺失关键约束：{trace['missing'] or '无'}",
        "",
        "## 2. ReAct 轨迹",
        "",
    ]
    for s in trace["steps"]:
        lines += [f"### 第 {s['i']} 步", "", f"**思考**：{s['thought']}", ""]
        if s["action"] == "finish":
            lines += ["**行动**：`finish` → 生成最终回答", ""]
        else:
            lines += [
                f"**行动**：`{s['action']}`　参数 `{json.dumps(s['action_input'], ensure_ascii=False)}`",
                "",
                f"**观察**：ok={s['observation']['ok']}，返回 {s['observation']['count']} 条；{s['observation']['note']}",
                "",
            ]
            for p in s["observation"]["preview"]:
                lines.append(f"- `{json.dumps(p, ensure_ascii=False)}`")
            lines.append("")
    lines += ["## 3. 最终回答", "", "```", trace["final"].get("answer", ""), "```", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-llm", action="store_true", help="用真实 LLM 跑（需要 LLM_API_KEY）")
    args = ap.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    llm = llm_mod.LLM()
    if args.real_llm and not llm.available:
        print("没有配置 LLM_API_KEY，无法用真实模型；退出。")
        return 2

    rows = []
    for name, q, expect in SCENARIOS:
        if args.real_llm:
            expect = dict(expect, real_llm=True)
        trace = run_one(q, offline=not args.real_llm, llm=llm if args.real_llm else None)
        rows.append(summarize(name, expect, trace))
        r = rows[-1]
        print(f"{name}: kind={r['kind']} steps={r['steps']} {'通过' if r['pass'] else '失败'} | {'；'.join(r['why'])[:90]}")

    mock_row = None
    if not args.real_llm:
        trace = run_one("我下午去故宫，只有两个小时，随便看看主要宫殿", offline=False, llm=MockLLM())
        mock_row = summarize("M1-LLM分支(Mock)", {"plan": True}, trace)
        print(f"M1-LLM分支(Mock): kind={mock_row['kind']} steps={mock_row['steps']} {'通过' if mock_row['pass'] else '失败'}")

    if args.real_llm:
        served = sorted({c.get("model") for c in llm.calls if c.get("model")})
        label = (
            f"真实 LLM（OpenAI 兼容）：配置 model={llm.model}，服务端实际返回 {', '.join(served) or '未知'}；"
            f"base={llm.base_url}；共 {len(llm.calls)} 次模型调用"
        )
        report_name = "测试报告-真实LLM.md"
        demo_name = "示范用例-真实LLM.md"
    else:
        label = "规则后端（无 API key 的确定性兜底），另附 MockLLM 验证 LLM 分支代码路径"
        report_name = "测试报告.md"
        demo_name = "示范用例-规则后端.md"

    (OUT_DIR / report_name).write_text(md_report(rows, mock_row, label), encoding="utf-8")
    (OUT_DIR / "测试结果.json" if not args.real_llm else OUT_DIR / "测试结果-真实LLM.json").write_text(
        json.dumps({"backend": label, "rows": rows, "mock": mock_row, "llm": llm.status()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        s1 = json.loads((agent_mod.TRACE_DIR / rows[0]["trace"]).read_text(encoding="utf-8"))
        (OUT_DIR / demo_name).write_text(demo_markdown(s1), encoding="utf-8")
    except Exception as exc:
        print(f"示范用例生成失败：{exc}")

    print(f"\n报告：{OUT_DIR / report_name}")
    return 0 if all(r["pass"] for r in rows) and (mock_row is None or mock_row["pass"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
