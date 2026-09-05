# 英国（GBR）数据源说明——leg（legislation.gov.uk 官方法律数据库）

> 数据快照日期：2026-09-03。文中状态码、字节数与计数均为当日对源站直连实测的真实值（可重放复核）。
> 阅读前提：了解仓库根目录 `python cli.py` 的用法即可，不需要读代码。英国全部源的总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：legislation.gov.uk 是什么、装了谁的产出

**legislation.gov.uk** 是英国国家档案馆（The National Archives，TNA）运营的官方法律数据库——英国（联合王国层级）的法律（Acts of Parliament）与法定文书（Statutory Instruments，二级立法，即部长/政府部门依据法律授权制定的法规）在此官方发布；数据库同时回溯收录历史立法（元数据早至 1235 年）。

一个对使用很重要的设计：这个站**没有独立的 API 主机——整个网站本身就是 API**。任何页面的地址后缀换成 `/data.xml` 即得结构化文档（CLML，Crown Legislation Markup Language，官方法律标记语言），列表页后缀 `/data.feed` 即得 Atom 格式清单。本源正是走这条官方通道（官方数据复用文档：legislation.github.io/data-documentation）。

本源抓的是**颁布原样版**（as-enacted / as-made）：一部法律/文书**通过或制定当天的原始全文**——这正是"政府在日期 X 出台了什么政策"的时间序列研究所需要的文本形态。现行有效版（编入后续修订的版本）由另一源（lex，规划中）整包补齐。

### 1.2 类型与覆盖

站的类型体系有 34 种（王国/地方/历史/欧盟类型等）。本源默认只收**联合王国层级**的两类：`ukpga`（UK 公共一般法）与 `uksi`（UK 法定文书）；参数 `types` 可放宽（见 §3）。苏格兰、威尔士、北爱尔兰地方立法类型（asp/ssi/wsi/nia 等）默认排除。

一个实测坑：**uksi 的年表清单里会混入 wsi（威尔士文书）条目**——两者共用同一编号系列（2024 年清单第一页首条即 wsi/2024/1395，2026-09-03 实测）。过滤在清单解析层按条目地址的类型段执行，混入者不入账。

覆盖事实（官方说明 + 2026-09-03 实测）：ukpga 1988 年起全部有 XML；uksi 1987 年起全量，**地方性（L 系列）与非印刷件自 2011 年起只有印刷 PDF、无 XML**（这些条目请求 data.xml 返回 404，本源记为"无 XML 版"边界）；个别编号在源站本身就不存在（2023 年 1,442 个编号中 45 个 404，实测为未刊/撤回件）。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| User-Agent | **必须自报身份**（公平使用政策明文要求带联系方式），国家包内已固定 |
| 限速 | 站方 robots.txt（2026-09-03 实测）要求 **Crawl-delay: 5 秒**；另限额 3,000 请求/5 分钟。运行时用 `--delay 5:7` |
| 禁爬 | robots.txt 禁 `*/data.pdf` 与 `*/data.docx`——本源只取 XML，印刷 PDF 链接仅记录不下载 |
| 防护 | 站点前方有商业防护服务，按连接指纹选择性拦截：命令行工具 curl 会被挡（HTTP 202 挑战页），**Python requests 库与真实浏览器实测通过**（2026-09-03 多端点验证）；若运行中撞上限流页（HTTP 438）或封禁页（437），任务会记为可重试失败，用修复通道重跑即可 |
| 响应格式 | 全部 XML（UTF-8）；单件 35 KB（小型文书）至 2 MB（大型法案） |

## 3. 抓什么：任务类型清单

每种任务 = 一次请求 + 一次解析。共 **2 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `leg_list`（种子，每类型×年份×页一个） | `/{type}/{year}/data.feed`（每页 100 条，Atom） | 该页条目清单 → 范围内每件派生一个 `leg_enacted`；页内有"下一页"链接则续页；全部条目元数据先落 `items` 表 |
| `leg_enacted` | `/{type}/{year}/{number}/enacted（法）或 made（文书）/data.xml` | 一个文档记录 + CLML 全文原样落盘 + `items` 行补齐；**404 且响应体为已知错误页 → 记"无 XML 版"合法空**（PDF-only 件），未知 404 形状报错升级 |

任务链：`leg_list × 每类型每年（自动翻页）→ leg_enacted × 每件`。

命令行参数（key=value 形式）：

```
years=2000:2026    制定年闭区间（必填；或 year=2023 单年）
types=core         core = ukpga+uksi（默认）；可写逗号列表如 ukpga,uksi,ukcm
refresh={时间戳}    强制重走全部年表清单（增量用，见 §7）
```

## 4. 数据落到哪

**一张领域表 + documents 表 + 每件一个文件夹**。

| 位置 | 记什么 |
|---|---|
| `items` 表 | 一件法规一行：规范键（如 `uksi/2012/215`）、题名、原生类型、年、号、**制定日 / 提交日 / 施行日**（日期三件套）、站点更新戳、有无 XML、条款数、文件路径；另有一批预留列供 lex 源（规划中）补现行版信息——两源汇于同一张表，无迁移 |
| `documents` 表 | 一件一个文档：题名、制定日（publication_date）、类型、规范地址、语言（eng）、CLML 元数据全量入 meta |
| `01_raw/leg/{type}/{year}/{number}/enacted/data.xml` | 颁布原样版 CLML 原样字节（或 `made/`，文书类） |

documents 主要字段（真实示例，Identity Cards Act 2006，2006-03-30 制定）：

| 列 | 值 |
|---|---|
| `doc_id` | `GBR_{制定日}_{地址哈希8位}` |
| `publication_date` | 2006-03-30（法的 `EnactmentDate`；文书用签署日 `DateSigned`） |
| `doc_type` | ukpga→`STATUTE`；uksi→`SECONDARY_LEGISLATION`（站点原生类型词永存 meta） |
| `entity_ref` | `items:ukpga/2006/15` |
| `meta` | 站点元数据原生字段全量：ISBN、替代编号、主题、出版者、修改日、**提交日与施行日**（导言块的 LaidDate / ComingIntoForce，人类文本原样保留）、印刷 PDF 链接（不下载）、条款数 |

## 5. 完整案例走查（2023 年公共一般法，2026-09-03 实跑库内实值）

1. **枚举**：`GET /ukpga/2023/data.feed` → 一页收齐 57 部 → 57 个 `leg_enacted` 任务；
2. **全文**：57 件全部 200（该年无 PDF-only 件），CLML 原样落盘；合计 **58 任务零失败、57 文档、57 items 行、30 MB**；
3. **样子**：最大一件 Economic Crime and Corporate Transparency Act 2023（2023-10-26 制定）——2,035,642 字节、773 条款；最小一件 National Insurance Contributions (Reduction in Rates) Act 2023（2023-12-18 制定）——35,888 字节、10 条款；
4. **时间轴**：57 部制定日覆盖 2023-01-10 至 2023-12-18 全年——按年聚合即为"2023 年英国出台了哪些法律"的完整序列；
5. **重复运行**同年同类型 → 零请求（任务确定性跳过）。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country gbr --source leg years=2020:2020 --dry-run

# 某一年真实抓取（如 2023 年全部法律与文书）
python cli.py collect --country gbr --source leg year=2023

# 大窗口批量（务必带 5 秒以上限速，遵守站点 robots）
python cli.py collect --country gbr --source leg years=2000:2026 --delay 5:7

# 状态 / 快照 / 修复
python cli.py status --country gbr --source leg
python cli.py export --country gbr
python cli.py requeue --country gbr
```

## 7. 更新与增量

- **枚举型源 = 参数化重开（refresh 模式）**：加 `refresh={时间戳}` 重跑同窗口，年表清单任务身份改变而强制重走；已完成的全文任务直接跳过，成本仅清单页数。清单条目携带站点更新戳作为信号——一件已抓过的法规只有在站点更新戳变新时才重开（如颁布更正），重开自动重取全文。
- 站点另有逐日发布日志（`/update/{日期}/…/data.feed`，2026-09-03 实测可用），适合日增量；本源暂未启用，需要时作为新任务类型加入。
- 源站无"删除"概念（极少见的撤回件在发布日志中可见）——重开重扫即对齐。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **PDF-only 件无 XML** | 2011 年起的地方性/非印刷文书只有印刷 PDF（robots 禁爬 PDF）；请求 data.xml 得 404，`items` 行记 `xml_available=0`，题名与编号仍在账（来自清单），PDF 链接在 meta 可后续按需人工补 |
| 未刊编号 | 个别编号源站本身 404（未刊/撤回），与上项同记 `xml_available=0` |
| 只收原样版 | 现行有效版文本与逐时点历史版本不在本源（现行版由 lex 源整包补；历史版本通道已验证可行，另批实施） |
| 语言 | 只收英文版（威尔士语变体不收——其规范类型本就在排除范围） |
| 地方与欧盟类型 | 苏格兰/威尔士/北爱尔兰立法与欧盟留存法默认排除（`types` 参数可放宽，放宽 = 新任务自动补抓、无需清库） |
| 修订关系 | 本源不抓修订效果明细（lex 源的修订台账与站点效果通道覆盖此需求） |
| 1988 年前 | ukpga 1988 年前仅部分有 XML（本源默认窗口 2000 年起，不受影响） |

## 9. 端点速查表

| 用途 | URL 模式 |
|---|---|
| 年表清单（枚举入口） | `GET https://www.legislation.gov.uk/{type}/{year}/data.feed?page=N&results-count=100` |
| 颁布原样版全文（法/文书） | `GET https://www.legislation.gov.uk/{type}/{year}/{number}/enacted\|made/data.xml` |
| 条目元数据子资源 | `GET …/{type}/{year}/{number}/resources/data.xml`（含前后版本链接，历史版本层将来用） |
| 逐日发布日志 | `GET https://www.legislation.gov.uk/update/{yyyy-mm-dd}/legislation/{type}/data.feed` |
| 修订效果清单 | `GET https://www.legislation.gov.uk/changes/affected/{type}/{year}/{number}/data.feed` |
| 时点历史版本 | `GET …/{type}/{year}/{number}/{yyyy-mm-dd}/data.xml` |
| 爬取政策 | `GET https://www.legislation.gov.uk/robots.txt`（Crawl-delay 5；禁 data.pdf/data.docx） |

**源里还有但暂未用的**：Explanatory Notes（解释说明，`/notes` 与导言链接）、impact assessments（影响评估）、逐时点版本全史、SPARQL 元数据端点（1235 年起题录）——每项 = 将来可加的任务类型。

---

*更新日期：2026-09-03；数据快照：2026-09-03；数据由 year=2023 types=ukpga 实跑背书（58 任务零失败 / 57 文档 30 MB / 磁盘≡账本路径一致 / 幂等重跑零请求），全窗口 years=2000:2026 抓取进行中。*
