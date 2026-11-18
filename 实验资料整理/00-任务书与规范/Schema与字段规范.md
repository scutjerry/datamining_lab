# 景区游览知识图谱 Schema 与字段规范

版本：v1.1　编写：成员C　日期：2026-11-18（v1.0 初版 2026-11-11）
适用实验：《数据挖掘》探索性实验 · 项目6（多源知识融合与图谱可视化）、项目7（旅游规划Agent）

> 本文档是成员C（项目6/7）给成员A（项目1/2）、成员B（项目3/5）的**数据交付合同**。A、B 按第5节格式输出，C 按第3-4节建图，三方字段以本文档为准。有异议先改文档再改代码，避免各自实现后返工。

---

## 1. 总体设计原则

1. **结构映射评分点**：节点/边类型覆盖任务书要求的"先后顺序、条件关系、包含关系"和"时间维度层级（上午/中午/下午）"。
2. **归一化集中做**：上游（A、B）只输出原文和位置，**不做名称归一化**；所有别名合并在项目6融合阶段由 C 统一执行（规则见第6节），保证三份数据同一套口径。
3. **宁简勿繁**：交通方式先做 STEP 边的属性而不是独立节点；条件建议独立建节点而不是硬塞进边属性。后续有余力再升级。
4. **一切可追溯**：每个节点/边保留 `source` 或 `sources` 字段，能回答"这条知识从哪篇文本来"。

---

## 2. 节点类型定义（6 类）

### 2.1 ScenicArea 景区

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | str | 是 | 编码见第7节，如 `SA-WUHAN-HHL` |
| name | str | 是 | 官方全称，canonical name |
| city | str | 否 | 所在城市 |

### 2.2 POI 景点

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | str | 是 | 如 `POI-WUHAN-HHL` |
| name | str | 是 | 归一化后的规范名（见第6节） |
| type | str | 是 | 枚举：`自然景观 / 人文景观 / 亲子设施 / 餐饮 / 其他` |
| source | str | 是 | 首次出现来源：`official / travelogue`（多来源时用 sources 数组） |
| aliases | list[str] | 否 | 被合并的别名列表，如 `["黄鹤楼公园", "黄鹤楼景区"]` |

### 2.3 Route 路线

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | str | 是 | 如 `RT-HHL-OFF-001` |
| route_type | str | 是 | `official`（官方推荐）或 `visitor`（游客游记中的实际路线） |
| source_doc_id | str | 是 | 来源文档 id（与项目1数据表关联） |

### 2.4 Transport 交通方式（v1 暂不建节点，预留）

v1 中交通方式作为 STEP 边的 `transport` / `duration_min` 属性。若后续需要"哪两个景点间有轮渡"类查询，再升级为节点，字段：`id, name（步行/轮渡/索道/公交/缆车…）`。

### 2.5 Advice 条件建议

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | str | 是 | 如 `AD-HHL-003` |
| condition_type | str | 是 | 枚举：`weather（天气） / crowd（人流） / audience（游客类型） / season（季节） / time（时间） / other` |
| condition | str | 是 | 条件描述原文，如"如果下雨" |
| advice | str | 是 | 建议内容原文，如"优先安排室内展馆" |
| audience | str | 是 | 枚举：`老人 / 亲子 / 情侣 / 通用`（无法判断填"通用"） |
| source | str | 是 | 来源景区/文档 |

### 2.6 TimeSlot 时段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | str | 是 | `TS-AM / TS-NOON / TS-PM`（固定三个） |
| name | str | 是 | `上午 / 中午 / 下午` |

> **落地状态（本版）**：本版实验6 **不生成** TimeSlot 节点。`routes.json` 的 `time_slot` 全为 `null`，硬建会让三个节点度数为 0、成为孤立点噪声。定义保留在此，待实验3 补上 `time_slot` 后由 `02_normalize_nodes.py` 生成节点并连边。

---

## 3. 边类型定义（6 类）

| 边类型 | 方向 | 属性 | 语义 | 对应任务书要求 |
|---|---|---|---|---|
| HAS_ROUTE | ScenicArea → Route | 无 | 景区包含某条路线 | 包含关系 |
| LOCATED_IN | POI → ScenicArea | 无 | 景点坐落于某景区（**v1.1 新增**，见 3.2） | 包含关系 |
| STEP | Route → POI | `order:int（步骤序号）, time_slot:str（上午/中午/下午）, activity:str, transport:str（到下一站的方式）, duration_min:int（停留时长）` | 路线中的一步：路线按 order 依次经过 POI | **先后顺序 + 时间维度层级** |
| PART_OF | POI → POI | 无 | 子景点属于父区域（如 东湖樱园 → 东湖） | 包含关系 |
| HAS_ADVICE | ScenicArea → Advice | 无 | 景区附带的游览建议 | 条件关系 |
| RELATES_TO | Advice → POI | 无 | 建议指向的具体景点（如"下雨→室内展馆"） | 条件关系（可选，无明确指向时省略） |

**英文说明**：所有边类型名大写，Neo4j / NetworkX 通用。

### 3.1 关键取舍说明（写进报告，属"Schema 设计合理性"得分点）

- **先后顺序用 STEP 边 + order 属性，不用链式 NEXT 边**：同一 POI 被多条路线经过时，链式边会把不同路线串成一团；STEP 边挂在各自 Route 下，天然隔离，Agent 按 `route_id` 有序查询即可。
- **交通方式作为 STEP 边属性**：避免为低频信息引入节点和边的类型爆炸；查询"某景点的交通方式"只需取该 STEP 边属性。
- **Advice 独立成节点而非边属性**：条件建议是一等知识（项目5的完整产出），独立节点便于按 audience/condition_type 查询和统计，Agent 也容易按"带老人"过滤。

### 3.2 v1.1 新增 LOCATED_IN 的理由

多源融合的必然结果：POI 有两个来源——路线（项目3 的 `routes.json`）和实体识别（项目2 的 `entities.json`，按提及频次 ≥5 收录）。实体来源的景点里有 77 个从未出现在任何路线的 step 中（如"文渊阁""钦安殿""廓如亭"），它们在图里没有任何边就成了孤立节点，既不可查询也不可视。

`LOCATED_IN` 让每个 POI 都有确定的景区归属，使图变成"景区 → 路线 → 景点"与"景点 → 景区"的双向可达结构，Agent 的 `query_pois_by_scenic` 也能统一走图查询而不是读节点属性。**代价**：每个 POI 会多一条边（本数据 131 条），可视化时按低透明度虚线处理，不干扰主视图。

同理，`PART_OF`（景点父子关系）与 `RELATES_TO`（建议指向景点）在 v1.1 仍然**不生成**：上游没有提供父子关系数据，建议文本里也没有能可靠对齐到具体景点的表述。宁可缺边，不可造边——这一点写进质量验证章节。

---

## 4. 图谱结构示意

```
(ScenicArea:黄鹤楼景区)
 ├─[:HAS_ROUTE]→ (Route:官方一日游 RT-HHL-OFF-001)
 │                 ├─[:STEP {order:1, time_slot:"上午"}]→ (POI:黄鹤楼)
 │                 ├─[:STEP {order:2, time_slot:"中午"}]→ (POI:户部巷)
 │                 └─[:STEP {order:3, time_slot:"下午"}]→ (POI:武汉长江大桥)
 ├─[:HAS_ROUTE]→ (Route:游客路线 RT-HHL-VIS-001) …
 ├─[:HAS_ADVICE]→ (Advice:下雨→室内展馆)
 ├─POI 之间的父子关系： (POI:东湖樱园)-[:PART_OF]→(POI:东湖)
 └─景点的景区归属： (POI:黄鹤楼)-[:LOCATED_IN]→(ScenicArea:黄鹤楼景区)   ← v1.1
```

---

## 5. 上游交付合同（发给 A、B）

### 5.1 项目2（成员A）→ 实体文件 `entities.json`

```json
{
  "doc_id": "D001",
  "scenic": "黄鹤楼景区",
  "source": "official",
  "entities": [
    {
      "text": "黄鹤楼",
      "type": "POI",
      "start": 12,
      "end": 15,
      "sentence_id": 3
    },
    {"text": "步行", "type": "TRANSPORT", "start": 16, "end": 18, "sentence_id": 3},
    {"text": "上午九点", "type": "TIME", "start": 19, "end": 23, "sentence_id": 3}
  ]
}
```

约束：`type` 只能是 `POI / TRANSPORT / TIME`；`start/end` 为字符偏移；**保留原文，不做归一化**（如游记写"黄鹤楼公园"就保留原文）。

### 5.2 项目3（成员B）→ 路线结构文件 `routes.json`

```json
{
  "route_id": "RT-HHL-OFF-001",
  "scenic": "黄鹤楼景区",
  "route_type": "official",
  "source_doc_id": "D001",
  "steps": [
    {
      "step": 1,
      "time_slot": "上午",
      "poi_name": "黄鹤楼",
      "activity": "登楼参观",
      "transport_to_next": "步行",
      "duration_min": 90
    }
  ]
}
```

约束：`time_slot` 只能是 `上午 / 中午 / 下午`；`poi_name` 用**原文写法**；`duration_min` 无法确定时填 `null`，不要估算后不留痕。

### 5.3 项目5（成员B）→ 条件建议映射表 `advices.json`

```json
{
  "advice_id": "AD-HHL-003",
  "scenic": "黄鹤楼景区",
  "condition_type": "weather",
  "condition": "如果下雨",
  "advice": "优先安排室内展馆，登楼改到雨停后",
  "audience": "通用",
  "source": "D005"
}
```

### 5.4 项目1（成员A）→ 清洗后的数据表

结构化表中必须含字段：`doc_id, scenic, doc_type（official/travelogue）, source, content（清洗后正文）, url（如有）`。`doc_id` 是所有下游数据的关联键。

---

## 6. 名称归一化规则（合并策略）

| 情况 | 规则 | 例子 |
|---|---|---|
| 别名/简称 | 以官方全称做 canonical name，其余写入 `aliases` 数组 | "黄鹤楼公园" → "黄鹤楼" |
| 子景点/父区域 | **分开建节点**，用 `PART_OF` 连；不合并 | "东湖樱园" PART_OF "东湖" |
| 同名不同景区 | **不合并**，id 带景区前缀区分 | 两个景区的"游客中心" |
| 泛指表达 | 丢弃，不建节点 | "这里""景区里" |
| 近重复建议 | 条件+建议文本相似度 > 0.9 判重，保留来源多的一条并合并 `source` | 同句重复抽取结果 |

实现建议：维护 `alias_table.csv`（`canonical, alias, type`），融合脚本先查表、查不到再用模糊匹配（difflib 相似度 ≥ 0.85 时人工确认），**模糊匹配结果一律进人工确认清单**，避免过度对齐（任务书评分点明确扣"明显过度对齐"）。

---

## 7. ID 编码规则

```
ScenicArea:  SA-<城市拼音>-<景区缩写>        例：SA-WUHAN-HHL
POI:         POI-<城市拼音>-<景点缩写>       例：POI-WUHAN-HHL
Route:       RT-<景区缩写>-<OFF|VIS>-<序号>  例：RT-HHL-OFF-001
Advice:      AD-<景区缩写>-<序号>            例：AD-HHL-003
TimeSlot:    TS-AM / TS-NOON / TS-PM
```

景区缩写取官方名拼音首字母（黄鹤楼 → HHL）。重名时加数字后缀。

---

## 8. 文件命名与目录约定（按仓库结构使用）

```
project6_graph/
├── schema/
│   ├── Schema与字段规范.md        ← 本文档
│   └── alias_table.csv
├── data_contract/                  ← A、B 的交付原样存放（只读）
│   ├── entities/                   项目2 输出（按 doc 分文件或一个大 JSON）
│   ├── routes.json                 项目3 输出
│   └── advices.json                项目5 输出
├── build/
│   ├── normalize.py                归一化 + 去重（第6节规则）
│   ├── build_graph.py              JSON → nodes.csv / edges.csv
│   ├── load_neo4j.py               CSV → Neo4j
│   └── visualize.py                NetworkX/PyVis 或 Neo4j Browser 截图脚本
├── output/
│   ├── nodes.csv
│   ├── edges.csv
│   └── figures/                    图谱可视化图
└── report/                         项目6 报告素材
```

项目7 的 Agent 单独放在 `project7_agent/`，它的图谱查询工具通过 Neo4j Cypher 或读取 `output/nodes.csv + edges.csv` 两种方式接入（推荐前者，演示更直观）。

---

## 9. Neo4j 建图约束（Cypher）

```cypher
CREATE CONSTRAINT sa_name IF NOT EXISTS FOR (n:ScenicArea) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT poi_name IF NOT EXISTS FOR (n:POI) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT route_name IF NOT EXISTS FOR (n:Route) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT advice_id IF NOT EXISTS FOR (n:Advice) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT ts_id IF NOT EXISTS FOR (n:TimeSlot) REQUIRE n.id IS UNIQUE;
CREATE INDEX poi_name_idx IF NOT EXISTS FOR (n:POI) ON (n.name);
```

关系属性（order、time_slot 等）用 `SET r.order = row.order` 方式从 `edges.csv` 导入。

---

## 10. Agent 查询工具 Schema（项目7，先行约定）

| 工具名 | 输入 | 输出 |
|---|---|---|
| `query_pois_by_scenic` | `scenic: str, poi_type: str=None` | `[{name, type}]` |
| `query_route` | `scenic: str, route_type: str` | `[{route_id, steps: [{order, time_slot, poi_name, activity, transport, duration_min}]}]` |
| `query_advices` | `scenic: str, audience: str=None, condition_type: str=None` | `[{condition, advice, audience}]` |
| `query_relation` | `poi_a: str, poi_b: str` | `{exists: bool, order: int=None, transport: str=None}` |

约定：查无结果返回空列表而不是报错；所有工具返回结构化 dict（Agent 的"观察"直接消费）。这对应项目7评分里"工具输入输出 Schema 清晰、能处理无结果情况"。

---

## 11. 版本与变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-11-11 | 初版，C 提出，待 A、B 确认 |
| v1.1 | 2026-11-18 | 新增 `LOCATED_IN`（POI → ScenicArea）边，解决实体来源景点无归属、图中孤立的问题；边类型 5 类 → 6 类；`PART_OF`/`RELATES_TO` 仍不生成并说明理由；LOCATED_IN 实际边数 131（原文误写 135）；TimeSlot 本版不生成节点（时段数据缺失，待实验3 补 `time_slot` 后启用） |
