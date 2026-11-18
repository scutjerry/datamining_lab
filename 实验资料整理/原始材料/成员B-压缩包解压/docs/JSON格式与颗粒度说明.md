# 实验三、四、五 JSON 格式与颗粒度

本文说明“数组里的一条记录代表什么”。区分文档、提及、结构节点和去重后的知识关系，是避免实验结果看起来数量很多、实际却无法核验的关键。

## 共同约定

- `record_id` 是输入文档的稳定主键。一篇游记或一条官方路线占一个输入文档记录。
- 所有 `start`、`end` 都是相对于该输入记录 `content` 的 Unicode 码点偏移，采用左闭右开区间。可用 `content[start:end]` 还原原文。
- `source_url` 为空是因为当前文件是课程生成语料，不是网页采集结果。不能把这些示例当作真实官网或游客原文提交。
- 结构化结果保留表面词、归一化词和证据文本。归一化方便统计，表面词和 span 用于回到原文。

## 实验三 路线层级结构挖掘

### 层级

```text
输入文档 route_record（每条官方路线或每篇游记）
└── 原文 POI 提及 route_step（每次提及一条）
    ├── 时间层 time_bucket
    ├── 活动 activity[]
    └── 原文位置 source_span + evidence_span
```

不要把“一篇游记”直接当作“一条路线步骤”。一份来源文本是 `route_record`；其中每一次出现的景点 POI 是一个独立 `route_step`。若文本两次提到同一个景点，仍保存两个步骤，因为它们可能表示再次到访或返程。`event_kind=return` 的步骤保留在输出里，但主路线覆盖率和顺序比较只使用 `visit` 步骤。

时间层是步骤属性和层级索引，不会复制整条路线文本。`route_hierarchy.time_blocks[].step_ids` 只引用步骤主表中的 ID，避免同一景点步骤在 JSON 中被复制多份。

### 路线步骤节选

以下是字段形状示例，具体完整输出见 `outputs/exp3/route_steps.json`：

```json
{
  "step_id": "bj_official_01_step_001",
  "route_id": "bj_official_01",
  "step_index": 1,
  "time_block_index": 1,
  "time_bucket": "上午",
  "time_evidence": "上午",
  "poi_surface": "午门",
  "poi_canonical": "午门",
  "activity": [{"type": "enter", "text": "入馆"}],
  "event_kind": "visit",
  "source_span": {"start": 12, "end": 14, "unit": "unicode_codepoint"},
  "evidence_span": {
    "start": 4,
    "end": 20,
    "text": "上午 8:30 从午门入馆",
    "unit": "unicode_codepoint"
  }
}
```

### 路线比较粒度

比较对象是一条官方 `route_id` 与同一景区的一篇游客 `route_id`，因此当前语料产生 15 组比较。指标在归一化后去重的 POI 序列上计算：

- `official_coverage`：游客路线出现过的官方 POI 数 / 官方唯一 POI 数。
- `sequence_lcs_similarity`：最长公共子序列长度 / 两条路线唯一 POI 并集大小。
- `order_consistency`：共同 POI 两两顺序保持比例；共同 POI 少于 2 个时为 `null`。
- `time_distribution_total_variation`：按步骤数估计时间层分布差异，不代表实际停留时长。

箭头链路和编号路线由合成解析夹具单独测试，不混入课程语料统计。夹具结果见 `outputs/exp3/format_fixture_results.json`。

## 实验四 共指消解

### 颗粒度

一条 `pronoun_mention` 表示一个文档中的一次代词提及，不是一整句，也不是一个候选实体。唯一定位字段为 `record_id + pronoun + occurrence`，另存字符偏移和完整句子范围。

预测先行词和人工标注先行词分开存储：`predicted_antecedent` 是规则结果，`gold_antecedent` 只在人工标注样本上有值。未标注提及的 `correct` 为 `null`，不参加准确率分母。最近实体基线只搜索同一文档中代词之前的 POI，不能把小样本成绩解释为通用共指能力。

### 代词提及节选

```json
{
  "mention_id": "bj_note_02_那里_01",
  "record_id": "bj_note_02",
  "pronoun": "那里",
  "occurrence": 1,
  "pronoun_span": {"start": 63, "end": 65, "unit": "unicode_codepoint"},
  "sentence": "那里台阶较多，老人走慢一点更稳妥。",
  "predicted_antecedent": "中和殿",
  "gold_antecedent": "中和殿",
  "annotation_status": "human_labeled",
  "correct": true
}
```

样例中的偏移以本次输入快照为准；最终准确值请以 `outputs/exp4/pronoun_mentions.json` 为准。`coref_gold.json` 中的先行词是助手预标注，不是组员的人工标注；请先核对再把 `annotation_source` 更新为真实标注来源。

## 实验五 条件性建议抽取

### 两种粒度

- `condition_advice_mentions.json`：原文提及粒度。每条记录是一篇来源中的一个条件—建议证据，带原文区间。
- `condition_advice_mappings.json`：知识映射粒度。一个去重后的映射是“一个条件 + 一个原子建议”。跨来源重复时合并映射，但 `evidence[]` 中保留每个来源和原文位置。

例如“如果下雨，建议穿防滑鞋并带轻便雨衣”拆为两条原文映射提及：“下雨 -> 穿防滑鞋”和“下雨 -> 带轻便雨衣”。条件与建议都能由各自 span 回溯。不要把整篇游记、一整句话或一个包含多个动作的长段落当作一条映射。

### 去重主键

```text
景区 + 条件类型 + 规范化条件 + 规范化单项建议
```

去重只合并相同的条件—建议关系，不合并原始来源证据。每个映射的 `evidence_count` 应等于其 `evidence[]` 项数。

### 条件—建议映射节选

```json
{
  "mapping_id": "map_0001",
  "attraction": "故宫博物院",
  "condition_type": "weather",
  "condition": {"text": "下雨", "normalized": "下雨"},
  "advice": {"text": "穿防滑鞋", "normalized": "穿防滑鞋"},
  "evidence_count": 1,
  "source_record_ids": ["bj_note_03"],
  "evidence": [
    {
      "record_id": "bj_note_03",
      "condition_text": "下雨",
      "condition_span": {"start": 2, "end": 4, "unit": "unicode_codepoint"},
      "advice_text": "穿防滑鞋",
      "advice_span": {"start": 9, "end": 13, "unit": "unicode_codepoint"},
      "evidence_sentence": "如果下雨，建议穿防滑鞋并带轻便雨衣。"
    }
  ],
  "manual_review": {"status": "accepted", "review_scope": "representative_sample"}
}
```

生产输出会包含完整的 `text_type`、句序、完整区间、抽取规则和复核备注。当前 12 条候选不计作本人已完成人工复核；请在 `data/condition_review_candidates.json` 中确认或修改候选结论。字段约束见 `schemas/experiment_3_4_5.schema.json`，本次完整输出样例见 `docs/json_examples.json`。

## 按小组接口调整颗粒度

尽量与组员约定一个“最小事实单元”，避免某人的 JSON 一条代表整份文档、另一人的 JSON 一条代表单个实体。

### 实验三

- 当前：每次 POI 提及一条 `route_step`，最适合和实验二的 POI 实体逐条对接，也能计算顺序。
- 若组内接口要求“一段时间安排一条”：不要删除步骤表；改为把 `route_hierarchy.time_blocks[]` 作为交接记录，块内 `step_ids` 引用步骤。这样比较、返程和原文定位仍可复用。
- 若组内只接收“路线 POI 序列”：从 route_step 按 `step_index` 投影出字符串数组即可，不必让核心输出降粒度。

### 实验四

- 当前：每一个代词 occurrence 一条记录，保留 `record_id + pronoun + occurrence` 和字符跨度；这是能够评估共指准确率的最细粒度。
- 若组内接口要求“每句一条”：以 `record_id + sentence_span.start` 分组，增加 `mentions[]` 子数组。不要把同一句多个代词压成一个先行词字段。
- 若下游只需要替换后的文本：使用 `resolved_examples.json`，但仍保留 `pronoun_mentions.json` 作为可审查明细。

### 实验五

- 当前：一个条件 + 一个原子建议一个去重映射；原始重复来源放在 `evidence[]`。
- 若组内更需要“每条原文证据一行”：交接 `condition_advice_mentions.json`，不要做跨文档去重。
- 若组内需要“每个条件聚合全部建议”：在 `condition_advice_mappings.json` 外再按 `attraction + condition_type + condition` 分组，将 `advice[]` 汇总；不要把独立建议拼成无法单独评估的长字符串。
- 修改去重粒度的位置是 `src/exp5_conditions.py` 的 `aggregate_mappings()` 主键。当前主键包含景区、条件类型、规范化条件和规范化单项建议。

调整规则：先保留最细的原文提及层，再派生较粗视图。较粗视图可以聚合引用，不能覆盖或丢弃明细层的 span 和来源。
