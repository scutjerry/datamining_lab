"""03_build_graph.py — 建图 / 结构校验 / 可视化 / Neo4j 导出（成员C / 实验6）

前置：先跑 02_normalize_nodes.py 生成 输出/nodes.csv、输出/edges.csv

输入：输出/nodes.csv、输出/edges.csv
输出：输出/graph.gml                 —— 网络结构（Gephi 可直接打开）
     输出/graph_stats.json          —— 结构指标与校验结果（报告"图谱质量验证"用）
     输出/graph.html                —— pyvis 交互可视化（vis.js 内联，断网可用）
     输出/graph_overview.png        —— 静态三视图（报告插图）
     输出/import_neo4j.cypher       —— Neo4j 导入脚本

依赖：networkx、matplotlib、pyvis（均在 Anaconda 环境中）
"""

import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import networkx as nx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 自动向上找到“实验资料整理”目录：脚本放在 代码/ 或实验6 根目录都能跑（不写死层数）
ROOT = Path(__file__).resolve().parent
while ROOT.name != "实验资料整理" and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if ROOT.name != "实验资料整理":
    raise SystemExit("未找到“实验资料整理”目录，请保持项目原有目录结构后再运行")
E6 = ROOT / "实验6-知识图谱"
OUT = E6 / "输出"
NODES_CSV, EDGES_CSV = OUT / "nodes.csv", OUT / "edges.csv"

ALLOWED_LABELS = {"ScenicArea", "POI", "Route", "Advice", "TimeSlot"}
ALLOWED_TYPES = {"HAS_ROUTE", "STEP", "PART_OF", "HAS_ADVICE", "RELATES_TO", "LOCATED_IN"}
ID_PATTERNS = {
    "ScenicArea": r"^SA-[A-Z]+-[A-Z]+$",
    "POI": r"^POI-[A-Z]+-[A-Z]+-\d{3}$",
    "Route": r"^RT-[A-Z]+-(OFF|VIS)-\d{3}$",
    "Advice": r"^AD-[A-Z]+-\d{3}$",
    "TimeSlot": r"^TS-(AM|NOON|PM)$",
}
COLOR = {"ScenicArea": "#c0392b", "Route-OFF": "#2471a3", "Route-VIS": "#e67e22",
         "POI": "#7f8c8d", "POI-HUB": "#16a085", "Advice": "#27ae60", "TimeSlot": "#bdc3c7"}
HUB_THRESHOLD = 3        # 被 ≥3 条路线经过的景点算"高频景点"，可视化里高亮

# ---------------------------------------------------------------- 1. 读入
if not NODES_CSV.exists() or not EDGES_CSV.exists():
    sys.exit("缺少 nodes.csv / edges.csv，请先运行 02_normalize_nodes.py")

nodes_rows = list(csv.DictReader(NODES_CSV.open(encoding="utf-8-sig")))
edges_rows = list(csv.DictReader(EDGES_CSV.open(encoding="utf-8-sig")))

G = nx.MultiDiGraph()
for r in nodes_rows:
    G.add_node(r["id"], label=r["label"], name=r["name"], scenic=r["scenic"],
               extra=json.loads(r["extra"]) if r["extra"] else {})
for i, r in enumerate(edges_rows):
    G.add_edge(r["source"], r["target"], key=f"{r['type']}#{r.get('order') or i}",
               type=r["type"], order=r.get("order", ""), time_slot=r.get("time_slot", ""),
               activity=r.get("activity", ""), transport=r.get("transport", ""),
               duration_min=r.get("duration_min", ""))

label_of = nx.get_node_attributes(G, "label")
scenic_of = nx.get_node_attributes(G, "scenic")

# ---------------------------------------------------------------- 2. 结构校验
issues = []          # (级别, 检查项, 说明)


def add(level, check, msg):
    issues.append({"level": level, "check": check, "detail": msg})


# 2.1 ID 与枚举
for n, d in G.nodes(data=True):
    if d["label"] not in ALLOWED_LABELS:
        add("error", "label_enum", f"{n} 的 label={d['label']} 不在 Schema 允许集合内")
    elif not re.match(ID_PATTERNS[d["label"]], n):
        add("error", "id_pattern", f"{n} 不符合 {d['label']} 的 ID 规则")
for u, v, k, d in G.edges(keys=True, data=True):
    if d["type"] not in ALLOWED_TYPES:
        add("error", "type_enum", f"{u}-[{d['type']}]->{v} 关系类型不在 Schema 内")

# 2.2 每条路线恰好归属一个景区、步序连续、步数 ≥2
route_nodes = [n for n, d in G.nodes(data=True) if d["label"] == "Route"]
route_seq = defaultdict(list)
for u, v, k, d in G.edges(keys=True, data=True):
    if d["type"] == "STEP":
        try:
            route_seq[u].append(int(d["order"]))
        except (TypeError, ValueError):
            add("error", "step_order_invalid", f"{u}->{v} 的 order={d['order']!r} 不是整数")
for rt in route_nodes:
    owners = [u for u, _, d in G.in_edges(rt, data=True) if d["type"] == "HAS_ROUTE"]
    if len(owners) != 1:
        add("error", "route_owner", f"{rt} 的 HAS_ROUTE 入边数为 {len(owners)}（应为 1）")
    elif scenic_of[owners[0]] != scenic_of[rt]:
        add("error", "route_scenic", f"{rt} 与所属景区 {owners[0]} 的 scenic 不一致")
    seq = sorted(route_seq.get(rt, []))
    if len(seq) < 2:
        # 只逛一处的短线路是合法数据，不该当结构错误，降级为警告
        add("warn", "route_steps_short", f"{rt} 的 STEP 边只有 {len(seq)} 条")
        continue
    if seq != sorted(set(seq)):
        add("error", "route_order", f"{rt} 的步序有重复或非递增: {seq[:12]}")
        continue
    if seq[0] != 1:
        add("warn", "route_order_head_gap",
            f"{rt} 的首步是 {seq[0]}（原始 step {seq[0] - 1} 及之前被判为残渣隔离，起点缺失）")
    # 首步之前的缺口已由 head_gap 表达，这里只报内部断档；两条信息互不吞掉
    gaps = [g for g in sorted(set(range(1, seq[-1] + 1)) - set(seq)) if g > seq[0]]
    if gaps:
        # 断档 = 该步被判为解析残渣隔离掉。保留原始序号而不重排，便于回溯 routes.json 的下标
        add("warn", "route_order_gap",
            f"{rt} 步序断档 {gaps}（原始 step {gaps} 被判为残渣隔离，已记入 poi_quarantine.csv）")

# 2.3 孤立点（TimeSlot 例外，已在质量报告记为缺口）
isolated = [n for n in G.nodes if G.degree(n) == 0]
for n in isolated:
    if label_of[n] == "TimeSlot":
        # 本版 02 已不生成 TimeSlot 节点，这里保留分支是为实验3 补时段后能再用
        add("warn", "ts_unlinked", f"{n} 无任何边（time_slot 数据缺失，属已知缺口）")
    else:
        add("error", "isolated_node", f"{n}({label_of[n]}) 是孤立节点")

# 2.4 交叉景区边
for u, v, k, d in G.edges(keys=True, data=True):
    if scenic_of.get(u) and scenic_of.get(v) and scenic_of[u] != scenic_of[v]:
        add("error", "cross_scenic", f"{u}->{v} 跨景区（{scenic_of[u]} / {scenic_of[v]}）")

# 2.5 建议覆盖
adv_nodes = [n for n, d in G.nodes(data=True) if d["label"] == "Advice"]
adv_linked = {v for u, v, d in G.in_edges(adv_nodes, data=True) if d["type"] == "HAS_ADVICE"}
for a in adv_nodes:
    if a not in adv_linked:
        add("error", "advice_owner", f"{a} 没有 HAS_ADVICE 边")

# 2.5b 每个景点恰好归属一个景区（Schema v1.1 的 LOCATED_IN）
for p in [n for n, d in G.nodes(data=True) if d["label"] == "POI"]:
    outs = [(v, d) for u, v, d in G.out_edges(p, data=True) if d["type"] == "LOCATED_IN"]
    if len(outs) != 1:
        add("error", "poi_located_in", f"{p} 的 LOCATED_IN 出边数为 {len(outs)}（应为 1）")
    elif scenic_of.get(outs[0][0]) != scenic_of[p]:
        add("error", "poi_located_in", f"{p} 的 LOCATED_IN 指向了别的景区 {outs[0][0]}")

# 2.6 同一路线内景点重复出现（环形/重复段）
dups = []
for rt, seq in route_seq.items():
    tgts = [v for u, v, d in G.out_edges(rt, data=True) if d["type"] == "STEP"]
    c = Counter(tgts)
    for poi, cnt in c.items():
        if cnt > 1:
            dups.append({"route": rt, "poi": poi, "times": cnt})
if dups:
    add("warn", "repeat_poi", f"{len(dups)} 处同一路线内重复经过同一景点")

# 2.7 景区内连通性（无向）
conn = {}
for sc in sorted({d["scenic"] for n, d in G.nodes(data=True) if d["scenic"]}):
    sub = G.subgraph([n for n, d in G.nodes(data=True) if d["scenic"] == sc]).to_undirected()
    conn[sc] = {"nodes": sub.number_of_nodes(), "edges": sub.number_of_edges(),
                "components": nx.number_connected_components(sub)}
    if conn[sc]["components"] > 1:
        add("warn", "disconnected", f"{sc} 子图有 {conn[sc]['components']} 个连通分量")

# 2.8 只看"路线链路"（HAS_ROUTE + STEP）的连通性。LOCATED_IN 把所有景点都挂到景区中心，
# 全图天然 1 个分量，看不出"景点有没有被路线串起来"，故单独算一项，避免用全图分量当通过证据
pois_all = [n for n, d in G.nodes(data=True) if d["label"] == "POI"]
step_g = nx.Graph()
step_g.add_edges_from((u, v) for u, v, d in G.edges(keys=False, data=True)
                      if d["type"] in ("HAS_ROUTE", "STEP"))
step_reached = {v for u, v, d in G.in_edges(keys=False, data=True) if d["type"] == "STEP"}
pois_no_route = sorted(set(pois_all) - step_reached)
if pois_no_route:
    add("warn", "poi_without_route",
        f"{len(pois_no_route)} 个景点没有任何路线经过（仅实体来源，靠 LOCATED_IN 挂到景区）")

# ---------------------------------------------------------------- 3. 结构指标
poi_in_deg = Counter()             # 步骤出现次数（同一路线可重复经过同一景点）
poi_routes = defaultdict(set)      # 该景点被多少条**不同路线**经过
for u, v, d in G.in_edges(keys=False, data=True):
    if d["type"] == "STEP" and label_of[v] == "POI":
        poi_in_deg[v] += 1
        poi_routes[v].add(u)


def hub_routes(p):
    return len(poi_routes[p])


stats = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "nodes": G.number_of_nodes(),
    "edges": G.number_of_edges(),
    "by_label": dict(Counter(label_of.values())),
    "by_type": dict(Counter(d["type"] for u, v, k, d in G.edges(keys=True, data=True))),
    "avg_degree": round(2 * G.number_of_edges() / max(G.number_of_nodes(), 1), 3),
    "scenic_subgraph": conn,
    "step_only_view": {"components": nx.number_connected_components(step_g),
                       "pois_without_route": len(pois_no_route)},
    "route_steps": {
        "routes": len(route_nodes),
        "routes_with_steps": sum(1 for r in route_nodes if route_seq.get(r)),
        "min": min((len(route_seq.get(r, [])) for r in route_nodes), default=0),
        "max": max((len(route_seq.get(r, [])) for r in route_nodes), default=0),
        "avg": round(sum(len(route_seq.get(r, [])) for r in route_nodes)
                     / max(len(route_nodes), 1), 1),
        "total": sum(len(route_seq.get(r, [])) for r in route_nodes),
    },
    "top_hubs_by_routes": [
        {"poi_id": p, "name": G.nodes[p]["name"], "scenic": scenic_of[p],
         "routes": hub_routes(p), "occurrences": poi_in_deg[p]}
        for p in sorted(pois_all, key=lambda x: (-hub_routes(x), -poi_in_deg[x]))[:10]
    ],
    "repeat_poi_in_route": dups[:20],
}
# checks 与可视化结果在脚本末尾统一写入（pyvis 的警告也要进来）

# ---------------------------------------------------------------- 4. 导出 GML
# GML 只接受标量字符串属性：把 dict 型 extra 序列化，None 统一成空串
H = nx.MultiDiGraph()
for n, d in G.nodes(data=True):
    H.add_node(n, label=d["label"], name=d["name"], scenic=d["scenic"],
               extra=json.dumps(d["extra"], ensure_ascii=False))
for u, v, k, d in G.edges(keys=True, data=True):
    H.add_edge(u, v, key=k, **{kk: ("" if vv is None else str(vv)) for kk, vv in d.items()})
nx.write_gml(H, OUT / "graph.gml")

# ---------------------------------------------------------------- 5. Neo4j 导入脚本
cypher = ["// 实验6 知识图谱导入脚本（Neo4j 5.x）",
          "// 用法：把 nodes.csv、edges.csv 复制到 <NEO4J_HOME>/import/，",
          "//       在 Neo4j Browser 执行  :source import_neo4j.cypher",
          ""]
for lab in ["ScenicArea", "POI", "Route", "Advice", "TimeSlot"]:
    cypher.append(f"CREATE CONSTRAINT {lab.lower()}_id IF NOT EXISTS "
                  f"FOR (n:{lab}) REQUIRE n.id IS UNIQUE;")
cypher.append("")
for lab in ["ScenicArea", "POI", "Route", "Advice", "TimeSlot"]:
    cypher += [
        "LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row",
        f"WITH row WHERE row.label = '{lab}'",
        f"MERGE (n:{lab} {{id: row.id}})",
        "SET n.name = row.name, n.scenic = row.scenic, n.extra = row.extra;",
        "",
    ]
for typ in ["HAS_ROUTE", "HAS_ADVICE", "PART_OF", "RELATES_TO"]:
    cypher += [
        "LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row",
        f"WITH row WHERE row.type = '{typ}'",
        "MATCH (a {id: row.source}), (b {id: row.target})",
        f"MERGE (a)-[r:{typ}]->(b);",
        "",
    ]
# LOCATED_IN（Schema v1.1）必须一起导入：77 个仅在实体识别中出现的景点与图谱的唯一连接
# 就是这条边，漏了它们导入后全是孤立点，而且不会报错
cypher += [
    "LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row",
    "WITH row WHERE row.type = 'LOCATED_IN'",
    "MATCH (a:POI {id: row.source}), (b:ScenicArea {id: row.target})",
    "MERGE (a)-[r:LOCATED_IN]->(b)",
    "SET r.scope = CASE WHEN row.extra = '' THEN 'in_scenic' ELSE row.extra END;",
    "",
]
cypher += [
    "// STEP 边带属性，直接 SET 成关系属性（Schema 第9节）",
    "LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row",
    "WITH row WHERE row.type = 'STEP'",
    "MATCH (a:Route {id: row.source}), (b:POI {id: row.target})",
    "MERGE (a)-[r:STEP {order: toInteger(row.order)}]->(b)",
    "SET r.time_slot   = row.time_slot,",
    "    r.activity    = row.activity,",
    "    r.transport   = row.transport,",
    "    r.duration_min = CASE WHEN row.duration_min = '' THEN null",
    "                          ELSE toFloat(row.duration_min) END;",
]
(OUT / "import_neo4j.cypher").write_text("\n".join(cypher), encoding="utf-8")

# ---------------------------------------------------------------- 6. 静态三视图
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

scenics = sorted({d["scenic"] for n, d in G.nodes(data=True) if d["scenic"]})
fig, axes = plt.subplots(1, len(scenics), figsize=(7.2 * len(scenics), 7.6))
if len(scenics) == 1:
    axes = [axes]

for ax, sc in zip(axes, scenics):
    sa = [n for n, d in G.nodes(data=True) if d["label"] == "ScenicArea" and d["scenic"] == sc][0]
    rts = sorted(n for n, d in G.nodes(data=True) if d["label"] == "Route" and d["scenic"] == sc)
    pois = sorted(n for n, d in G.nodes(data=True) if d["label"] == "POI" and d["scenic"] == sc)

    # 环形布局：景区在中心，路线内环，景点外环（按被引用次数排序，便于对读）
    pos = {sa: (0.0, 0.0)}
    for i, r in enumerate(rts):
        ang = 2 * math.pi * i / len(rts)
        pos[r] = (0.55 * math.cos(ang), 0.55 * math.sin(ang))
    pois_sorted = sorted(pois, key=lambda n: (-hub_routes(n), -poi_in_deg[n]))
    n_hub = sum(1 for p in pois_sorted if hub_routes(p) >= HUB_THRESHOLD)
    for i, p in enumerate(pois_sorted):
        ang = 2 * math.pi * i / max(len(pois_sorted), 1) - math.pi / 2
        pos[p] = (math.cos(ang), math.sin(ang))

    for u, v, d in G.edges(data=True):
        if d["type"] == "LOCATED_IN" and u in pos and v in pos:
            ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]],
                    color="#d7dbdf", lw=0.4, alpha=0.22, ls=(0, (2, 3)), zorder=0)
        if d["type"] == "STEP" and u in pos and v in pos:
            ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]],
                    color="#b0b8bf", lw=0.45, alpha=0.35, zorder=1)
    for r in rts:
        ax.plot([0, pos[r][0]], [0, pos[r][1]], color="#2471a3", lw=1.1, alpha=0.85, zorder=2)

    ax.scatter([pos[n][0] for n in pois], [pos[n][1] for n in pois],
               s=[24 + 15 * poi_in_deg[n] for n in pois],
               c=[COLOR["POI-HUB"] if hub_routes(n) >= HUB_THRESHOLD else "#c3ccd3"
                  for n in pois],
               edgecolors="white", linewidths=0.5, zorder=3)
    ax.scatter([pos[n][0] for n in rts], [pos[n][1] for n in rts],
               s=[40 + 8 * len(route_seq.get(n, [])) for n in rts],
               c=[COLOR["Route-VIS"] if G.nodes[n]["extra"].get("route_type") == "visitor"
                  else COLOR["Route-OFF"] for n in rts],
               edgecolors="white", linewidths=0.6, zorder=4, marker="s")
    ax.scatter([0], [0], s=4600, c=COLOR["ScenicArea"], edgecolors="white",
               linewidths=1.5, zorder=5)
    ax.text(0, 0, sc, ha="center", va="center", color="white", fontsize=9.2,
            fontweight="bold", zorder=6)

    # 只标注被多条路线共用的景点，标签沿半径向外放；相邻标签交替半径，
    # 避免同一扇区的两个标签并排叠字
    for i, p in enumerate(pois_sorted[:10]):
        ang = math.atan2(pos[p][1], pos[p][0])
        rad = 1.11 + 0.075 * (i % 2)
        lx, ly = rad * math.cos(ang), rad * math.sin(ang)
        ha = "left" if math.cos(ang) > 0.2 else ("right" if math.cos(ang) < -0.2 else "center")
        va = "bottom" if math.sin(ang) > 0.55 else ("top" if math.sin(ang) < -0.55 else "center")
        ax.annotate(G.nodes[p]["name"], xy=pos[p], xytext=(lx, ly), textcoords="data",
                    fontsize=7.4, ha=ha, va=va, zorder=7, color="#34495e",
                    bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.75))
    ax.set_title(f"{sc}｜路线 {len(rts)} 条｜景点 {len(pois)} 个｜高频景点 {n_hub} 个",
                 fontsize=11)
    ax.set_xlim(-1.42, 1.42)
    ax.set_ylim(-1.32, 1.32)
    ax.axis("off")

legend = [Line2D([], [], marker="o", ls="", color=COLOR["ScenicArea"], ms=11, label="ScenicArea"),
          Line2D([], [], marker="s", ls="", color=COLOR["Route-OFF"], ms=9, label="Route(官方)"),
          Line2D([], [], marker="s", ls="", color=COLOR["Route-VIS"], ms=9, label="Route(游记)"),
          Line2D([], [], marker="o", ls="", color=COLOR["POI"], ms=8, label="POI（面积∝引用次数，深色=被≥3条路线经过）"),
          Line2D([], [], color="#b0b8bf", lw=1.2, label="STEP 边"),
          Line2D([], [], color="#d7dbdf", lw=1.0, ls=(0, (2, 3)), label="LOCATED_IN")]
fig.legend(handles=legend, loc="lower center", ncol=5, frameon=False, fontsize=10)
fig.suptitle(f"景区游览知识图谱总览（{G.number_of_nodes()} 节点 / {G.number_of_edges()} 边）",
             fontsize=14)
fig.tight_layout(rect=[0, 0.05, 1, 0.95])
fig.savefig(OUT / "graph_overview.png", dpi=190, bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------- 7. pyvis 交互图
# 与静态图同一套环形几何，只把三个景区并排摆：景区中心 → 路线内环 → 景点外环。
# 坐标写死并关闭物理引擎，这样打开就是稳定布局，不会每次刷新变成另一张图；
# 拖拽/缩放/tooltip 仍然保留（physics 关闭不影响这些交互）。
CLUSTER_W = 1500.0        # 相邻景区中心间距（≥ 2×最外圈半径，避免两簇的点互相穿插）
ROUTE_R = 300.0           # 路线内环半径

fixed_pos = {}
for ci, sc in enumerate(scenics):
    cx = (ci - (len(scenics) - 1) / 2.0) * CLUSTER_W
    sa_nodes = [n for n, d in G.nodes(data=True) if d["label"] == "ScenicArea" and d["scenic"] == sc]
    rts_sc = sorted(n for n, d in G.nodes(data=True) if d["label"] == "Route" and d["scenic"] == sc)
    pois_sc = sorted(n for n, d in G.nodes(data=True) if d["label"] == "POI" and d["scenic"] == sc)
    adv_sc = sorted(n for n, d in G.nodes(data=True) if d["label"] == "Advice" and d["scenic"] == sc)
    # 景点环半径随该景区景点数收缩：天坛只有 20 个，不必和故宫 58 个一样大
    poi_r = min(620.0, 220.0 + 6.5 * len(pois_sc))
    advice_r = poi_r * 0.66
    for n in sa_nodes:
        fixed_pos[n] = (cx, 0.0)
    for i, r in enumerate(rts_sc):
        ang = 2 * math.pi * i / max(len(rts_sc), 1)
        fixed_pos[r] = (cx + ROUTE_R * math.cos(ang), ROUTE_R * math.sin(ang))
    for j, a in enumerate(adv_sc):
        ang = 2 * math.pi * j / max(len(adv_sc), 1) + math.pi / 3
        fixed_pos[a] = (cx + advice_r * math.cos(ang), advice_r * math.sin(ang))
    pois_sorted_sc = sorted(pois_sc, key=lambda n: (-hub_routes(n), -poi_in_deg[n]))
    for i, p in enumerate(pois_sorted_sc):
        ang = 2 * math.pi * i / max(len(pois_sorted_sc), 1) - math.pi / 2
        rad = poi_r if i % 2 == 0 else poi_r * 1.1       # 奇偶交替半径，减轻相邻标签叠字
        fixed_pos[p] = (cx + rad * math.cos(ang), rad * math.sin(ang))

# 剩下没有 scenic 归属的节点排在整幅图底部中间一行（本版 02 不再产出 TimeSlot，
# 这里通常为空；保留这段是为了实验3 补上 time_slot 后能自动接住新节点）
_loose = [n for n, d in G.nodes(data=True) if n not in fixed_pos]
for i, n in enumerate(sorted(_loose)):
    fixed_pos[n] = ((i - (len(_loose) - 1) / 2.0) * 240.0, -800.0)

try:
    from pyvis.network import Network

    net = Network(height="940px", width="100%", directed=True, bgcolor="#ffffff",
                  font_color="#222222", cdn_resources="in_line")
    for n, d in G.nodes(data=True):
        lab = d["label"]
        if lab == "Route":
            color = COLOR["Route-VIS"] if d["extra"].get("route_type") == "visitor" else COLOR["Route-OFF"]
            size = 12 + 1.6 * len(route_seq.get(n, []))
            shape = "square"
        elif lab == "POI":
            # 高频景点用深绿+名字，只被一条路线用到一次的景点退成浅灰小点当背景，
            # 否则 61 个故宫景点在环上会和主链路抢视觉
            if hub_routes(n) >= HUB_THRESHOLD:
                color, size = COLOR["POI-HUB"], 6 + 1.8 * poi_in_deg[n]
            else:
                color, size = "#ccd3d9", 4 + 1.0 * poi_in_deg[n]
            shape = "dot"
        else:
            color, size, shape = COLOR.get(lab, "#999999"), 26, "dot"
        tip = f'{lab}｜{d["name"]}'
        if d["extra"]:
            tip += "<br>" + "<br>".join(f"{k}: {v}" for k, v in list(d["extra"].items())[:5])
        # 标签策略：只给"能看懂图"的节点写字——景区、路线、高频景点、建议、时段。
        # 其余 100 多个只被一条路线用到一次的景点保持为无字圆点，靠 tooltip 查看，
        # 否则 61 个故宫景点挤在环上会糊成一片（静态图同理，只标 top10）。
        if lab == "POI" and hub_routes(n) < HUB_THRESHOLD:
            # 必须给一个空格而不是空串：vis.js 遇到空 label 会回退显示节点 id，
            # 图上就会变成一片 "POI-BEIJING-TT-013"
            label = " "
        elif lab == "Route":
            # 上游路线名多是"北京市公园管理中心-天坛公园暑期推出3条…"这种营销标题，
            # 直接写图上既长又互相压字；改成"景区+官方/游记+序号"，全名留在 tooltip
            short = {"故宫博物院": "故宫", "颐和园": "颐和园", "天坛公园": "天坛"}.get(d["scenic"], d["scenic"])
            tag = "游记" if d["extra"].get("route_type") == "visitor" else "官方"
            idx = sorted(n2 for n2, d2 in G.nodes(data=True)
                         if d2["label"] == "Route" and d2["scenic"] == d["scenic"]).index(n) + 1
            label = f"{short}{tag}{idx}"
        elif lab == "Advice":
            # 建议正文（"如果只是走马观花，看一看主要宫殿 → 约两个小时…"）太长，
            # 图上只放前 8 字，完整条件与建议在 tooltip 里
            label = d["name"][:8]
        else:
            label = d["name"][:12]
        px, py = fixed_pos.get(n, (0.0, 0.0))
        net.add_node(n, label=label, title=tip, color=color, size=size,
                     shape=shape, borderWidth=1, x=px, y=py, physics=False)
    for u, v, k, d in G.edges(keys=True, data=True):
        if d["type"] == "STEP":
            title = (f'STEP 第{d["order"]}步' +
                     (f'｜{d["activity"]}' if d["activity"] else ""))
            net.add_edge(u, v, title=title, color="#c8cdd2", width=0.6, arrows="to")
        elif d["type"] == "LOCATED_IN":
            # 归属边 131 条，若和路线边同样显眼，交互图上会盖过真正的游览链路
            net.add_edge(u, v, title=f'LOCATED_IN（{d.get("extra") or "in_scenic"}）',
                         color="#e2e6e9", width=0.5, dashes=True, arrows="")
        else:
            net.add_edge(u, v, title=d["type"], color="#2471a3" if d["type"] == "HAS_ROUTE"
                         else "#27ae60", width=1.4, arrows="to")
    net.set_options(json.dumps({
        # 坐标已按环形三簇写死，这里必须关掉物理引擎，否则一打开就被 barnesHut 拖走
        "physics": {"enabled": False},
        "interaction": {"hover": True, "tooltipDelay": 120, "navigationButtons": True,
                        "dragNodes": True, "zoomView": True},
        "nodes": {"font": {"size": 11, "face": "Microsoft YaHei"}},
        "edges": {"smooth": {"type": "continuous"}},
    }))
    # pyvis 的 write_html 内部用 open(...,'w') 走系统默认编码，中文 Windows 上是 GBK，
    # 内联的 vis.js 里有 '©' 等字符会直接抛 UnicodeEncodeError。改成自己按 UTF-8 落盘。
    html = net.generate_html(notebook=False)
    # pyvis 模板里还夹着两类外链，必须清掉，否则单文件拷走/断网时体验很差：
    #   1) 一段被注释掉的 <script src="../node_modules/vis/dist/vis.js">——仓库里没有
    #      node_modules（lib/ 也已清理），留在文件里会让人以为缺依赖而白屏；
    #      真正的 vis-network 9.1.2 已经由 cdn_resources="in_line" 内联在下面。
    #   2) jsdelivr 上的 bootstrap CSS/JS（模板自带的卡片样式），断网时阻塞加载。
    html = re.sub(r"<!--.*?\.\./node_modules.*?-->", "", html, flags=re.S)
    html = re.sub(r"<script[^>]*\bsrc=[\"'][^\"']*[\"'][^>]*>\s*</script>", "", html, flags=re.S)
    html = re.sub(r"<link[^>]*\bhref=[\"']https?://[^\"']*[\"'][^>]*/?>", "", html, flags=re.S)
    external_refs = len(re.findall(r"<script[^>]*\bsrc=", html))
    (OUT / "graph.html").write_text(html, encoding="utf-8")
    html_ok = True
    if external_refs:
        add("warn", "html_external_script", f"graph.html 仍引用 {external_refs} 个外部脚本")
except Exception as exc:            # 可视化失败不影响主产物
    html_ok = False
    add("warn", "pyvis", f"交互图生成失败：{exc}")

# ---------------------------------------------------------------- 8. 汇总落盘
stats["visualization"] = {
    "html": str(OUT / "graph.html"),
    "html_ok": html_ok,
    "html_external_script_refs": external_refs if html_ok else None,
    "png": str(OUT / "graph_overview.png"),
    "gml": str(OUT / "graph.gml"),
    "cypher": str(OUT / "import_neo4j.cypher"),
}
stats["checks"] = {
    "errors": [i for i in issues if i["level"] == "error"],
    "warnings": [i for i in issues if i["level"] == "warn"],
    "passed": not any(i["level"] == "error" for i in issues),
}
(OUT / "graph_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

# ---------------------------------------------------------------- 9. 摘要
print("节点:", G.number_of_nodes(), "| 边:", G.number_of_edges())
print("按类型:", dict(Counter(d["type"] for u, v, k, d in G.edges(keys=True, data=True))))
print("路线步数 min/avg/max:", stats["route_steps"]["min"], stats["route_steps"]["avg"],
      stats["route_steps"]["max"])
print("连通分量:", {k: v["components"] for k, v in conn.items()})
print("错误:", len(stats["checks"]["errors"]), "| 警告:", len(stats["checks"]["warnings"]))
for i in stats["checks"]["errors"][:10]:
    print("  [ERR]", i["check"], i["detail"])
for i in stats["checks"]["warnings"][:6]:
    print("  [WARN]", i["check"], i["detail"])
print("Top 共用景点:", [(h["name"], h["routes"]) for h in stats["top_hubs_by_routes"][:5]])
print("输出:", OUT, "| html:", html_ok)
