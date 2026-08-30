# 法国（FRA）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。
> 文件命名规则：`{iso3}/{source}-{lang}.md`（国家文件夹 + 语言后缀，lang ∈ zh/en）；九节写作结构见 [_template-zh.md](../_template-zh.md)。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `jorf` | 官方公报（JORF）"法律与法令"版：法律、条例、法令、部委令、公告——法国中央层级的全部成品规范（行政产出为主体，法律在颁布日刊出） | DILA 开放数据目录 echanges.dila.gouv.fr（免 key、无反爬、按日 tar.gz） | [jorf-zh.md](./jorf-zh.md) |

## 2. 共享访问准备

| 项 | 说明 |
|---|---|
| 数据目录 | `python cli.py init` 配置，或 `POLICY_DATA_ROOT` 环境变量；法国数据落在 `{data_root}/FRA_policy/` |
| 密钥 | **无需任何 key**，`.env` 不需要条目（Légifrance API 是备选通道，未使用，见 jorf-zh.md §8） |
| 通用命令习惯 | `collect`（key=value 传参）/ `status` / `export` / `requeue` / `reset`，全部在仓库根目录 `python cli.py` 运行 |
| 节奏 | 框架统一限速（请求间隔 0.5–1 秒随机）+ 错误三分法重试；JORF 每天一包（一期一请求），日常增量一两个请求即完成 |

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| 立法过程（法案/辩论/表决） | 国民议会与参议院系统（senat.fr 等），未开工 |
| 代码版库（codes 与法律现行版汇编） | Légifrance 的 LEGI 库，未开工 |
| 判例 | JADE/CASS 等，未开工 |
| 地方政府文件 | 省级令基本不登国家公报刊；协会公告在 JOAFE（另一数据集） |
| EU 法原文 | EU 条例直接生效、不经 JORF；需要时另立 EU 源 |

---

*更新日期：2026-08-28*
