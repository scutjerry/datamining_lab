# 实验资料整理说明

整理日期：2026-11-16　整理人：成员C
数据来源：① GitHub 仓库 `scutjerry/datamining_lab` 分支 `codex/member-a-data-entities`（成员A，2026-11-13 提交）；② 成员B 的压缩包《个人负责实验3-5.zip》。两处原始材料完整保留在 `原始材料/`，本目录为按实验任务整理的副本。

## 目录结构

```
实验资料整理/
├── 00-任务书与规范/                  任务书、报告模板、Schema 规范、给 A/B 的接口说明
├── 实验1-数据采集与预处理（成员A）/    真实采集的 3 景区 21 篇文档（故宫/颐和园/天坛）
│   ├── 代码/                          collect.py、clean.py、discover.py 等 + config
│   ├── 数据/raw/                      23 个页面的原始 HTML + 抓取清单
│   ├── 数据/processed/                documents.csv（六列接口表）、provenance
│   ├── 数据/foundation.sqlite         原文/清洗文关联底座
│   └── 质量检查/                      清洗前后对比、数据质量、隔离记录
├── 实验2-实体识别（成员A）/            3032 个实体（POI 2747 / TRANSPORT 97 / TIME 188）
│   ├── 代码/                          词典、识别与评估脚本、schemas
│   ├── 结果/                          entities.json（v5 最终版）、词频、分句
│   ├── 迭代与图表/                    v1–v5 迭代文件、词频图
│   ├── 人工评估/                      human_review、reference 评估材料
│   └── 质量检查/                      接口校验、复核、可复现性记录
├── 实验3-路线层级结构（成员B）/         18 条路线、115 个步骤、格式夹具
├── 实验4-程序性知识共指消解（成员B）/   代词检测、5 个预标注样本、评估结果
├── 实验5-条件性游览建议（成员B）/       33 条去重后的条件-建议映射、复核候选
├── 实验6-知识图谱（成员C）/            （空，待建）
├── 实验7-旅游规划Agent（成员C）/       （空，待建）
├── 文档与交接/
│   ├── 成员A/                         README、INTERFACE、交接说明、requirements、tests
│   └── 成员B/                         个人报告、JSON 格式说明、schema、运行入口
└── 原始材料/                          两部分未经整理的完整原样（A 的整个分支 + B 的压缩包及解压）
```

## 当前状态与问题（重要）

**成员A（实验1、2）——可用。** 数据为真实网页采集，21 篇有效文档（2 页隔离），字段完全符合《给AB的输出格式说明》v1.0。实体跨度已校验：3032 个实体全部能在原文中精确还原（0 错误）。

**成员B（实验3、4、5）——管线可用，但数据源和格式需要返工。**

1. 输入用的是"课程生成语料"18 条，景区是**故宫、杭州西湖、上海迪士尼**（record_id 形如 `bj_official_01`、`sh_note_02`），与 A 的真实数据（doc_id 形如 `D001…D305`，故宫/颐和园/天坛）**无法按来源关联**。B 个人报告里也已列出"用小组确认的数据替换 cleaned_data.jsonl"为一号待办。
2. 输出格式与组内接口约定不一致：`attraction/text_type/time_bucket/poi_surface` 等字段名与 `scenic/route_type/time_slot/poi_name` 的约定不符；条件建议缺 `audience` 字段；`condition_type` 枚举与约定不同，需要映射。
3. B 有两项人工核验未完成：共指消解的 5 个先行词标注仍是助手预标注（`student_review_pending`），条件建议的 12 条复核候选也待确认。两者直接对应任务书"人工标注 20 分"。

**处理建议：** B 把 A 的 `data/processed/documents.csv` 转换为他的 `cleaned_data.jsonl` 格式后重跑，并按接口约定导出 `routes.json` / `advices.json`；C 同步写适配层，把 B 现有输出（`route_steps.json`、`condition_advice_mappings.json`）转换为图谱的 STEP 边和 Advice 节点。另需约定：原文无明确时段的路线，`time_slot` 允许为 `null`。

## 2026-11-16 更新：B 结果已在真实数据上重跑并适配

- 实验3/4/5 的 `结果-真实数据重跑/`：用 A 的真实数据跑 B 的管线所得。三个实验均跑通、跨度校验通过。
- `实验6-知识图谱（成员C）/接口数据/`：适配后的 `routes.json`（19 条路线、250 步，官方链式路线行提取）、`advices.json`（3 条高置信条件建议）、`quality_report.json`、适配脚本与 `适配说明.md`。
- 关键结论：B 的规则在真实长文本上质量不达标（提及级解析过细、条件规则误报、复核样本不适用），返工清单见 `接口数据/适配说明.md` 第四节。B 的原生成语料结果保持原样未动。

## 运行成员B的完整项目

`原始材料/成员B-压缩包解压/` 是完整可运行工程：

```
python -m pip install -r requirements.txt
python run_experiments_3_4_5.py
```

各实验文件夹中的 代码/ 是便于单文件查看的副本，模块间有相对导入依赖，实际运行请用完整项目。
