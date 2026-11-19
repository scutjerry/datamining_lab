# 实验7 旅游规划 Agent — 运行与复现说明

成员C（实验6 知识图谱 + 实验7 Agent）。本目录只依赖实验6 的图谱产物（`nodes.csv` / `edges.csv`），
不改动实验1~6 的任何文件。

## 1. 目录

```
实验7-旅游规划Agent/
├─ 代码/
│  ├─ kg_tools.py      图谱查询工具（4 个工具 + 统一返回信封 + 工具注册表）
│  ├─ llm.py           LLM 接入层（OpenAI 兼容协议）+ 不可用时的异常
│  ├─ planner.py       意图解析器 + 路线规划器（确定性算法，不含大模型猜）
│  ├─ agent.py         ReAct 主循环（LLM 后端 / 规则后端）+ CLI 入口
│  ├─ run_scenarios.py 11 类场景自动测试 + 证据落盘
│  ├─ test_agent.py    标准库 unittest 回归（不调用真实 API）
│  └─ requirements.txt 真实 API 模式依赖
└─ 输出/
   ├─ traces/          每次运行的完整轨迹 JSON（思考/行动/观察）
   ├─ 测试报告.md       场景覆盖表 + 逐场景回答 + 失败与边界分析
   ├─ 测试结果.json     同上，机器可读
   └─ 示范用例-故宫两小时.md  一条请求的完整链路 walkthrough
```

## 2. 依赖

- Python 3.8+，只用标准库（`json` / `csv` / `re` / `pathlib` / `argparse`）。
- 真实调用大模型时额外需要 `requests`（anaconda 自带）。
- 不需要 `openai` / `langchain` / `networkx`：工具层直接读 CSV，避免依赖地狱。

本机验证环境为 Windows、Python 3.12.10。规则模式和回归测试不要求密钥。
真实模型模式可在 `代码/` 下执行 `python -m pip install -r requirements.txt`。

## 3. 环境变量（只有用真实模型时才需要）

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `LLM_API_KEY` | 服务商 key；**不设置就自动走规则后端** | 无 |
| `LLM_BASE_URL` | OpenAI 兼容地址 | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 模型名 | `deepseek-flash`（服务端 display name：DeepSeek-V4.1-Flash） |

任何 OpenAI 兼容服务都可以：把 `LLM_BASE_URL` 换成 `https://dashscope.aliyuncs.com/compatible-mode/v1`、
`https://api.moonshot.cn/v1` 等即可，代码不用改。

Windows PowerShell 示例：
```powershell
$env:LLM_API_KEY="sk-xxxx"; $env:LLM_MODEL="deepseek-flash"
```

**不想设环境变量的话**：复制 `代码/llm_config.example.json` 为 `代码/llm_config.local.json`，各人填自己的 key：

```json
{ "LLM_API_KEY": "sk-你自己的key", "LLM_MODEL": "deepseek-flash" }
```

查找顺序：**环境变量 → 代码目录 `llm_config.local.json` → `~/.dsh/secrets/llm.local.json` → 默认值**。
这两个本地文件已被 `.gitignore` 忽略（`**/llm_config.local.json`、`**/llm.local.json`），不会进仓库；
删掉该文件即自动回到规则后端，不影响别人复现。模板里没改的占位符（如「你的api」）会被自动忽略，
不会被当成有效 key 去发请求。

环境变量也认常见别名：`DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`。

## 4. 运行

```powershell
cd 实验资料整理\实验7-旅游规划Agent\代码
python agent.py "我下午去故宫，只有两个小时，随便看看主要宫殿"     # 有 key 走 LLM，无 key 自动降级
python agent.py --offline "去故宫，只有20分钟"                   # 强制规则后端
python agent.py --json "我想去天坛，一个半小时，想祈福拍照"        # 只输出 trace JSON
python run_scenarios.py                                         # 跑 11 类场景 + Mock，生成测试报告
python agent.py --offline --chat                               # 多轮补充缺失约束，exit 退出
python -m unittest -v test_agent                               # 本地回归，不调用 API
```

其他用户可能在别的机器上没配 key，`run_scenarios.py` 默认就按"无 key"跑规则后端，
另外用 MockLLM 验证 LLM 分支的解析与编排代码路径，**报告里明确标注了这不是真实模型调用**。

## 5. 四个模块 ↔ 代码对应

| 模块 | 实现 | 说明 |
| --- | --- | --- |
| 意图解析器 | `Agent._parse_intent` + `planner.parse_constraints` | 在线先调用 LLM 输出结构化约束，运行时校验；规则提供明确字面约束、无 key 复现与异常回退 |
| 图谱查询工具 | `kg_tools.py` | 4 个工具，统一 `{ok,tool,count,data,note}` 信封；异常一律转 ok=false，Agent 不用 try/except |
| 路线规划器 | `planner.plan` | 硬约束过滤、官方路线优先、兴趣评分和预算内前缀截取；参数与评分在结构化结果中保留 |
| LLM 集成 | `llm.py` + `agent._run_llm` | LLM 解析与决策、工具回灌；协议错误在步数内纠正；服务不可用或输出截断时显式回退 |

## 6. ReAct 协议

每步模型只能输出一个 JSON：

```json
{"thought": "还缺景区，先问用户", "action": "finish", "action_input": {"followup": "想去哪个景区？"}}
{"thought": "先看有哪些路线", "action": "query_route", "action_input": {"scenic": "故宫博物院"}}
{"thought": "信息够了", "action": "finish", "action_input": {"answer": "..."}}
```

工具返回值以 `observation=<压缩后的 JSON>` 回灌（最多 12 条，不按字符硬切 JSON）。
5 个可用 action：`query_pois_by_scenic` / `query_route` / `query_advices` / `query_relation` / `route_plan`。

## 7. 测试方法（复现证据）

```powershell
python run_scenarios.py              # 规则后端 → 输出/测试报告.md
python run_scenarios.py --real-llm   # 真调模型 → 输出/测试报告-真实LLM.md
```

| 场景 | 请求 | 期望行为 |
| --- | --- | --- |
| S1 正常需求 | 故宫 + 2 小时 + 走马观花 | 调 4 个工具，给出 13 步、估算 114 分钟的行程 |
| S2 信息不足 | "我想去颐和园"（没时长） | 追问时长，不瞎排 |
| S3 无匹配 | 杭州西湖（不是图谱景区） | 明确说图谱里没有这个景区，再给可选项 |
| S4 预算冲突 | 故宫 20 分钟 | 只取 2 步并说明砍掉 10 个景点 |
| S5 兴趣约束 | 天坛 90 分钟 + 祈福拍照 | 按兴趣词过滤候选 + 完整行程 |
| S6 LLM 分支 | 同上 S1，MockLLM | 验证 JSON 解析→工具→回灌→finish 链路（仅规则后端跑） |

上表为原始五类需求与 Mock 设计。当前测试扩展为 11 个需求场景：
原 S1～S5，加老人慢行、亲子、情侣半天、复合时长、极短预算、必去与避开；
Mock 编排单独记为 M1。报告内保留每一项判定和实际模型调用次数。

当前 `judge()` 对规划场景检查：有结构化计划、严格不超时、耗时加和一致、
图谱路线/来源可追溯、站点保持原路线前缀、景点名称正确、必去与避开满足、最终文本与工具结果一致。
真实模式额外检查 LLM 意图解析成功、有实际模型调用、未回退到规则。回退不能冒充真实模型测试通过。

另有 `test_agent.py` 检查时间表达、否定、追问上下文、兴趣 A/B、预算边界、
参数错误、无依据回答、非法 HTTP 响应、JSON 花括号及脱敏。实际通过情况以最近生成的报告和测试命令输出为准。

## 8. 已知边界（如实写，不粉饰）

1. **时间全是估算**：实验6 图谱里 STEP 边的 `time_slot` / `duration_min` 100% 为空（实验3 没落时间维度），
   默认按 6 分钟/景点 + 3 分钟转场估算；快速为 4、深度为 10 分钟/景点；
   老人/亲子每点至少 8 分钟、转场 4 分钟。它们都是本地假设，不是实测或图谱事实。
2. **建议只有 3 条且全在故宫**，`audience` 全是"通用"；非故宫场景 `query_advices` 返回空并说明原因。
3. **没有受众标签**：老人/亲子通过耗时启发式适配；没有无障碍认证或亲子设施数据。
4. **景区外参照物**（杭州西湖、香山等）在图谱里是 `scope=nearby` 的 POI，不是景区，不能规划路线。
5. **游记路线可能拼接**：`route_type=visitor` 的路线来自单篇游记，实验6 已标 `quality_flag`，规划器默认官方路线优先。
6. **前缀截取不保证离园**：保留图谱已有顺序，不自由拼接景点；截断方案没有出口/返程耗时保证。
7. **适用范围有限**：仅支持单景区、1～1440 分钟；缺失约束追问仅在同一 Agent 实例或 `--chat` 会话内保存。

## 9. 与实验6 的接口

只读 `实验6-知识图谱\输出\nodes.csv`、`edges.csv`（当前 156 节点 / 377 边，3 景区、19 路线）。
若图谱重新生成，本目录无需改代码，重跑即可。

## 10. 产物对照（交给报告用）

| 产物 | 用途 |
| --- | --- |
| `输出/测试报告.md` | 规则后端 11 场景 + MockLLM 联通性，无 key 也能复现 |
| `输出/测试报告-真实LLM.md` | 真实模型 11 场景实际结果，含模型名、本轮调用次数与意图来源 |
| `输出/示范用例-真实LLM.md` | 一条请求的完整链路 walkthrough（意图解析 → 4 步 ReAct → 回答） |
| `输出/示范用例-规则后端.md` | 同上，规则后端版本 |
| `输出/traces/*.json` | 每次运行的原始轨迹（思考/行动/观察/耗时），测试报告里的每个结论都能追到文件 |
| `输出/测试结果.json`、`输出/测试结果-真实LLM.json` | 机器可读的判定结果（pass/why/工具序列） |

密钥安全：`LLM_API_KEY` 只通过环境变量或本地的 `llm_config.local.json` 传入。
`llm.status()` 统一显示 `[REDACTED]`，不保留密钥首尾片段；
错误与模型内容做完整密钥替换。本地配置文件已被 `.gitignore` 排除。

## 11. 对照 Final 评分细则（2026-11-19 迭代）

依据任务书“实验项目 7”五个考核项，覆盖关系如下。这是证据索引，不代表教师最终评分。

| 考核项 | 分值 | 实现与可检查证据 |
| --- | --- | --- |
| 基础架构与 LLM 集成 | 20 | `INTENT_PROMPT` → LLM 约束 JSON → `normalize_constraints`；trace 的 `intent`、`constraints`、本轮 `llm_calls` |
| 图谱工具 | 25 | 四个图谱工具 + `route_plan`；`TOOLS[*].args` 输入说明、运行时类型/枚举校验，统一 `{ok,tool,count,data,note}` 返回 |
| 推理与调用编排 | 25 | 模型按问题选工具；读 observation 后再决策；最终路线由工具结果确定性渲染，拒绝无依据 finish；有追问、错误纠正、服务回退 |
| 测试、证据、鲁棒性 | 20 | 11 个场景覆盖老人/亲子/情侣、三景区、时长/兴趣/冲突；结构化严格断言；34 项本地回归（含 Windows UTF-8 CLI） |
| 交互与复现 | 10 | 单次 CLI、`--chat` 追问、`--json`；配置模板、依赖清单与两种测试命令 |

### 11.1 规划方法与输入输出

约束核心字段：`scenic: string|null`、`minutes: integer|null`、
`audience`（通用/老人/亲子/情侣/学生）、`pace`（快速/常规/深度）、
`interests`、`must_visit`、`avoid_pois`（字符串数组）。
minutes 只有明确给出时才填写；多景区输入先追问选择，不自行只取第一个。

先按耗时策略截取每条候选路线的前缀，再过滤未满足必去或经过避开景点的候选。
官方来源优先；同类来源中最小化：

`score = 剩余分钟 + (截断 ? 20 : 0) - 20 × 兴趣名称命中数`

兴趣命中由 `INTEREST_KEYWORDS` 匹配景点名称，参数可审计；
相同偏好不保证总能换线，未命中也不伪称已个性化。
结果保留候选分数、命中景点、time_policy、来源文档 ID 和结构化站点。

### 11.2 可直接复现的前后对照

以下是迭代前实际观察到的失败输入，固定图谱和输入复测；不能把这些定向回归当成总体准确率。

| 输入/检查 | 迭代前 | 当前目标与验证 |
| --- | --- | --- |
| 2小时30分钟 / 三十分钟 | 30 分钟 / 未识别 | 150 / 30；ConstraintsTests |
| 不去故宫，去颐和园两小时 | 错选故宫 | 选颐和园；否定回归 |
| 故宫只有5分钟 | 强行安排 15 分钟 | 明确不可行；预算回归 |
| 颐和园90分钟，加园林兴趣 | 兴趣查询不改变规划 | A/B 中实际换线；保存命中依据 |
| 老人慢慢走 | 单站耗时未变化 | 耗时参数与站点数改变 |
| 追问后仅回复两个小时 | 丢失景区 | 同会话补全景区与时长 |
| 长篇假回答 + 调用过规划器 | 宽松 judge 误判通过 | 缺结构化依据即判失败 |

### 11.3 失败反思与一学期研究方向（报告素材）

**失败一：复合时长与预算错误。** 原解析先匹配分钟即返回，导致 2小时30分钟只剩 30；
路线截取又为了保留两个点强行超预算。这是确定性的算法/规则缺陷，不是模型随机误差。
改进为小时分钟累计、预算严格过滤，并固定同一输入对照、跨景区遍历预算边界。

**失败二：真实模型输出被截断。** 接入时出现 HTTP 200、`finish_reason=length`，
最终 JSON 不完整；900-token 上限还包含模型推理开销，反复纠正仍可能耗尽步数。
这是参数、协议与模型输出共同造成的失败。当前上限 2048，识别 length 后明确回退，
并测试畸形 JSON/HTTP；不把 HTTP 200 或规则回退当作真实模型场景成功。

**现有限制分层：** 数据上缺少距离、开放时段和人群设施；算法上只选现成路线前缀，
偏好匹配依赖名称；工程上同步 CLI、会话不持久化；泛化上仅 3 景区；
评估上结构化断言不等于真实游客满意度，仍缺独立人工标注的可行性评测集。

**若有一学期，仅优先突破一个点：带真实时空约束的可验证路线规划。**
补充有来源的步行时间和开放窗口，构建可达图；在相同景区、预算、必去/避开样本上，
比较现有前缀方法与时间窗约束搜索。固定候选 POI 与需求集，分别消融距离、时间窗、偏好项；
指标包括超时率、必去满足率、无法到达/闭园违规率、偏好覆盖率与规划耗时。
预期困难是路线数据缺失和时效漂移，可对缺失边保守估算并报告不确定性。
这部分是研究设计，尚未实施，报告中应与本轮已验证改动分开。
