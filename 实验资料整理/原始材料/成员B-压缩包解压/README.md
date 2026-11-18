# 个人负责实验 3、4、5

这是一个与课程全量工程隔离的工作目录，只运行实验三、四、五。输入数据是从上级工程复制的 18 条课程生成语料，不是网页真实采集数据；原上级目录和文件不会由本项目改写。

## 运行

需要 Python 3.10+、Pillow。Windows PowerShell 首次配置依赖并运行：

```powershell
python -m pip install -r requirements.txt
python -m src.exp3_routes
python -m src.exp4_coref
python -m src.exp5_conditions
```

一次执行三项实验：

```powershell
python run_experiments_3_4_5.py
```

测试两类解析格式：

```powershell
python -m unittest discover -s tests -v
```

## 目录

- `data/cleaned_data.jsonl`：输入文档级数据。
- `data/entity_dict.txt`：实验二提供的 POI 词典。
- `data/coref_gold.json`：5 个共指先行词预标注样本，需本人核验。
- `data/condition_review_candidates.json`：12 条条件映射复核候选，需本人确认。
- `data/route_format_fixtures.json`：箭头链路、编号路线解析夹具，不混入真实统计。
- `data/condition_manual_review_sample.json`：实验五 12 条代表性人工抽查记录。
- `schemas/experiment_3_4_5.schema.json`：实验输出 Schema。
- `docs/JSON格式与颗粒度说明.md`：JSON 粒度、字段和示例说明。
- `docs/json_examples.json`：从实际运行输出生成的完整 JSON 示例。
- `report/实验3-5个人实验报告.md`：本次实验结果与提交前待完成事项。
- `outputs/exp3/`、`outputs/exp4/`、`outputs/exp5/`：结构化结果、质量指标和图表。
- 共指和条件建议的预标注/复核候选尚待本人核验，不能称为组员已完成人工标注。

## 粒度速览

- 实验三：一个 `route_record` 对应一份来源文本；一条 `route_step` 对应原文里一次 POI 提及。重复提及保留，返程提及标为 `event_kind=return`。
- 实验四：一个 `pronoun_mention` 对应一个代词在一份文档中的一次出现，以 `record_id + pronoun + occurrence` 唯一定位。先行词是助手预标注，须由组员核验后才能称为人工标注。
- 实验五：一个去重后 `condition_advice_mapping` 对应一个条件和一个原子建议；重复表达合并到 `evidence[]`，所有原文提及及其字符区间仍保留。

所有 span 使用 Unicode 码点偏移，可以直接在对应原文上用 `text[start:end]` 还原。
