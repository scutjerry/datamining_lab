"""课程回归测试：真实图谱、可控模型回复和隔离 HTTP；不消耗模型 API。"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

import agent
import kg_tools
import llm
import planner
import run_scenarios


INTENT = {
    "scenic": "故宫博物院", "minutes": 120, "audience": "通用",
    "pace": "常规", "interests": [], "must_visit": [], "avoid_pois": [],
}
ROUTE = {"action": "route_plan", "action_input": {"scenic": "故宫", "minutes": 120}}
FINISH = {"action": "finish", "action_input": {"answer": "依据工具结果生成行程"}}


class ScriptLLM:
    def __init__(self, script):
        self.script = script
        self.calls = []

    @property
    def available(self):
        return True

    def status(self):
        return {"available": True, "model": "test-script", "base_url": "mock", "calls": len(self.calls)}

    def chat(self, messages, **kwargs):
        index = len(self.calls)
        self.calls.append(list(messages))
        reply = self.script[min(index, len(self.script) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply, ensure_ascii=False) if isinstance(reply, dict) else reply


def offline(question):
    return agent.Agent(offline=True).run(question)


class ConstraintsTests(unittest.TestCase):
    def test_compound_duration(self):
        self.assertEqual(planner.parse_minutes("2小时30分钟"), 150)
        self.assertEqual(planner.parse_minutes("一小时三十分钟"), 90)

    def test_chinese_minutes(self):
        self.assertEqual(planner.parse_minutes("三十分钟"), 30)

    def test_half_and_decimal_hours(self):
        for text, minutes in (("一个半小时", 90), ("两小时半", 150), ("半小时", 30), ("半个小时", 30), ("1.5小时", 90)):
            with self.subTest(text=text):
                self.assertEqual(planner.parse_minutes(text), minutes)

    def test_clock_interval(self):
        self.assertEqual(planner.parse_minutes("从9点到11点"), 120)
        self.assertEqual(planner.parse_minutes("9:30到11:00"), 90)
        self.assertEqual(planner.parse_minutes("9:30-11:00"), 90)

    def test_invalid_or_ambiguous_duration(self):
        for text in ("-5分钟", "2到3小时", "两到三小时", "从25点到26点", "0分钟", "时间待定"):
            with self.subTest(text=text):
                self.assertIsNone(planner.parse_minutes(text))

    def test_negated_scenic(self):
        self.assertEqual(planner.parse_constraints("不去故宫了，去颐和园两小时")["scenic"], "颐和园")

    def test_multiple_scenics_ask(self):
        trace = offline("去故宫和天坛，各玩两小时")
        self.assertEqual(trace["final"]["kind"], "followup")
        self.assertIn("一个景区", trace["final"]["answer"])

    def test_followup_context(self):
        a = agent.Agent(offline=True)
        self.assertEqual(a.run("我想去颐和园")["final"]["kind"], "followup")
        trace = a.run("两个小时")
        self.assertEqual(trace["final"]["kind"], "plan")
        self.assertEqual(trace["constraints"]["scenic"], "颐和园")
        a = agent.Agent(offline=True)
        a.run("我想去颐和园")
        cancelled = a.run("不去颐和园了，两小时")
        self.assertIsNone(cancelled["constraints"]["scenic"])
        self.assertEqual(cancelled["final"]["kind"], "followup")

    def test_chat_cli_utf8_pipe(self):
        completed = subprocess.run(
            [sys.executable, "-B", "agent.py", "--offline", "--chat"],
            input="我想去颐和园\n两个小时\nexit\n".encode("utf-8"),
            capture_output=True, timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", errors="replace"))
        output = completed.stdout.decode("utf-8")
        self.assertIn("大概能逛多久", output)
        self.assertIn("【颐和园", output)


class PlannerTests(unittest.TestCase):
    def test_too_short_budget_refused(self):
        trace = offline("去故宫，只有5分钟")
        self.assertEqual(trace["final"]["kind"], "no_plan")
        self.assertFalse(trace["final"]["plan"]["ok"])

    def test_one_point_never_forces_overrun(self):
        p = offline("去故宫，10分钟")["final"]["plan"]
        self.assertLessEqual(p["minutes_used"], 10)
        self.assertEqual(len(p["steps"]), 1)

    def test_budget_property_across_scenics_and_paces(self):
        for scenic in kg_tools.get_kg().scenics():
            for minutes in (1, 5, 10, 20, 90, 120, 240):
                for pace in ("快速", "常规", "深度"):
                    with self.subTest(scenic=scenic, minutes=minutes, pace=pace):
                        p = planner.plan(kg_tools.get_kg(), dict(INTENT, scenic=scenic, minutes=minutes, pace=pace))
                        if p["ok"]:
                            self.assertLessEqual(p["minutes_used"], minutes)
                            self.assertEqual(p["minutes_used"], sum(s["est_min"] + s["transport_min"] for s in p["steps"]))

    def test_interest_changes_route_on_controlled_input(self):
        base = offline("去颐和园，90分钟")["final"]["plan"]
        garden = offline("去颐和园，90分钟，想看园林")["final"]["plan"]
        self.assertNotEqual(base["route"]["route_id"], garden["route"]["route_id"])
        self.assertTrue(garden["personalization"]["matched_pois"])

    def test_slow_family_policy_changes_time(self):
        base = offline("去故宫，两个小时")["final"]["plan"]
        slow = offline("带老人去故宫，两个小时，慢慢走")["final"]["plan"]
        self.assertGreater(slow["steps"][0]["est_min"], base["steps"][0]["est_min"])
        self.assertLess(len(slow["steps"]), len(base["steps"]))

    def test_must_and_avoid_constraints(self):
        p = offline("去故宫，两小时，必须参观武英殿，不去御花园")["final"]["plan"]
        self.assertTrue(p["ok"])
        names = {s["poi_name"] for s in p["steps"]}
        self.assertIn("武英殿", names)
        self.assertNotIn("御花园", names)

    def test_poi_without_route_refused(self):
        trace = offline("去故宫，两小时，必须参观珍宝馆")
        self.assertEqual(trace["final"]["kind"], "no_plan")
        self.assertIn("无法同时满足", trace["final"]["answer"])

    def test_no_invented_source_or_order(self):
        trace = offline("去天坛，90分钟")
        tools = [s["action"] for s in trace["steps"]]
        self.assertTrue(run_scenarios.judge({"plan": True}, trace["final"], tools)[0])


class AgentProtocolTests(unittest.TestCase):
    def test_nonobject_tool_args(self):
        self.assertFalse(agent.call_tool("query_route", "故宫")["ok"])

    def test_bad_budget_types_return_errors(self):
        for value in ("两个小时", -1, True, 1.5, 2000):
            with self.subTest(value=value):
                self.assertFalse(agent.call_tool("route_plan", {"scenic": "故宫", "minutes": value})["ok"])

    def test_nonstring_scenic_return_error(self):
        self.assertFalse(agent.call_tool("route_plan", {"scenic": ["故宫"], "minutes": 120})["ok"])

    def test_llm_intent_semantic_field(self):
        intent = dict(INTENT, audience="亲子")
        client = ScriptLLM([intent, ROUTE, FINISH])
        trace = agent.Agent(llm=client).run("带六岁儿子去故宫，两小时")
        self.assertEqual(trace["intent"]["source"], "llm")
        self.assertEqual(trace["final"]["plan"]["audience"], "亲子")
        self.assertEqual(trace["llm_calls"], 3)

    def test_malformed_action_recovers(self):
        client = ScriptLLM([INTENT, {"action": "route_plan", "action_input": "故宫"}, ROUTE, FINISH])
        trace = agent.Agent(llm=client).run("去故宫，两小时")
        self.assertEqual(trace["final"]["kind"], "llm_answer")
        self.assertTrue(trace["protocol_errors"])

    def test_unknown_action_recovers(self):
        client = ScriptLLM([INTENT, {"action": "unknown", "action_input": {}}, ROUTE, FINISH])
        self.assertEqual(agent.Agent(llm=client).run("去故宫，两小时")["final"]["kind"], "llm_answer")

    def test_no_evidence_cannot_finish_with_fabrication(self):
        client = ScriptLLM([INTENT, {"action": "finish", "action_input": {"answer": "故宫有迪士尼城堡"}}])
        trace = agent.Agent(llm=client).run("去故宫，两小时")
        self.assertEqual(trace["final"]["kind"], "exhausted")
        self.assertNotIn("迪士尼", trace["final"]["answer"])

    def test_final_plan_ignores_unverified_model_draft(self):
        client = ScriptLLM([INTENT, ROUTE, {"action": "finish", "action_input": {"answer": "故宫有迪士尼城堡"}}])
        trace = agent.Agent(llm=client).run("去故宫，两小时")
        self.assertNotIn("迪士尼", trace["final"]["answer"])
        self.assertEqual(trace["final"]["answer_source"], "verified_tool_result")

    def test_observation_remains_valid_json(self):
        client = ScriptLLM([INTENT, {"action": "query_route", "action_input": {"scenic": "故宫"}}, ROUTE, FINISH])
        agent.Agent(llm=client).run("去故宫，两小时")
        observations = [m["content"][12:] for call in client.calls for m in call if m["content"].startswith("observation=")]
        self.assertTrue(observations)
        for value in observations:
            self.assertIsInstance(json.loads(value), dict)

    def test_api_failure_explicitly_falls_back(self):
        trace = agent.Agent(llm=ScriptLLM([llm.LLMUnavailable("模拟服务中断")])).run("去故宫，两小时")
        self.assertEqual(trace["backend"], "rule(fallback)")
        self.assertEqual(trace["final"]["kind"], "plan")

    def test_weak_long_answer_no_longer_passes(self):
        fake = {"kind": "llm_answer", "answer": "没有依据的假行程。" * 30}
        self.assertFalse(run_scenarios.judge({"plan": True}, fake, ["route_plan"])[0])

    def test_real_evaluation_rejects_fallback(self):
        trace = offline("去故宫，两小时")
        self.assertFalse(run_scenarios.judge({"plan": True, "real_llm": True}, trace["final"], [s["action"] for s in trace["steps"]], trace)[0])


class LLMClientTests(unittest.TestCase):
    def test_json_with_braces_in_string(self):
        obj = {"thought": "字符串里有 } 和 { 以及引号 \"", "action": "finish", "action_input": {}}
        self.assertEqual(llm.extract_json("回复：" + json.dumps(obj, ensure_ascii=False)), obj)

    def test_status_has_no_key_fragments(self):
        client = llm.LLM(api_key="evaluation-key-not-real")
        self.assertEqual(client.status()["api_key_masked"], "[REDACTED]")
        self.assertNotIn(client.api_key, json.dumps(client.status()))

    def test_non_json_http_response_falls_back(self):
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("HTML")
        with patch("requests.post", return_value=response):
            trace = agent.Agent(llm=llm.LLM(api_key="evaluation-key-not-real")).run("去故宫，两小时")
        self.assertEqual(trace["backend"], "rule(fallback)")

    def test_error_echo_does_not_expose_secret(self):
        key = "evaluation-key-not-real"
        response = Mock(status_code=401, text="invalid key: " + key)
        with patch("requests.post", return_value=response):
            with self.assertRaises(llm.LLMUnavailable) as raised:
                llm.LLM(api_key=key).chat([])
        self.assertNotIn(key, str(raised.exception))

    def test_truncated_response_is_detected(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": '{"action":'}, "finish_reason": "length"}], "usage": {}}
        with patch("requests.post", return_value=response):
            with self.assertRaises(llm.LLMUnavailable):
                llm.LLM(api_key="evaluation-key-not-real").chat([])


if __name__ == "__main__":
    unittest.main(verbosity=2)
