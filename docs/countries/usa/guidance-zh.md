# 美国（USA）数据源说明——guidance（机构直发政策文件）

> 文中覆盖范围与结构特征为官方数据源的稳定属性（2026-08-31 探查实测）；各机构真实运行计数见 1.3 节对应文档的"实测"段。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。美国全部源总览见 [overview-zh.md](./overview-zh.md)。
> **每部门一份细节文档**（站点取证、解析细节、坑、命令）：见 1.3 节指针表。

## 1. 源概览

### 1.1 这一层是什么：行政系统的第三类文件

美国联邦政府的政策产出走三条渠道，前两条已建成：

```
立法渠道   bills 源        法案 → 两院表决 → 成法（congress.gov API）
规制渠道   regulations 源  规则草案 → 白宫审查 → FR 出版 → 生效（FR API + reginfo.gov）
机构直发   guidance 源     机构在自己官网上直接发布的政策文件 ← 本源
```

**机构直发**指：机构对法律/法规如何适用的官方解释（指引）、政策声明、程序说明、官方口径问答（Frequently Asked Questions，FAQ）、对下属机构的政策下达（directive/bulletin）、政府全域指引（管理与预算办公室〔Office of Management and Budget，OMB〕通告）。它们不经国会、也不在《联邦公报》（Federal Register，FR）走规制流程，**没有统一平台**——2019 年行政令（Executive Order，EO）13891 曾强制各机构建统一指引库，2021 年被撤销，门户随之大量下线；现状是机构自愿维护、质量参差、网址随换届流转。

这一层文件的法律性质是**非强制**（理论上不约束法院和公众），但实务影响巨大——食品药品监督管理局（FDA）的一份指引决定一个行业怎么申报，财政部海外资产控制办公室（OFAC）的一条问答决定制裁怎么执行。

### 1.2 范围口径

**抓**：官方解释、政策声明、程序指引、问答、directive/bulletin、技术标准类政策载体、OMB 通告/备忘录；**约束性法规和数据发布也照抓**（如国内收入公报〔Internal Revenue Bulletin，IRB〕里的财政部决定〔Treasury Decision，TD〕），靠 `doc_type` 标签供研究端筛——漏抓比多抓代价高。
**不抓**：国内收入局（Internal Revenue Service，IRS）个案裁定（letter ruling，不在公报渠道）、财政部金融犯罪执法网络（FinCEN）的 advisory 类。

### 1.3 机构清单与部门文档指针

| 机构 | 渠道形态 | 细节文档 |
|---|---|---|
| 财政部（IRS 公报 / OFAC 问答 / OCC 公告） | 公报型 / 站点地图型 / 站点地图型 | [guidance-treasury-zh.md](./guidance-treasury-zh.md) |
| 商务部（BIS 指引 / NWS 指令 / NIST 书目快照） | 清单型 / 编号树型 / 快照型 | [guidance-commerce-zh.md](./guidance-commerce-zh.md) |
| 环境保护署（EPA 指引门户） | 站点地图 + 三级分类 | [guidance-epa-zh.md](./guidance-epa-zh.md) |
| FDA / OMB / 其余 12 部 | 方法已验证（FDA 站点地图实测 3,643 指引页） | 后续机构 |

机构清单按**政策显著度**划线（非"是否内阁"）：15 部 + 内阁级独立机构起步，纯监管委员会后置。**每接触一个机构，第一个动作是查 `sitemap.xml`**——OFAC、EPA、FDA 三家连续验证"搜索墙"后几乎总有站点地图，全库可直接枚举，无需浏览器。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| 密钥 | **不需要**。已接渠道（irs.gov / ofac.treasury.gov / occ.gov / bis.doc.gov / weather.gov / epa.gov / github.com）全部开放访问 |
| 限额 | 均无公开限额；框架统一限速（0.5–1 秒/请求）；EPA 例外——有软限流（挂起不报错），见 EPA 文档坑四 |
| 反爬 | 均无。动态门户（FDA/EPA 搜索界面）以站点地图绕行，见 1.3 |

## 3. 抓什么：任务形态总表

一个源、机构即模块（`agency=` 参数路由）；八种任务形态覆盖全部已接渠道：

| 任务类型 | 形态 | 用在 |
|---|---|---|
| `gz_index` / `gz_issue` | 官报索引 → 期次 | IRS |
| `sitemap_page` | 站点地图一页 → 过滤 → 详情任务 | OFAC / OCC / EPA |
| `guid_page` | 一个文档详情页 → 行 + 附件任务 | OFAC / OCC / EPA |
| `pdf_listing` | 清单页直挂 PDF → 行 + 下载 | BIS / NWS |
| `index_page` | 索引页 → 子页任务 | NWS 系列索引 |
| `guid_file_dl` | 文件下载 → documents 入账 | 全部 |
| `nist_latest` | GitHub 接口查最新发布标签 | NIST |
| `nist_release_dl` | 一次发布快照：下载 + 归档 + 入库 | NIST |

命令行参数：`agency=irs|ofac|occ|bis|nws|epa|nist`（必填）、`window=FROM:TO`（IRS 期号窗口）、`year=YYYY`、`series=编号`（NWS 单系列）、`release=标签`（NIST 指定发布）、`max_pages=N` / `max_docs=N`（测试护栏，`max_docs` 是整链预算）。具体命令见各部门文档。

## 4. 数据落到哪

**一张 `guidance_documents` 表**（主键 = 机构+原生号；`native_type` 原文永存、`doc_type` 走受控词表、`status` 记 draft/final/withdrawn、EPA 专列 `page_class`）+ `documents` 表（正文文件一格式一档，`entity_ref` 回链）+ 一文档一文件夹 `01_raw/guidance/{部门}/{机构}/{年}/{原生号}/`（独立机构如 EPA 无部门段）；`department` 列随行入账。

**doc_type 打标五规则**：只映射源站官方原生字段，无原生类型一律 OTHER 绝不猜；通道标签 ≠ 语义标签；原生类型串永存（重打标 = 重推导，永不需要重抓）；映射是纯函数+单测；词表受控（`REGULATION / GUIDANCE / EXECUTIVE_ORDER / PRESIDENTIAL_DOCUMENT / BILL_TEXT / FAQ / BULLETIN / DIRECTIVE / STANDARD / CIRCULAR / MEMORANDUM / NEWS_RELEASE / OTHER`）。

## 5. 更新与增量

- **站点地图型**（OFAC/OCC/EPA）：重扫站点地图与新库比对即天然增量；
- **公报型**（IRS）：新期次即新任务；`window` 从上次期号续；
- **清单/树型**（BIS/NWS）：清单页重扫，URL 不变即跳过；
- **快照型**（NIST）：任务标识含发布标签，同标签重跑为无操作，每月新标签即新任务；
- **重推导**：doc_type 规则演进时重跑对应任务即可（原生类型串已存）。

## 6. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| 无统一平台 | 门户网址随换届流转；渠道模块按现状写，失效即修模块 |
| 灰区件 | 新闻稿、政策声明无原生类型——打通道标签不硬贴语义，研究端筛 |
| EPA 软限流 | 连续约 90–400 页后服务器挂起请求（不返 429）；须放慢节奏分段跑，见 EPA 文档坑四 |
| 历届覆盖 | 现任政府官网先行；archives.gov 历届存档后置 |

---

*更新日期：2026-09-01；数据快照：2026-08-31（探查实测）+ 2026-09-01（各渠道真实运行：合计 20,792 行 / 附件 1,091 份；EPA 页面余量分段推进中）；明细见各部门文档实测段。*
