"""02_normalize_nodes.py — 实体归一化 + 图谱节点/边生成（成员C / 实验6）

设计依据：Schema与字段规范.md v1.1（第2、3、4、6、7节）

输入：接口数据/routes.json、接口数据/advices.json、实验2-实体识别（成员A）/结果/entities.json
输出：输出/nodes.csv、edges.csv、id_mapping.csv、alias_table.csv、
      poi_quarantine.csv、graph_quality_report.json

与旧版（v1 草稿）的差异，均在报告"Schema 落地"一节可解释：
1. 节点/边 ID 按 Schema 第7节编码（旧版是 SA-GG / D001-CHAIN-01，与自定规范不符）
2. 补 TimeSlot 节点（TS-AM/TS-NOON/TS-PM），Schema 要求 6 类节点
3. Advice 的 name 改为「条件 → 建议」，旧版误取了 advice 字段（"就能逛完"）
4. 增加 POI 名清洗与隔离（quarantine）：routes.json 里有大量链式提取残渣
   （整段正文、多景点并列、混入开放时间/票价、箭头残留），不清理会污染图谱；
   实测隔离 26 条，逐条写进 poi_quarantine.csv 供人工复核
5. 输出 edges.csv（旧版只出 nodes.csv）
"""

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

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
E6 = ROOT / "实验6-知识图谱（成员C）" / "接口数据"
E2 = ROOT / "实验2-实体识别（成员A）" / "结果"
OUT = ROOT / "实验6-知识图谱（成员C）" / "输出"

# ---------------------------------------------------------------- 1. 编码表
CITY = "BEIJING"                                   # 三个景区都在北京
SCENIC_CODE = {"故宫博物院": "GG", "颐和园": "YHY", "天坛公园": "TT"}

# Schema 第6节：别名归并到 canonical name。这里四条都指向"景区级"名称，
# 归并后不再单独建 POI 节点（它们是景区本身，不是景区内的景点）。
ALIAS = {
    "紫禁城": "故宫博物院",
    "故宫": "故宫博物院",
    "清漪园": "颐和园",          # 颐和园前身，文献中作旧称出现
    "天坛": "天坛公园",
}
SCENIC_NAMES = set(SCENIC_CODE)
ALIAS_TO_SCENIC = set(ALIAS.values()) | SCENIC_NAMES

FREQ_THRESHOLD = 5          # 实体提及 ≥5 次才作为独立 POI 收录（低频噪声过滤）
MAX_NAME_LEN = 12           # 超过此长度的"景点名"基本是正文残片

# 文本中作为"对比/远眺"出现的景区外参照物：仍保留节点（可追溯），但标 scope=nearby，
# Agent 按景区查景点时可据此过滤，避免把"杭州西湖"当成颐和园的景点返回。
REFERENCE_POIS = {"杭州西湖", "香山", "玉泉山", "北海", "北海公园", "圆明园", "景山", "天安门"}

# 条件建议的人工修正（C 侧，附原文证据）。
# B 的兜底规则在第 1 条上把条件句从"约两个小时"处切断，建议只剩"就能逛完"；
# 按 D001 原文更正，并在节点的 extra 里留痕，不静默改数据。
ADVICE_PATCH = {
    "AD-D001-001": {
        "condition": "如果只是走马观花，看一看主要宫殿",
        "advice": "约两个小时就能逛完",
        "evidence_doc": "D001",
        "evidence_text": "如果只是走马观花，看一看主要宫殿，约两个小时就能逛完。",
    }
}

# ---------------------------------------------------------------- 2. 名清洗规则
# 规则从数据中归纳，每条都对应 routes.json 里的实际残渣（见 poi_quarantine.csv）
STRIP_CHARS = "←→⟶⟵<>《》〈〉 \t　"
# 注意：不剥引号。真实景点名里有“正大光明”匾这类带引号的匾额名，
# 按首尾字符逐个剥引号会把左右引号剥得不配对（只剩右引号），名字被改坏。
MULTI_SEP = "、;；/|"
SENT_PUNCT = "，。！？："
OP_INFO = ("开放时间", "票价", "元/", "营业时间", "线路：", "门票")
# 明显不是"游览景点"的设施名（OSM 节点名里的闸机、售票点等），不建节点
NOISE_WORDS = ("闸机", "停车场", "售票", "厕所", "服务点", "垃圾", "检票")


def clean_poi_name(raw):
    """返回 (清洗后名称, 状态, 原因)。状态：ok / repaired / quarantine。

    只做"能自证"的清洗，不做猜测式改写：
    - 箭头、书名号残留 → 直接剥掉（原文里是列表符号，不是名称的一部分）
    - 括号不闭合 → 补右括号（原文形如"文华殿（陶瓷馆）"，链式截断丢了右括号）
    - 整段正文 / 多景点并列 / 混入运营信息 → 隔离，交人工复核，不硬猜
    """
    s = raw.strip()
    while s and s[0] in STRIP_CHARS:
        s = s[1:]
    while s and s[-1] in STRIP_CHARS:
        s = s[:-1]
    if not s:
        return s, "quarantine", "清洗后为空"

    # 半角括号统一成全角，否则 `文华殿(陶瓷馆` 会被补成 `文华殿(陶瓷馆）` 这种混搭
    s = s.replace("(", "（").replace(")", "）")

    if any(k in s for k in OP_INFO):
        return s, "quarantine", "混入线路标题/开放时间/票价等运营信息"
    if any(k in s for k in NOISE_WORDS):
        return s, "quarantine", "设施名（闸机/售票点等），不是游览景点"
    if any(c in s for c in SENT_PUNCT):
        return s, "quarantine", "含句读标点，是正文残片而非景点名"
    if any(c in s for c in MULTI_SEP):
        if "（" in s:
            return s, "quarantine", "括号内并列多个展馆/子区域，无法确定该步骤的落点"
        return s, "quarantine", "多个景点并列，无法确定该步骤的落点"
    if len(s) < 2:
        return s, "quarantine", "过短"

    status, reason = "ok", ""
    if s.count("（") > s.count("）"):
        s = s + "）"
        status, reason = "repaired", "补齐缺失的右括号"
    elif s.count("（") != s.count("）"):
        return s, "quarantine", "括号不配对且无法安全修复"
    # 长度在补括号之后再量：否则补完刚好超限的合法名会被误杀
    if len(s) > MAX_NAME_LEN:
        return s, "quarantine", f"长度 {len(s)} 超出景点名合理范围（>{MAX_NAME_LEN}）"
    return s, status, reason


# ---------------------------------------------------------------- 3. 读数据
def check_fields(rows, fname, required):
    """上游 JSON 的必填字段校验：缺字段时给一条能定位的报错，而不是散落的 KeyError。"""
    missing = [(i, k) for i, r in enumerate(rows) for k in required if k not in r]
    if missing:
        raise SystemExit(f"{fname} 缺必填字段 {missing[:8]}（共 {len(missing)} 处），请先修上游输出")


routes = json.loads((E6 / "routes.json").read_text(encoding="utf-8"))
advices = json.loads((E6 / "advices.json").read_text(encoding="utf-8"))
entities = json.loads((E2 / "entities.json").read_text(encoding="utf-8"))
check_fields(routes, "routes.json", ("route_id", "scenic", "route_type", "steps"))
check_fields(advices, "advices.json", ("advice_id", "scenic", "condition", "advice"))
check_fields(entities, "entities.json", ("doc_id", "scenic", "entities"))
for r in routes:
    for st in r["steps"]:
        check_fields([st], f"routes.json[{r['route_id']}].steps", ("step", "poi_name"))

# ---------------------------------------------------------------- 4. 步骤名清洗
quarantine = []                 # (scenic, route_id, step, raw, reason)
clean_steps = {}                # route_id -> [(order, name, raw_step_dict)]
repaired = []

for r in routes:
    kept = []
    for st in r["steps"]:
        raw = st["poi_name"]
        name, status, reason = clean_poi_name(raw)
        if status == "quarantine":
            quarantine.append({
                "scenic": r["scenic"], "route_id": r["route_id"],
                "step": st["step"], "raw_name": raw, "reason": reason,
            })
            continue
        if status == "repaired":
            repaired.append({"scenic": r["scenic"], "route_id": r["route_id"],
                             "step": st["step"], "raw_name": raw, "clean_name": name})
        if name in ALIAS_TO_SCENIC:
            # 步骤名就是景区本身（如"颐和园"），不是景区内景点；若建 POI 会与 ScenicArea 重复，
            # 也会让后面建 STEP 边时查不到 poi_id
            quarantine.append({"scenic": r["scenic"], "route_id": r["route_id"],
                               "step": st["step"], "raw_name": raw,
                               "reason": "该步骤名是景区本身，不作为景区内景点建节点"})
            continue
        kept.append((st["step"], name, st))
    clean_steps[r["route_id"]] = kept

# ---------------------------------------------------------------- 5. POI 集合
route_pairs = {(r["scenic"], n) for r in routes for _, n, _ in clean_steps[r["route_id"]]}

ent_count = Counter()
for d in entities:
    for e in d["entities"]:
        if e["type"] != "POI":
            continue
        name = ALIAS.get(e["text"].strip(), e["text"].strip())
        if name in ALIAS_TO_SCENIC:      # 景区本身/旧称，不建 POI
            continue
        clean_name, status, _ = clean_poi_name(name)
        if status == "quarantine":
            continue
        # 名字统一用清洗后的结果计数：repair（补右括号）得到的是同一景点的规范写法，
        # 若这里沿用原始串，会和路线侧"文华殿（陶瓷馆）"分裂成两个节点
        ent_count[(d["scenic"], clean_name)] += 1

freq_pairs = {p for p, c in ent_count.items() if c >= FREQ_THRESHOLD}
poi_pairs = route_pairs | freq_pairs

# 展馆注记并入基名：若"基名（某馆/某展）"的基名本身已是独立景点，两者是同一处地方
# （如 文华殿 与 文华殿（陶瓷馆）），按 Schema 第6节"别名并合并"处理，否则一个景点两个节点。
# 只在这一条件下合并：基名不存在时（如 保和殿东庑（宫阙述往展））注记本身是有效区分信息，保留原样。
route_scenic = {r["route_id"]: r["scenic"] for r in routes}
POI_ALIAS = {}
for sc, nm in sorted(poi_pairs):
    if "（" in nm and nm.endswith("）"):
        base = nm.split("（")[0]
        if (sc, base) in poi_pairs:
            POI_ALIAS[(sc, nm)] = base
if POI_ALIAS:
    poi_pairs = {(sc, POI_ALIAS.get((sc, nm), nm)) for sc, nm in poi_pairs}
    route_pairs = {(sc, POI_ALIAS.get((sc, nm), nm)) for sc, nm in route_pairs}
    merged_count = Counter()
    for (sc, nm), c in ent_count.items():
        merged_count[(sc, POI_ALIAS.get((sc, nm), nm))] += c
    ent_count = merged_count
    for rid, kept in clean_steps.items():
        sc = route_scenic[rid]
        clean_steps[rid] = [(o, POI_ALIAS.get((sc, nm), nm), st) for o, nm, st in kept]

# ---------------------------------------------------------------- 6. 节点
nodes = []
id_map = []            # dict(label, old_id, new_id)：旧 ID → Schema ID 的可追溯对照
poi_id = {}

for sc, code in SCENIC_CODE.items():
    nodes.append({"id": f"SA-{CITY}-{code}", "label": "ScenicArea", "name": sc,
                  "scenic": sc, "extra": json.dumps({"city": "北京"}, ensure_ascii=False)})

# TimeSlot：Schema 要求固定三个。当前 routes.json 的 time_slot 全为 null，
# 所以这三个节点暂无 STEP 边相连——保留节点以符合 Schema，缺口写进质量报告。
for ts_id, ts_name in [("TS-AM", "上午"), ("TS-NOON", "中午"), ("TS-PM", "下午")]:
    nodes.append({"id": ts_id, "label": "TimeSlot", "name": ts_name, "scenic": "",
                  "extra": json.dumps({"note": "暂无路线标注时段，待实验3补 time_slot"},
                                      ensure_ascii=False)})

# POI：按景区内名称排序编号，保证可复现
for sc, code in SCENIC_CODE.items():
    for i, n in enumerate(sorted(nm for s2, nm in poi_pairs if s2 == sc), 1):
        pid = f"POI-{CITY}-{code}-{i:03d}"
        poi_id[(sc, n)] = pid
        nodes.append({
            "id": pid, "label": "POI", "name": n, "scenic": sc,
            "extra": json.dumps({
                "mention_count": ent_count.get((sc, n), 0),
                "in_route": (sc, n) in route_pairs,
                "scope": "nearby" if n in REFERENCE_POIS else "in_scenic",
                # 别名只收有依据的：由展馆注记合并产生的全称（见 POI_ALIAS）
                "aliases": sorted(f for (s2, f), b in POI_ALIAS.items() if s2 == sc and b == n),
            }, ensure_ascii=False),
        })

# Route
route_id_map = {}
seq = defaultdict(int)
for r in routes:
    code = SCENIC_CODE[r["scenic"]]
    kind = "OFF" if r["route_type"] == "official" else "VIS"
    seq[(code, kind)] += 1
    rid = f"RT-{code}-{kind}-{seq[(code, kind)]:03d}"
    route_id_map[r["route_id"]] = rid
    id_map.append({"label": "Route", "old_id": r["route_id"], "new_id": rid})
    extra = {
        "route_type": r["route_type"],
        "source_doc_id": r["source_doc_id"],
        "step_count": len(clean_steps[r["route_id"]]),
        "duration_min": r["route_duration_min"],
    }
    if r["route_id"] == "D205-CHAIN-01":
        # 该游记里把三条官方线路（东宫门/北宫门/新建宫门）写成一条"》"列表，
        # 链式提取当成了一条路线，实际是 3 条。标记出来，不在本步骤硬拆。
        extra["quality_flag"] = "segmentation_suspect"
    nodes.append({"id": rid, "label": "Route",
                  "name": r.get("route_title") or r["route_id"],
                  "scenic": r["scenic"],
                  "extra": json.dumps(extra, ensure_ascii=False)})

# Advice
advice_id_map = {}
aseq = defaultdict(int)
for a in advices:
    code = SCENIC_CODE[a["scenic"]]
    aseq[code] += 1
    aid = f"AD-{code}-{aseq[code]:03d}"
    advice_id_map[a["advice_id"]] = aid
    id_map.append({"label": "Advice", "old_id": a["advice_id"], "new_id": aid})
    extra = {
        "condition": a["condition"],
        "advice": a["advice"],
        "condition_type": a["condition_type"],
        "audience": a["audience"],
        "source": a["source"],
        "extraction": a.get("extraction", ""),
    }
    name = f'{a["condition"]} → {a["advice"]}'
    patch = ADVICE_PATCH.get(a["advice_id"])
    if patch:                            # 边界切分错误已按原文修正，留痕
        name = f'{patch["condition"]} → {patch["advice"]}'
        extra.update({"condition": patch["condition"], "advice": patch["advice"],
                      "patched_by": "C", "evidence_doc": patch["evidence_doc"],
                      "evidence_text": patch["evidence_text"]})
    elif len(a["advice"].strip()) < 6:   # 建议部分被切成半句且无原文可依据
        extra["quality_flag"] = "advice_fragment"
    nodes.append({"id": aid, "label": "Advice", "name": name[:60],
                  "scenic": a["scenic"],
                  "extra": json.dumps(extra, ensure_ascii=False)})

# ---------------------------------------------------------------- 7. 边
edges = []

for r in routes:
    edges.append({"source": f"SA-{CITY}-{SCENIC_CODE[r['scenic']]}", "type": "HAS_ROUTE",
                  "target": route_id_map[r["route_id"]], "order": "", "time_slot": "",
                  "activity": "", "transport": "", "duration_min": "", "extra": ""})

for r in routes:
    for order, name, st in clean_steps[r["route_id"]]:
        edges.append({
            "source": route_id_map[r["route_id"]], "type": "STEP",
            "target": poi_id[(r["scenic"], name)],
            "order": order,
            "time_slot": st.get("time_slot") or "",
            "activity": st.get("activity") or "",
            "transport": st.get("transport_to_next") or "",
            "duration_min": "" if st.get("duration_min") is None else st["duration_min"],
            "extra": "",
        })

for a in advices:
    edges.append({"source": f"SA-{CITY}-{SCENIC_CODE[a['scenic']]}", "type": "HAS_ADVICE",
                  "target": advice_id_map[a["advice_id"]], "order": "", "time_slot": "",
                  "activity": "", "transport": "", "duration_min": "", "extra": ""})

# POI 的景区归属（Schema v1.1 新增 LOCATED_IN）：实体来源的景点里有一批从未
# 出现在任何路线 step 中，若只靠 STEP 边它们就是孤立节点，既查不到也画不出。
for (sc, n), pid in poi_id.items():
    edges.append({"source": pid, "type": "LOCATED_IN",
                  "target": f"SA-{CITY}-{SCENIC_CODE[sc]}", "order": "", "time_slot": "",
                  "activity": "", "transport": "", "duration_min": "",
                  # nearby：语料里作为"远眺/对比"对象出现的景区外参照物（如颐和园游记里的杭州西湖）。
                  # 挂到景区下只是为了可查；这不代表空间上位于景区内，用边属性标出来
                  "extra": "nearby" if n in REFERENCE_POIS else ""})

# PART_OF（POI→POI 父子）与 RELATES_TO（Advice→POI）当前无可靠来源：
# B 未输出父子关系，Advice 的条件文本里也没有能自动对齐到 POI 的表述。
# 按"宁缺勿造"处理，缺口写进质量报告，等 B 补或有依据的别名表后再加。

# ---------------------------------------------------------------- 8. 写出
OUT.mkdir(parents=True, exist_ok=True)


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


write_csv(OUT / "nodes.csv", nodes, ["id", "label", "name", "scenic", "extra"])
write_csv(OUT / "edges.csv", edges,
          ["source", "type", "target", "order", "time_slot", "activity",
           "transport", "duration_min", "extra"])
write_csv(OUT / "id_mapping.csv", id_map, ["label", "old_id", "new_id"])
alias_rows = [{"canonical": c, "alias": a, "type": "ScenicArea"} for a, c in ALIAS.items()]
alias_rows += [{"canonical": b, "alias": f, "type": "POI"} for (_, f), b in POI_ALIAS.items()]
write_csv(OUT / "alias_table.csv", alias_rows, ["canonical", "alias", "type"])
write_csv(OUT / "poi_quarantine.csv", quarantine,
          ["scenic", "route_id", "step", "raw_name", "reason"])
write_csv(OUT / "poi_repaired.csv", repaired,
          ["scenic", "route_id", "step", "raw_name", "clean_name"])

# ---------------------------------------------------------------- 9. 自查
node_ids = [n["id"] for n in nodes]
dup_ids = [k for k, v in Counter(node_ids).items() if v > 1]
dangling = [e for e in edges if e["source"] not in set(node_ids) or e["target"] not in set(node_ids)]
label_by_id = {n["id"]: n["label"] for n in nodes}
bad_enum = [
    e for e in edges
    if (e["type"] == "STEP" and e["time_slot"] not in ("", "上午", "中午", "下午"))
    or (e["type"] == "HAS_ADVICE" and label_by_id.get(e["target"]) != "Advice")
    or (e["type"] == "HAS_ROUTE" and label_by_id.get(e["target"]) != "Route")
]
step_edges = [e for e in edges if e["type"] == "STEP"]

report = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "schema_version": "Schema与字段规范 v1.1",
    "inputs": {
        "routes.json": len(routes),
        "advices.json": len(advices),
        "entities.json": len(entities),
    },
    "nodes": {"total": len(nodes), "by_label": dict(Counter(n["label"] for n in nodes))},
    "edges": {"total": len(edges), "by_type": dict(Counter(e["type"] for e in edges))},
    "poi": {
        "from_routes": len(route_pairs),
        "from_entities_freq_ge_%d" % FREQ_THRESHOLD: len(freq_pairs - route_pairs),
        "total": sum(1 for n in nodes if n["label"] == "POI"),
        "quarantined_step_names": len(quarantine),
        "repaired_step_names": len(repaired),
        "merged_exhibition_alias": len(POI_ALIAS),
    },
    "step_attribute_coverage": {
        "steps_total": len(step_edges),
        "time_slot_non_null": sum(1 for e in step_edges if e["time_slot"]),
        "activity_non_empty": sum(1 for e in step_edges if e["activity"]),
        "transport_non_null": sum(1 for e in step_edges if e["transport"]),
        "duration_non_null": sum(1 for e in step_edges if e["duration_min"] != ""),
        "route_duration_non_null": sum(1 for r in routes if r["route_duration_min"]),
    },
    "checks": {
        "duplicate_node_ids": dup_ids,
        "dangling_edges": len(dangling),
        "enum_violations": len(bad_enum),
        "all_step_poi_resolved": len(step_edges) + len(quarantine) ==
                                 sum(len(r["steps"]) for r in routes),
    },
    "known_gaps": [
        "STEP.time_slot 全为空：routes.json 的链式路线原文无时段标注，时间层级（上午/中午/下午）"
        "在项目6内无法落地，属实验3 待补项；TimeSlot 节点已建但暂无边。",
        "STEP.activity 全为空、transport 仅 3 条、duration 全空：实验3 只做了链式景点序列，未解析活动与时长。",
        "PART_OF（POI 父子）与 RELATES_TO（建议→景点）无可靠来源，本版不生成，避免造边；"
        "POI 的景区归属改用 Schema v1.1 新增的 LOCATED_IN 表达。",
        "D205-CHAIN-01 实际是游记里并列的三条官方线路，被链式提取当成一条，已标 quality_flag=segmentation_suspect。",
        f"{len(quarantine)} 个步骤名被判为解析残渣并隔离（见 poi_quarantine.csv），源头是实验3 的路线段切分缺失。",
    ],}
(OUT / "graph_quality_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------------------------------------------------------------- 10. 控制台摘要
print("根目录:", ROOT)
print("节点总数:", len(nodes), "| 按类型:", dict(Counter(n["label"] for n in nodes)))
print("边总数:", len(edges), "| 按类型:", dict(Counter(e["type"] for e in edges)))
print("每景区 POI:", dict(Counter(n["scenic"] for n in nodes if n["label"] == "POI")))
print("隔离步骤名:", len(quarantine), "| 修复括号:", len(repaired))
print("悬空边:", len(dangling), "| 重复 ID:", len(dup_ids), "| 枚举违规:", len(bad_enum))
print("输出目录:", OUT)
