# -*- coding: utf-8 -*-
"""Refresh copy-ready JSON examples and the experiment 3-5 result note."""

from __future__ import annotations

from .common import DATA, OUT, ROOT, read_json, read_jsonl, write_json


def build_examples() -> None:
    routes = read_json(OUT / "exp3" / "route_records.json")
    steps = read_json(OUT / "exp3" / "route_steps.json")
    hierarchy = read_json(OUT / "exp3" / "route_hierarchy.json")
    comparisons = read_json(OUT / "exp3" / "route_comparisons.json")
    coref = read_json(OUT / "exp4" / "pronoun_mentions.json")
    mappings = read_json(OUT / "exp5" / "condition_advice_mappings.json")
    source = {row["record_id"]: row for row in read_jsonl(DATA / "cleaned_data.jsonl")}

    official = next(route for route in routes if route["text_type"] == "official_route")
    first_step = next(step for step in steps if step["route_id"] == official["route_id"])
    official_compare = next(item for item in comparisons if item["official_route_id"] == official["route_id"])
    pronoun_sample = next(item for item in coref if item["annotation_status"] != "unlabeled")
    mapping = next(
        item
        for item in mappings
        if item["condition_type"] == "weather" and item["condition"]["normalized"] == "下雨" and item["advice"]["normalized"] == "穿防滑鞋"
    )
    examples = {
        "offset_convention": "start/end are zero-based Unicode codepoint offsets, half-open; slice the record content with content[start:end].",
        "experiment_3": {
            "granularity": "one route_step per POI mention",
            "route_record": official,
            "route_step": first_step,
            "route_hierarchy": next(item for item in hierarchy if item["route_id"] == official["route_id"]),
            "route_comparison": official_compare,
        },
        "experiment_4": {
            "granularity": "one pronoun occurrence per mention record",
            "pronoun_mention": pronoun_sample,
            "source_content": source[pronoun_sample["record_id"]]["content"],
        },
        "experiment_5": {
            "granularity": "one atomic advice per condition mapping; duplicate relations aggregate source evidence",
            "condition_advice_mapping": mapping,
            "source_content": source[mapping["evidence"][0]["record_id"]]["content"],
        },
    }
    write_json(ROOT / "docs" / "json_examples.json", examples)


def build_report() -> None:
    r3 = read_json(OUT / "exp3" / "summary.json")
    r4 = read_json(OUT / "exp4" / "evaluation.json")
    r5 = read_json(OUT / "exp5" / "summary.json")
    type_names = {
        "weather": "天气",
        "visitor_type": "游客类型",
        "time_constraint": "时间约束",
        "crowd_level": "拥挤程度",
        "preference": "游览偏好",
        "other": "其他",
    }
    condition_counts = "、".join(f"{type_names.get(key, key)} {value} 条" for key, value in r5["mappings_by_condition_type"].items())
    examples = ROOT / "docs" / "json_examples.json"
    text = f"""# 实验三、四、五阶段性报告

本目录是个人负责实验的隔离工程。输入数据来自课程生成语料，并非真实网页抓取；结果只用于展示和检查代码流程，正式提交前需换成小组确认的数据并核对人工标注。

## 实验三 路线层级结构挖掘

- 路线来源记录：{r3['route_records']} 条（官方路线 {r3['official_routes']} 条、游客文本 {r3['traveler_routes']} 篇）。
- POI 提及步骤：{r3['route_step_mentions']} 条，每次出现单独记录，重复 POI 保留。
- 官方/游客配对比较：{r3['comparison_count']} 组；平均官方节点覆盖率 {r3['mean_official_coverage']:.4f}；有至少两个共同 POI 的配对中，平均顺序一致性 {r3['mean_order_consistency']:.4f}。
- 所有路线步骤原文跨度检查通过：{r3['source_span_integrity']['checked_steps']} 条。箭头链路和编号列表两种格式解析夹具均通过。
- 时间分布按路线步骤数量估计，不表示实际停留时间。比较指标是本演示语料上的样本统计。

## 实验四 程序性知识共指消解

- 检测代词提及：{r4['detected_mentions']} 条，其中助手建议标注 {r4['preannotated_mentions']} 条，学生确认 {r4['student_confirmed_mentions']} 条。
- 最近前置 POI 规则相对当前预标注结果的准确率：{r4['accuracy_against_preannotations']:.4f}。这不是正式人工评估准确率；学生核验后应更新 `data/coref_gold.json` 并重跑。
- 提及偏移和句子跨度检查通过：{r4['source_span_integrity']['checked_spans']} 个跨度。
- 当前样本仅覆盖少量 POI 指代，需补充无先行词、游客群体指代、跨句指代和多候选干扰样本。

## 实验五 条件性游览建议抽取

- 去重前原文条件—建议提及：{r5['condition_advice_mentions_before_dedup']} 条；去重映射：{r5['unique_mappings_after_dedup']} 条。
- 类型数量：{condition_counts}。
- 原文跨度检查：{r5['source_span_integrity']['checked_evidence']} 条证据全部通过。
- 已准备 {r5['student_review']['assistant_precheck_candidates']} 条代表性复核候选，尚无学生确认。其余 {r5['student_review']['pending_outside_precheck_sample']} 条也保留在学生复核队列中。当前不报告正式人工精确率。

## JSON 颗粒度

- 实验三：输入文档一个 route_record；一处 POI 提及一个 route_step；time block 以 step_id 引用步骤主表。
- 实验四：一处代词出现一个 mention；使用 record_id、代词和 occurrence 定位。预测与预标注分开存储。
- 实验五：一个条件加一个原子建议形成一个映射；相同映射合并到一个主记录，所有来源片段作为 evidence 数组保留。
- 所有字符区间是 Unicode 码点左闭右开，可直接用 `content[start:end]` 复原。

可复制的完整实例见 [json_examples.json](../docs/json_examples.json)，字段约束见 [experiment_3_4_5.schema.json](../schemas/experiment_3_4_5.schema.json)。

## 提交前由本人完成

1. 用小组确认的数据替换 `data/cleaned_data.jsonl`，补上真实来源信息。
2. 在 `data/coref_gold.json` 中逐条核验先行词，把 `annotation_source` 更新为本人/小组人工标注后重新运行。
3. 在 `data/condition_review_candidates.json` 中逐条确认建议是否合理，并将状态和理由记录到映射结果。
4. 阅读 `docs/JSON格式与颗粒度说明.md`，按组内接口决定是否改变颗粒度。若组内已有实验二的实体 JSON，可在 `data/entity_dict.txt` 基础上补充或替换 POI 词典，并重跑实验三、四。
"""
    report_dir = ROOT / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "实验3-5个人实验报告.md").write_text(text, encoding="utf-8")


def main() -> None:
    build_examples()
    build_report()


if __name__ == "__main__":
    main()
