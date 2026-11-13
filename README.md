# 数据挖掘探索性实验

本仓库用于成员 A、B、C 协作完成景区游览指南的程序性知识挖掘。成员 A 的实现负责项目 1 数据采集与预处理、项目 2 实体识别；B、C 可以直接读取已提交的数据，无须重新爬取网页。

A 部分位于独立分支 `codex/member-a-data-entities`。首次获取可运行 `git clone --branch codex/member-a-data-entities https://github.com/scutjerry/datamining_lab.git`；B、C 可在此基础上创建各自的工作分支。`main` 目前只用于初始化公共仓库。

## 成员 A 已交付内容

- 三个景区：故宫博物院、颐和园、天坛公园。
- 数据底座：原始 HTML、采集清单、正文提取记录和 `data/foundation.sqlite`。
- 团队共用清洗表：`data/processed/documents.csv`，同时提供内容相同的 JSON。
- 实体结果：`outputs/entities.json`，每份文档一条，字段遵循成员 C 的 v1.0 接口。
- 字符位置说明、分句表、词频图、质量报告、五版识别结果、参考标注与核验表。

完整交接说明见 [成员 A 交接说明](docs/MEMBER_A_HANDOFF.md)，字段约定见 [接口规范](docs/INTERFACE.md)。

## 安装与运行

使用 Python 3.11 及以上。此次实际运行环境是 Windows、Python 3.14；精确依赖记录见 `requirements-lock.txt`。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# 首次运行，包含联网采集；有缓存时验证校验和后复用。
.\.venv\Scripts\python.exe scripts/run_member_a.py all
# 从已提交的原始数据底座离线重建。
.\.venv\Scripts\python.exe scripts/run_member_a.py clean
.\.venv\Scripts\python.exe scripts/build_lexicon.py
.\.venv\Scripts\python.exe scripts/run_member_a.py ner
.\.venv\Scripts\python.exe scripts/evaluate_member_a.py
.\.venv\Scripts\python.exe scripts/evaluate_postfreeze.py --version 4
.\.venv\Scripts\python.exe scripts/evaluate_postfreeze.py --version 5
.\.venv\Scripts\python.exe scripts/run_member_a.py validate
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Linux/macOS 使用 `python3` 建立环境，并将示例中的解释器路径替换成 `.venv/bin/python`。

需要重新抓取时才运行 `scripts/run_member_a.py collect --refresh`。更新正文以后必须重新执行识别和校验；下游已有结果的字符位置不适用于新版正文。参考标注依赖当前正文版本，正文变动后须复核标注。

## 协作边界

| 成员 | 负责内容 | 读取 A 的输出 |
| --- | --- | --- |
| A | 项目 1、2 | 原始页面与来源清单 |
| B | 项目 3、4、5 | `data/processed/documents.csv`，可复用实体和分句表 |
| C | 项目 6、7 | 清洗表与 `outputs/entities.json` |

`doc_id` 为全局关联键。A 保留实体原文写法，名称归一化由 C 统一完成。接口字段变更应先同步规范与团队。

## 方法参考

调研过 [Trafilatura](https://github.com/adbar/trafilatura)、[Jieba](https://github.com/fxsjy/jieba)、[JioNLP](https://github.com/dongrixinyu/JioNLP) 和 [HanLP](https://github.com/hankcs/HanLP)。最终使用标准库 urllib 顺序采集、BeautifulSoup 按站点提取正文、领域词典与正则识别，Jieba 提供自定义词典分词样例，Matplotlib 绘制词频图。

由于网页只有少量固定来源，正文使用已检查的站点选择器，以便保留路线列表并在页面结构变化时明确报错。识别通过词典和规则直接生成跨度；Jieba 分词、通用 NER 模型和 LLM 均不被当作真实标注。没有调用收费 API，也无需配置密钥。

本仓库保存的网页是研究用采集快照，原作者及发布平台信息见采集清单；网页内容并不因存入仓库而获得新的开放许可。
