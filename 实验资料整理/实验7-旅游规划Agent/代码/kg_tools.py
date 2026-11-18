# -*- coding: utf-8 -*-
"""
kg_tools.py — 把实验6 的知识图谱封装成 Agent 可调用的查询工具（不是把图谱塞进 prompt）

对应《Schema与字段规范》§10 预定义的四个工具：
    query_pois_by_scenic(scenic, keyword=None, limit=None, in_route_only=False)
    query_route(route_id=None, scenic=None, route_type=None, with_steps=True)
    query_advices(scenic=None, condition_type=None, audience=None)
    query_relation(source_id=None, rel_type=None, target_id=None)

设计要点
1. 只依赖标准库（csv/json/re/pathlib），任何 Python 3.8+ 都能跑；
2. 每次调用都返回统一信封 {"ok", "tool", "count", "data", "note"}，
无结果 / 参数不合法 / 数据缺失都走同一条返回路径，Agent 不需要 try/except；
3. 数据缺失（time_slot、duration_min 全空）不编造，在 note 里明说。
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------- 定位图谱数据
def _find_root() -> Path:
    """向上找到「实验资料整理」目录，脚本放在 代码/ 或任意层都能跑。"""
    root = Path(__file__).resolve().parent
    while root.name != "实验资料整理" and root.parent != root:
        root = root.parent
    if root.name != "实验资料整理":
        raise SystemExit("未找到“实验资料整理”目录，请保持项目结构后再运行")
    return root


ROOT = _find_root()
GRAPH_DIR = ROOT / "实验6-知识图谱" / "输出"
NODES_CSV = GRAPH_DIR / "nodes.csv"
EDGES_CSV = GRAPH_DIR / "edges.csv"


# ---------------------------------------------------------------- 图数据容器
class KnowledgeGraph:
    """把 nodes.csv / edges.csv 读进内存，提供按标签/类型索引的查询。"""

    def __init__(self, nodes_csv: Path = NODES_CSV, edges_csv: Path = EDGES_CSV):
        for p in (nodes_csv, edges_csv):
            if not p.exists():
                raise SystemExit(
                    f"找不到图谱文件：{p}\n请先跑实验6 的 02_normalize_nodes.py 与 03_build_graph.py"
                )
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._load(nodes_csv, edges_csv)
        self.out_edges: dict[str, list[dict]] = defaultdict(list)
        self.in_edges: dict[str, list[dict]] = defaultdict(list)
        for e in self.edges:
            self.out_edges[e["source"]].append(e)
            self.in_edges[e["target"]].append(e)

    # -- 读入 ----------------------------------------------------------
    def _load(self, nodes_csv: Path, edges_csv: Path) -> None:
        with open(nodes_csv, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    extra = json.loads(row.get("extra") or "{}")
                except json.JSONDecodeError:
                    extra = {}
                self.nodes[row["id"]] = {
                    "id": row["id"],
                    "label": row["label"],
                    "name": row["name"],
                    "scenic": row.get("scenic") or "",
                    "extra": extra,
                }
        with open(edges_csv, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                self.edges.append(
                    {
                        "source": row["source"],
                        "type": row["type"],
                        "target": row["target"],
                        "order": row.get("order") or "",
                        "time_slot": row.get("time_slot") or "",
                        "activity": row.get("activity") or "",
                        "transport": row.get("transport") or "",
                        "duration_min": row.get("duration_min") or "",
                        "extra": row.get("extra") or "",
                    }
                )

    # -- 便捷查询 ------------------------------------------------------
    def of_label(self, label: str) -> list[dict]:
        return [n for n in self.nodes.values() if n["label"] == label]

    def scenics(self) -> list[str]:
        return sorted({n["name"] for n in self.of_label("ScenicArea")})

    def resolve_scenic(self, text: str) -> str | None:
        """把用户口语（故宫/天坛/颐和园…）对齐到图谱里的景区名。"""
        if not text:
            return None
        text = text.strip()
        alias = {
            "故宫": "故宫博物院",
            "紫禁城": "故宫博物院",
            "故宫博物院": "故宫博物院",
            "天坛": "天坛公园",
            "天坛公园": "天坛公园",
            "颐和园": "颐和园",
            "清漪园": "颐和园",
        }
        if text in alias:
            return alias[text]
        for name in self.scenics():
            if name in text or text in name:
                return name
        return None

    def route_steps(self, route_id: str) -> list[dict]:
        steps = [e for e in self.out_edges[route_id] if e["type"] == "STEP"]
        for s in steps:
            poi = self.nodes.get(s["target"], {})
            s["poi_name"] = poi.get("name", s["target"])
            s["poi_extra"] = poi.get("extra", {})
        steps.sort(key=lambda e: int(e["order"]) if e["order"].isdigit() else 9999)
        return steps


_KG: KnowledgeGraph | None = None


def get_kg() -> KnowledgeGraph:
    """惰性单例：同一进程里反复调用工具不重复读盘。"""
    global _KG
    if _KG is None:
        _KG = KnowledgeGraph()
    return _KG


# ---------------------------------------------------------------- 统一信封
def _envelope(tool: str, data: list, note: str = "") -> dict:
    return {"ok": True, "tool": tool, "count": len(data), "data": data, "note": note}


def _error(tool: str, note: str) -> dict:
    return {"ok": False, "tool": tool, "count": 0, "data": [], "note": note}


# ---------------------------------------------------------------- 工具 1
def query_pois_by_scenic(
    scenic: str,
    keyword: str | None = None,
    limit: int | None = None,
    in_route_only: bool = False,
) -> dict:
    """按景区查景点，可按关键词过滤，按提及次数降序返回。"""
    tool = "query_pois_by_scenic"
    try:
        kg = get_kg()
        name = kg.resolve_scenic(scenic)
        if not name:
            return _error(
                tool,
                f"没有叫“{scenic}”的景区；可查询的景区：{'、'.join(kg.scenics())}",
            )
        pois = [n for n in kg.of_label("POI") if n["scenic"] == name]
        if in_route_only:
            pois = [p for p in pois if p["extra"].get("in_route")]
        if keyword:
            kw = keyword.strip()
            pois = [p for p in pois if kw in p["name"]]
        pois.sort(key=lambda p: (-int(p["extra"].get("mention_count") or 0), p["id"]))
        if limit:
            pois = pois[: int(limit)]
        data = [
            {
                "poi_id": p["id"],
                "name": p["name"],
                "mention_count": p["extra"].get("mention_count", 0),
                "in_route": p["extra"].get("in_route", False),
                "scope": p["extra"].get("scope", "in_scenic"),
                "aliases": p["extra"].get("aliases", []),
            }
            for p in pois
        ]
        note = ""
        if not data:
            note = f"{name} 下没有匹配‘{keyword or ''}’的景点"
        elif keyword:
            note = f"关键词过滤：{keyword}"
        return _envelope(tool, data, note)
    except Exception as exc:  # 工具层兜底，Agent 不需要处理异常
        return _error(tool, f"查询失败：{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- 工具 2
def query_route(
    route_id: str | None = None,
    scenic: str | None = None,
    route_type: str | None = None,
    with_steps: bool = True,
    max_steps: int | None = None,
) -> dict:
    """查路线；给 route_id 返回单条详情，给 scenic 返回该景区的路线列表。"""
    tool = "query_route"
    try:
        kg = get_kg()
        routes = kg.of_label("Route")
        if route_id:
            routes = [r for r in routes if r["id"] == route_id]
            if not routes:
                return _error(tool, f"没有 id 为 {route_id} 的路线")
        if scenic:
            name = kg.resolve_scenic(scenic)
            if not name:
                return _error(
                    tool,
                    f"没有叫“{scenic}”的景区；可查询的景区：{'、'.join(kg.scenics())}",
                )
            routes = [r for r in routes if r["scenic"] == name]
        if route_type:
            routes = [r for r in routes if r["extra"].get("route_type") == route_type]
        if not routes:
            return _error(tool, "没有符合条件（景区/类型）的路线")

        data = []
        for r in routes:
            item = {
                "route_id": r["id"],
                "name": r["name"],
                "scenic": r["scenic"],
                "route_type": r["extra"].get("route_type"),
                "source_doc_id": r["extra"].get("source_doc_id"),
                "step_count": r["extra"].get("step_count"),
                "duration_min": r["extra"].get("duration_min"),
                "quality_flag": r["extra"].get("quality_flag"),
            }
            if with_steps:
                steps = kg.route_steps(r["id"])
                if max_steps:
                    steps = steps[: int(max_steps)]
                item["steps"] = [
                    {
                        "order": s["order"],
                        "poi_id": s["target"],
                        "poi_name": s["poi_name"],
                        "time_slot": s["time_slot"],
                        "activity": s["activity"],
                        "duration_min": s["duration_min"],
                        "transport_to_next": s["transport"],
                    }
                    for s in steps
                ]
            data.append(item)

        note = ""
        if with_steps and any(not s["time_slot"] for it in data for s in it["steps"]):
            note = "上游 time_slot/duration_min 缺失（实验3 未落时间维度），步骤只有顺序可依据"
        return _envelope(tool, data, note)
    except Exception as exc:
        return _error(tool, f"查询失败：{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- 工具 3
def query_advices(
    scenic: str | None = None,
    condition_type: str | None = None,
    audience: str | None = None,
    keyword: str | None = None,
) -> dict:
    """查条件性游览建议（实验5 的产物，已并入图谱）。"""
    tool = "query_advices"
    try:
        kg = get_kg()
        advices = kg.of_label("Advice")
        if scenic:
            name = kg.resolve_scenic(scenic)
            if not name:
                return _error(tool, f"没有叫“{scenic}”的景区")
            advices = [a for a in advices if a["scenic"] == name]
        if condition_type:
            advices = [a for a in advices if a["extra"].get("condition_type") == condition_type]
        if audience:
            advices = [a for a in advices if a["extra"].get("audience") == audience]
        if keyword:
            advices = [
                a
                for a in advices
                if keyword in a["name"] or keyword in str(a["extra"].get("condition", ""))
            ]
        data = [
            {
                "advice_id": a["id"],
                "scenic": a["scenic"],
                "condition": a["extra"].get("condition", ""),
                "advice": a["extra"].get("advice", ""),
                "condition_type": a["extra"].get("condition_type", ""),
                "audience": a["extra"].get("audience", ""),
                "source_doc": a["extra"].get("source", ""),
                "patched_by": a["extra"].get("patched_by"),
            }
            for a in advices
        ]
        note = ""
        if not data:
            note = "该景区/条件下没有抽到建议；实验5 一共只产出 3 条（故宫 时间类），不要编造"
        elif all(a["audience"] == "通用" for a in data):
            note = "全部建议 audience=通用，图谱没有老人/亲子等受众标签"
        return _envelope(tool, data, note)
    except Exception as exc:
        return _error(tool, f"查询失败：{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- 工具 4
def query_relation(
    source_id: str | None = None,
    rel_type: str | None = None,
    target_id: str | None = None,
    limit: int = 50,
) -> dict:
    """通用关系查询：任意两跳都能查，用于“这条路线经过哪些景点”这类问题。"""
    tool = "query_relation"
    try:
        kg = get_kg()
        rows = kg.edges
        if source_id:
            rows = [e for e in rows if e["source"] == source_id or e["source"] == _by_name(kg, source_id)]
        if target_id:
            rows = [e for e in rows if e["target"] == target_id or e["target"] == _by_name(kg, target_id)]
        if rel_type:
            rows = [e for e in rows if e["type"] == rel_type.upper()]
        if not rows:
            return _error(tool, "没有符合条件的关系（检查 id/名称/关系类型）")
        rows = rows[: int(limit)]
        data = [
            {
                "source": e["source"],
                "source_name": kg.nodes.get(e["source"], {}).get("name", ""),
                "type": e["type"],
                "target": e["target"],
                "target_name": kg.nodes.get(e["target"], {}).get("name", ""),
                "order": e["order"],
                "extra": e["extra"],
            }
            for e in rows
        ]
        return _envelope(tool, data, f"截断到前 {limit} 条" if len(rows) == limit else "")
    except Exception as exc:
        return _error(tool, f"查询失败：{type(exc).__name__}: {exc}")


def _by_name(kg: KnowledgeGraph, name: str) -> str:
    """把名称/id 混用的情况统一：输入是名称就返回对应 id。"""
    if name in kg.nodes:
        return name
    for n in kg.nodes.values():
        if n["name"] == name:
            return n["id"]
    return name


# ---------------------------------------------------------------- 工具注册表
TOOL_SPECS: dict[str, dict] = {
    "query_pois_by_scenic": {
        "func": query_pois_by_scenic,
        "desc": "按景区查询景点列表，可按关键词过滤；返回景点名称、提及次数、是否在某条官方/游记路线上",
        "args": {
            "scenic": "景区名，如 故宫博物院 / 天坛公园 / 颐和园（支持‘故宫’这类简称）",
            "keyword": "可选，景点名关键词，如‘门’‘殿’‘花园’",
            "limit": "可选，最多返回多少个",
            "in_route_only": "可选，true 时只要被路线收录过的景点",
        },
    },
    "query_route": {
        "func": query_route,
        "desc": "查询官方/游记路线的步骤顺序；给 route_id 看单条，给 scenic 看该景区所有路线",
        "args": {
            "route_id": "可选，路线 id，如 RT-GG-OFF-001",
            "scenic": "可选，景区名",
            "route_type": "可选，official 或 visitor",
            "with_steps": "可选，默认 true，是否返回步骤明细",
            "max_steps": "可选，只取前 N 步",
        },
    },
    "query_advices": {
        "func": query_advices,
        "desc": "查询条件性游览建议（时间不够怎么取舍、走马观花要多久等）",
        "args": {
            "scenic": "可选，景区名",
            "condition_type": "可选，如 time",
            "audience": "可选，如 通用 / 老人 / 亲子（图谱目前只有 通用）",
            "keyword": "可选，建议文本关键词",
        },
    },
    "query_relation": {
        "func": query_relation,
        "desc": "通用关系查询：查任意节点间的边（HAS_ROUTE/STEP/HAS_ADVICE/LOCATED_IN）",
        "args": {
            "source_id": "可选，起点 id 或名称",
            "rel_type": "可选，关系类型",
            "target_id": "可选，终点 id 或名称",
            "limit": "可选，默认 50",
        },
    },
}


def call_tool(name: str, args: dict | None = None) -> dict:
    """按名字调用工具，统一处理未知工具与参数错误。"""
    spec = TOOL_SPECS.get(name)
    if not spec:
        return _error(name, f"未知工具；可用工具：{'、'.join(TOOL_SPECS)}")
    args = dict(args or {})
    allowed = set(spec["args"])
    unknown = set(args) - allowed
    if unknown:
        return _error(name, f"参数 {sorted(unknown)} 不在工具签名里，允许的参数：{sorted(allowed)}")
    try:
        return spec["func"](**args)
    except TypeError as exc:
        return _error(name, f"参数类型不对：{exc}")


def describe_tools() -> str:
    """给 prompt 用的工具说明（紧凑 JSON）。"""
    return json.dumps(
        {k: {"desc": v["desc"], "args": v["args"]} for k, v in TOOL_SPECS.items()},
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    kg = get_kg()
    print(f"图谱：{len(kg.nodes)} 节点 / {len(kg.edges)} 边；景区：{'、'.join(kg.scenics())}")
    demo = call_tool("query_route", {"scenic": "故宫", "route_type": "official", "max_steps": 3})
    print(json.dumps(demo, ensure_ascii=False, indent=2)[:900])
