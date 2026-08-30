# 德国（DEU）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。
> 文件命名规则：`{iso3}/{source}-{lang}.md`（国家文件夹 + 语言后缀，lang ∈ zh/en）；九节写作结构见 [_template-zh.md](../_template-zh.md)。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `bgbl` | 联邦法律公报 Teil I（法律、法规、宪法法院判决主文、联邦总统令）：1949–2022 纸质公报的官方数字档案，逐条目 PDF | bgbl.de（Bundesanzeiger Verlag 官方档案站，无需 key） | [bgbl-zh.md](./bgbl-zh.md) |

## 2. 共享访问准备

| 项 | 说明 |
|---|---|
| 数据目录 | `python cli.py init` 配置，或 `POLICY_DATA_ROOT` 环境变量；德国数据落在 `{data_root}/DEU_policy/` |
| 密钥 | **无需任何 key**，`.env` 不需要条目 |
| 通用命令习惯 | `collect`（key=value 传参）/ `status` / `export` / `requeue` / `reset`，全部在仓库根目录 `python cli.py` 运行 |
| 节奏 | 框架统一限速（请求间隔 0.5–1 秒随机）+ 错误三分法重试；PDF 端点需要会话（cookie + 令牌），任务链自动建立，无需人工介入 |

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| BGBl Teil II（国际条约与协定） | 同站同构（覆盖 1951–2022），已探明未开抓——结构见 [bgbl-zh.md](./bgbl-zh.md) §8，开抓只需改 Teil 节点与路径前缀 |
| 2023 年起的电子公报 | 2023-01-01 起德国改在 recht.bund.de 电子公布，属另一源，未开工 |
| 现行法整合文本（gesetze-im-internet） | 联邦司法部的现行法规汇编（XML 全文），未开工 |
| Bundesanzeiger（联邦公报） | 部分公告与法规全文的补充公布渠道，未开工 |
| 立法过程（法案/辩论/表决） | Bundestag（联邦议院）信息系统，未开工 |

---

*更新日期：2026-08-30；数据快照：2026-08-30；数据由 bgbl 源 2020 年第 1–2 期窗口实跑背书。*
