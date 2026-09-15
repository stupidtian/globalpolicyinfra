# 奥地利（AUT）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。
> 文件命名规则：`{iso3}/{source}-{lang}.md`（国家文件夹 + 语言后缀，lang ∈ zh/en）。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `ris` | 联邦法律公报（Bundesgesetzblatt，BGBl）：2004 年至今的电子认证层 + 1945–2003 年扫描层 | RIS 官方开放数据 API（data.bka.gv.at，联邦总理府运营） | [ris-zh.md](./ris-zh.md) |

数据来源机构：RIS（Rechtsinformationssystem des Bundes，奥地利联邦法律信息系统，www.ris.bka.gv.at）由联邦总理府（Bundeskanzleramt，BKA）运营；本包不访问网页站，只访问其面向机器的开放数据 API（OGD RIS API），该 API 在奥地利开放数据门户 data.gv.at 上以"RIS Daten Version 2.6"登记。

## 1b. 三结构现状

- **时间序列**：`ris` 源承担，一行一次公布事件（公布日、发布机关、类型、德语标题、正文 XML 文件齐备）；生效日在公报层无结构化字段（长在条文里），如实记缺。
- **决策过程**：记缺。议会过程数据在奥地利议会（parlament.gv.at）的开放数据里，RIS 不提供，本包未采集。
- **版本序列**：记缺。现行法整合库（Bundesrecht konsolidiert）与条文级变更（History）在同一 API 上，通道已勘明可行，暂未纳入。

## 2. 共享访问准备

- 免 API key、免注册、免会话：`.env` 无需奥地利条目。
- 反爬边界：`www.ris.bka.gv.at` 网页站与 `ogd.ris.bka.gv.at` 的 HTML 页面（如 ELI 链接页）处于防护系统之后（2026-09-13 实测返回 503 人工验证页），**本包只访问 `data.bka.gv.at`（API 查询）与 `ogd.ris.bka.gv.at/Dokumente/`（文件下载）两条路径**，两者无防护。
- 命令习惯：一切从仓库根目录 `python cli.py collect --country aut --source ris …`；建议限速 `--delay 1:3`（实测连发未见限流，礼貌节奏仍按运营铁律执行）。

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| 州立法（Landesrecht） | 同一 API 有专用端点，未纳入（联邦层先行） |
| 现行法整合库（Bundesrecht konsolidiert） | 端点可用，未纳入；版本序列的候选通道 |
| 条文级变更（History） | 端点可用（含结构化生效/失效日期），未纳入 |
| 判例（Judikatur） | 同一 API 有专用端点，不在采集范围 |
| 帝国层公报 1848–1940（BgblAlt） | 端点可用但清单响应不带文件链接，形状不同，未纳入 |
| 议会过程数据 | 在奥地利议会开放数据，另立项目 |

---

*更新日期：2026-09-14；数据快照：2026-09-14（回填至当日，此后由 sync 增量接续）；数据由 2000–2026 全量真实采集背书（22,526 条）。*
