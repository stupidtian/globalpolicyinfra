# 澳大利亚（AUS）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。
> 文件命名规则：`{iso3}/{source}-{lang}.md`（国家文件夹 + 语言后缀，lang ∈ zh/en）；九节写作结构见 [_template-zh.md](../_template-zh.md)。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `frl` | 联邦立法登记册全量：Acts（法律）、legislative instruments（立法文书）、notifiable instruments（可告知文书）等，含每个标题的版本谱系（as-made 颁布原样版 + 编纂版）与文书解释声明 | legislation.gov.au 官方 OData API（免 key） | [frl-zh.md](./frl-zh.md) |

## 2. 共享访问准备

| 项 | 说明 |
|---|---|
| 数据目录 | `python cli.py init` 配置，或 `POLICY_DATA_ROOT` 环境变量；澳大利亚数据落在 `{data_root}/AUS_policy/` |
| 密钥 | **不需要**，`.env` 无需任何条目 |
| 通用命令习惯 | `collect`（key=value 传参）/ `status` / `export` / `requeue` / `reset`，全部在仓库根目录 `python cli.py` 运行 |
| 节奏 | 框架统一限速（请求间隔 0.5–1 秒随机）+ 错误三分法重试，数据不丢 |

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| 议会立法过程（bill → Act 之前） | 不在 FRL（在 parlinfo.aph.gov.au）；frl 标题元数据保留 `originating_bill_uri` 跳转线索，列为后续扩展 |
| 州与领地立法 | 各州自己的登记册（NSW/VIC/QLD 等），不在本源范围 |
| 联邦公报（Gazette）正文 | 标题台账入账、正文默认不下载（`gazette=1` 可开） |
| 法规历史编纂全量回填 | 端点与口径已就绪（`comp=all`），全量另议 |

---

*更新日期：2026-08-31；数据快照：2026-08-31；数据由 frl 实跑窗口背书（200 任务、68 标题、69 文档，见源文件文末）。*
