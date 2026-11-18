# 实验7 旅游规划 Agent — 运行与复现说明

成员C（实验6 知识图谱 + 实验7 Agent）。本目录只依赖实验6 的图谱产物（`nodes.csv` / `edges.csv`），
不改动实验1~6 的任何文件。

## 1. 目录

```
实验7-旅游规划Agent（成员C）/
├─ 代码/
│  ├─ kg_tools.py      图谱查询工具（4 个工具 + 统一返回信封 + 工具注册表）
│  ├─ llm.py           LLM 接入层（OpenAI 兼容协议）+ 不可用时的异常
│  ├─ planner.py       意图解析器 + 路线规划器（确定性算法，不含大模型猜）
│  ├─ agent.py         ReAct 主循环（LLM 后端 / 规则后端）+ CLI 入口
│  └─ run_scenarios.py 5 类场景自动测试 + 证据落盘
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

## 4. 运行

```powershell
cd 实验资料整理\实验7-旅游规划Agent（成员C）\代码
python agent.py "我下午去故宫，只有两个小时，随便看看主要宫殿"     # 有 key 走 LLM，无 key 自动降级
python agent.py --offline "去故宫，只有20分钟"                   # 强制规则后端
python agent.py --json "我想去天坛，一个半小时，想祈福拍照"        # 只输出 trace JSON
python run_scenarios.py                                         # 跑 5 类场景 + 生成测试报告
```

其他用户可能在别的机器上没配 key，`run_scenarios.py` 默认就按"无 key"跑规则后端，
另外用 MockLLM 验证 LLM 分支的解析与编排代码路径，**报告里明确标注了这不是真实模型调用**。

## 5. 四个模块 ↔ 代码对应

| 模块 | 实现 | 说明 |
| --- | --- | --- |
| 意图解析器 | `planner.parse_constraints` | 正则提取景区/时长/人群/节奏/兴趣/时段；中文数字（一个半小时=90）都覆盖 |
| 图谱查询工具 | `kg_tools.py` | 4 个工具，统一 `{ok,tool,count,data,note}` 信封；异常一律转 ok=false，Agent 不用 try/except |
| 路线规划器 | `planner.plan` | 官方路线优先、按预算截断、给出取舍理由；时间估算常量 `MIN_PER_POI=6` / `MIN_TRANSFER=3` 显式可审计 |
| LLM 集成 | `llm.py` + `agent._run_llm` | 严格 JSON 逐步协议；解析失败回灌纠错一次；模型不可用自动降级到规则后端 |

## 6. ReAct 协议

每步模型只能输出一个 JSON：

```json
{"thought": "还缺景区，先问用户", "action": "finish", "action_input": {"followup": "想去哪个景区？"}}
{"thought": "先看有哪些路线", "action": "query_route", "action_input": {"scenic": "故宫博物院"}}
{"thought": "信息够了", "action": "finish", "action_input": {"answer": "..."}}
```

工具返回值以 `observation=<压缩后的 JSON>` 回灌（最多 12 条，避免撑爆上下文）。
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

判定逻辑写在 `run_scenarios.py` 的 `judge()`：按场景检查"是否给出行程 / 是否追问 / 是否点明查不到 / 是否点明冲突"，
全部通过才返回码 0。

**两种后端都已实测通过**：
- 规则后端：6/6 通过（含 MockLLM 的 LLM 分支联通性验证）；
- 真实 LLM（DeepSeek 兼容接口，服务端实际返回 `deepseek-flash`）：5/5 通过，
  每次运行调模型 10~14 次（含纠正 JSON 的二次请求），证据见 `输出/测试报告-真实LLM.md`。

## 8. 已知边界（如实写，不粉饰）

1. **时间全是估算**：实验6 图谱里 STEP 边的 `time_slot` / `duration_min` 100% 为空（实验3 没落时间维度），
   所以行程时长 = 6 分钟/景点 + 3 分钟转场，写进了每条回答的"注意"里。
2. **建议只有 3 条且全在故宫**，`audience` 全是"通用"；非故宫场景 `query_advices` 返回空并说明原因。
3. **没有受众标签**：老人/亲子只能靠常识补充，回答里会明确标注"不算图谱结论"。
4. **景区外参照物**（杭州西湖、香山等）在图谱里是 `scope=nearby` 的 POI，不是景区，不能规划路线。
5. **游记路线可能拼接**：`route_type=visitor` 的路线来自单篇游记，实验6 已标 `quality_flag`，规划器默认官方路线优先。

## 9. 与实验6 的接口

只读 `实验6-知识图谱（成员C）\输出\nodes.csv`、`edges.csv`（159 节点 / 377 边）。
若图谱重新生成，本目录无需改代码，重跑即可。

## 10. 产物对照（交给报告用）

| 产物 | 用途 |
| --- | --- |
| `输出/测试报告.md` | 规则后端 5 场景 + MockLLM 联通性，无 key 也能复现 |
| `输出/测试报告-真实LLM.md` | 真实模型 5 场景全通过，含每次请求的模型名与调用次数 |
| `输出/示范用例-真实LLM.md` | 一条请求的完整链路 walkthrough（意图解析 → 4 步 ReAct → 回答） |
| `输出/示范用例-规则后端.md` | 同上，规则后端版本 |
| `输出/traces/*.json` | 每次运行的原始轨迹（思考/行动/观察/耗时），测试报告里的每个结论都能追到文件 |
| `输出/测试结果.json`、`输出/测试结果-真实LLM.json` | 机器可读的判定结果（pass/why/工具序列） |

密钥安全：`LLM_API_KEY` 只通过环境变量传入，代码与产物里不落盘、不打印（`llm.status()` 只返回掩码后的前 6 位与后 4 位）。
