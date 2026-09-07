# 德国（DEU）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。
> 文件命名规则：`{iso3}/{source}-{lang}.md`（国家文件夹 + 语言后缀，lang ∈ zh/en）；九节写作结构见 [_template-zh.md](../_template-zh.md)。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `bgbl` | 联邦法律公报 Teil I **纸质时代（1949–2022）**：法律、法规、宪法法院判决主文、联邦总统令——官方数字档案，逐条目 PDF | bgbl.de（Bundesanzeiger Verlag 官方档案站，无需 key） | [bgbl-zh.md](./bgbl-zh.md) |
| `ebgbl` | 联邦法律公报 Teil I **电子版（2023 起）**：每件公布独立编号（主文 + 可选附件，PDF） | recht.bund.de（联邦司法部，无需 key、无会话） | [ebgbl-zh.md](./ebgbl-zh.md) |

两个源同属《联邦法律公报》Teil I 的两个时代，文件同树存放（`01_raw/bgbl/…`），`doc_id` 规则一致；按年份分界互锁（各源传越界年份会报错并指向对方）。

## 2. 共享访问准备

| 项 | 说明 |
|---|---|
| 数据目录 | `python cli.py init` 配置，或 `POLICY_DATA_ROOT` 环境变量；德国数据落在 `{data_root}/DEU_policy/` |
| 密钥 | **无需任何 key**，`.env` 不需要条目 |
| 通用命令习惯 | `collect`（key=value 传参）/ `status` / `export` / `requeue` / `reset`，全部在仓库根目录 `python cli.py` 运行 |
| 节奏 | 框架统一限速（默认 0.5–1 秒随机）+ 错误三分法重试；bgbl 源 PDF 端点需会话（任务链自动建立，无需人工介入）；ebgbl 源建议全量回填时 `--delay 3:5`（站方 robots 声明 `Crawl-delay: 30`） |

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| BGBl Teil II（国际条约与协定） | 两站均已探明同构（纸质 1951–2022 / 电子 2023 起），未开抓——开抓只需放开 part 过滤，见各源文档 §8 |
| 现行法整合文本（gesetze-im-internet） | 联邦司法部的现行法规汇编（XML 全文，机器可读的"现行整合文本"），未开工 |
| Bundesanzeiger（联邦公报） | 部分公告与法规全文的补充公布渠道，未开工 |
| 立法过程（法案/辩论/表决） | Bundestag（联邦议院）信息系统，未开工 |

---

*更新日期：2026-09-07；数据快照：2026-09-07；数据由 bgbl 源 2020 年第 1–2 期窗口实跑背书（ebgbl 源窗口背书见 [ebgbl-zh.md](./ebgbl-zh.md) §5）。*
