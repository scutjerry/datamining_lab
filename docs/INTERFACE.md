# A 与 B C 的数据接口

本说明落实成员 C 于 2026 年 11 月 11 日提供的《给AB的输出格式说明》v1.0，不新增或重命名核心交接字段。

## 清洗数据

路径：`data/processed/documents.csv`。三个景区合并在同一张表中。CSV 为 UTF-8 BOM，Python 可用 `encoding="utf-8-sig"` 读取，Excel 可直接打开；换行正文按标准 CSV 引号转义。

| 字段 | 类型 | 约定 |
| --- | --- | --- |
| doc_id | 字符串 | 全局唯一稳定键；不因重新排序或重跑改变，不复用被隔离文档的 ID |
| scenic | 字符串 | 故宫博物院／颐和园／天坛公园；这是来源所属景区，不代表每个提及地点都属于景区内部 |
| doc_type | 字符串 | `official` 或 `travelogue` |
| source | 字符串 | 发布机构或平台说明；精确 URL、标题和抓取时间另见 provenance |
| content | 字符串 | 清洗正文；实体跨度唯一对应此字段 |
| url | 字符串 | 真实采集页面，不使用搜索结果摘要作为正文 |

`data/processed/documents.json` 与 CSV 字段、内容相同。原文存入 `data/raw/extracted_records.json` 与底座数据库，额外的来源、清洗摘要和哈希存入 `data/processed/provenance.json`，避免改变六列接口。

## 实体结果

路径：`outputs/entities.json`。顶层是数组，每份清洗文档恰好一条对象。对象只有 `doc_id`、`scenic`、`source`、`entities` 四个字段。

实体对象只有 `text`、`type`、`start`、`end`、`sentence_id` 六个字段。`type` 只允许 `POI`、`TRANSPORT`、`TIME`。

- 本接口实体对象的 `source` 按 C 的示例填写 `official`／`travelogue`，即清洗表中的 `doc_type`；它与清洗表里表示发布机构的同名 `source` 字段含义不同。
- 字符位置从 0 开始，使用 Python Unicode 字符索引，区间 `[start,end)`。逐条满足 `content[start:end] == text`。含 emoji 的文本在 JavaScript 中应使用 `Array.from(content).slice(start,end).join("")`，不可直接使用 UTF-16 的字符串 `slice`。
- `sentence_id` 从 1 开始；分句依据中文句末符号、问号、感叹号、分号、换行。英文句点和冒号不是句界，避免拆开小数和时刻。完整映射见 `outputs/sentences.json`。
- 同一个词多次出现分别保留；父区域和子景点若重叠，以最长表述保留该次出现。未合并简称、全称、俗称，未把“圆丘”改成“圜丘”。
- `outputs/entities.meta.json` 保存正文 SHA256、算法版本与位置约定。B、C 应使用同一批表和实体；正文变化后须重新生成下游结果。

## 下游读取示例

```python
import csv
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]  # 按你自己的脚本位置调整
with (root / "data/processed/documents.csv").open(encoding="utf-8-sig", newline="") as stream:
    documents = {r["doc_id"]: r for r in csv.DictReader(stream)}
entities = json.loads((root / "outputs/entities.json").read_text(encoding="utf-8"))
for item in entities:
    text = documents[item["doc_id"]]["content"]
    for entity in item["entities"]:
        assert text[entity["start"]:entity["end"]] == entity["text"]
```

## B 的后续输出约定

沿用 C 原规范：`routes.json` 使用 `route_id/scenic/route_type/source_doc_id/steps`；`route_type` 是 `official` 或 `visitor`。步骤使用 `step/time_slot/poi_name/activity/transport_to_next/duration_min`，时长不确定填 `null`，景点保留原文。

原规范要求 `time_slot` 只取上午／中午／下午，但不少原文只有顺序、没有时段。A 不补写时间。B、C 应明确待定时间的处理方式，避免把推断时间当作原文事实。

`advices.json` 使用 `advice_id/scenic/condition_type/condition/advice/audience/source`，其中 `source` 是对应 `doc_id`；`condition_type` 是 `weather/crowd/audience/season/time/other`，`audience` 是老人／亲子／情侣／通用。A 不生成 B 的路线和条件建议文件。
