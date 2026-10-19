# 波兰（POL）数据源说明——isap（Dziennik Ustaw 法律公报）

> 文中数量与字节数为真实运行的实测值（实测日期随文标注）；你运行时的产出取决于所选窗口。
> 阅读前提：了解仓库根目录 `python cli.py` 的用法即可，不需要读代码。
> 波兰全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：Dziennik Ustaw 是什么

**Dziennik Ustaw**（简称 Dz.U.，法律公报）是波兰宪法规定的规范性文件法定公布刊物——法律（ustawa）、条例（rozporządzenie）、经批准的国际条约、宪法法院判决与**编纂文本（tekst jednolity，把已生效修订编入后的官方权威文本）**只有在此公布才进入施行程序。由众议院议长署名出版，2017 年起电子版即唯一法定版本。

术语先说明白：**ISAP**（Internetowy System Aktów Prawnych，波兰法律文书系统）是管理这套语料的本体系统，每个条目的内部编号（形如 `WDU20240000001`）就是它的编址；**ELI**（European Legislation Identifier，欧洲立法标识符）是条目的标准对外标识（形如 `DU/2024/1` = 出版方/年/位次）。本源数据走 **api.sejm.gov.pl**——众议院运营的官方 ELI API，覆盖 Dziennik Ustaw **97,808 件（1918–2026 全年份）**（2026-09-20 实测）。

三个需要知道的边界：

| 通道 | 状态（2026-09-20 实测） | 结论 |
|---|---|---|
| **api.sejm.gov.pl**（官方 ELI API） | 可达、免 key、OpenAPI 文档公开（"ELI for Polish acts" v1.0，2025-11-25 更新） | ✅ 本源唯一通道 |
| isap.sejm.gov.pl（ISAP 网页站） | Imperva WAF 全站 JS 挑战，robots.txt 对非搜索引擎全禁（`User-agent: * Disallow: /`） | 不可程序访问；语料与 API 同源，无需它 |
| dziennikustaw.gov.pl（电子公报门户） | 对部分网络不可路由（2026-09-20 实测，本机与海外出口均超时） | API 即其数据的机器镜像，无需它 |

**Monitor Polski**（M.P.，总理署名的第二刊）在同一 API 上同构可取，但只载非规范性政府文件（政府声明、任免等），无法规——本源不收（见 §8）。

### 1.2 数据形态：公报本体 + 原生版本谱系 + 修订关系图

公报性为本（一次公布 = 一条数据），但比典型公报富三档：

1. **日期齐全**：公布日（promulgation）、公告/签署日（announcementDate）、施行日（entryIntoForce）三个日期字段原生分开提供，另有数据变更时间戳（changeDate）。
2. **版本谱系原生**：每次编纂以一份**公告（Obwieszczenie，官方通告文书）**的形式出版——公告自己是 Dz.U. 的一个正式条目（有自己的位次与公布日），其 `text.pdf` 就是该版编纂全文，并回链原法。原法条目则通过引用类目 `Inf. o tekście jednolitym`（编纂文本信息）列出全部历次公告。
3. **修订关系图**：条目详情的 references 共九类（修改/被修改/废止/被废止/被视为废止/执行/编纂/引用/宪法法院裁定），跨 Dz.U./M.P. 两刊——原始字段随源照收（存在每条目的 act.json 里），建图留给分析阶段。

### 1.3 技术形态

纯 HTTP GET 的 JSON/HTML/PDF 接口：按年枚举一次响应拿全（无翻页），条目详情一次请求，正文 HTML/PDF 各一请求。响应头中的负载均衡 cookie 由传输层自动持有，不构成应用会话。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 零条目 |
| 会话 | 无应用级会话（负载均衡 cookie 由传输层自动处理） |
| 限额 | 无公开限额；`/eli/changes/acts` 不带必填参数会被负载均衡规则以 403 拒绝（2026-09-20 实测）——带 `since` 参数即正常。框架统一限速（0.5–1 秒/请求）实测零失败（2026-09-21/22 连续约 2,100 个请求） |
| 反爬 | API 无；isap.sejm.gov.pl 网页站有（勿用） |
| 响应格式 | 枚举/详情/变更流为 JSON；`text.html` 为 UTF-8 HTML；`text.pdf` 为二进制 PDF（实测 `%PDF-1.7`） |
| 网络受限环境 | 加代理：`HTTPS_PROXY=http://host:port python cli.py collect …` |

## 3. 抓什么：任务类型清单（6 种）

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `isap_year`（种子） | `GET /eli/acts/DU/{year}`——一年全部条目**一次响应拿全**（2024 年 1,984 件，实测 count = 全年最大位次） | 按公布日窗口过滤后，每条目生成一个 `isap_act` |
| `isap_changes`（种子） | `GET /eli/changes/acts?since={游标}&limit=100`——变更流，`offset` 为**行偏移**（2026-09-21 实测；按行数推进翻页） | 每个变更的 Dz.U. 条目一个 `isap_act`（携带 changeDate 作更新信号）；末页推进游标 |
| `isap_act` | `GET /eli/acts/DU/{y}/{p}`——条目详情 | `acts` 实体行 + 原始响应留档（act.json）；按文本策略生成 `isap_text` / `isap_pdf`；把 `Inf. o tekście jednolitym` 里的每份编纂公告递归为 `isap_act`（任务身份天然去重，跨入口自动汇合） |
| `isap_text` | `…/text.html`——正文 HTML（结构化文档体：h1 标题、h2 部分、条文结构；连 1995 年扫描期条目都有 OCR 版） | 主文件落盘（带 doc_id），文件名 `text.html` |
| `isap_pdf` | `…/text.pdf`——排版原件 PDF | 有 HTML 的条目作兄弟文件；无 HTML 的条目（如编纂公告，其详情 textHTML=false）作**主文件**并登记文档 |
| `isap_clean` | 本地读 `text.html`（不走网络） | 确定性纯文本（框架派生路径与台账），白名单容器 `body`，剔除源站残留的"Pokaż całość"界面行 |

**文本策略**（每个条目按其详情里的 textHTML/textPDF 标志决策）：有 HTML → HTML 主文件 + PDF 排版件；只有 PDF → PDF 主文件；两者皆无（极罕见）→ 只登记实体行并在结果里说明。编纂公告与 2026 年的多数新条目走 PDF 主文件（2026-09-21 实测：窗口内 24 件中 21 件无 HTML）。

命令行参数（key=value）：

```
year=2026            公报年份（1918–当前年），回溯/窗口入口
from=… to=…          可选，公布日闭区间（须落在 year 内；过滤口径进任务参数，放宽零清库）
max_acts=N           每次扫取实际深抓的条目数上限（测试护栏）
sync=1               增量：从 kv 游标 isap_last_change 起回放变更流（首次增量见 §7）
```

## 4. 数据落到哪

**一张实体表 `acts` + documents 表 + 每部法一个文件夹**。一法（ELI 不变）横跨颁布原样文档与历次编纂文档，是跨文档持久实体；编纂公告本身也是公报条目，所以 `acts` 一行一条目（颁布件与公告都在表里），文档经 `entity_ref` 挂靠——**颁布件指向自身，编纂文本指向原法**（版本研究轴：按 entity_ref 聚合原法即得全版本线）。

| 列（acts） | 内容 |
|---|---|
| `eli`（主键） | `DU/2024/1` 形式的稳定标识 |
| `address` | ISAP 内部编号 `WDU20240000001`（2012 前的编址把期号编进号码，如 `WDU19951540801` = 1995 年第 154 期第 801 位——故用 ELI 做主键） |
| `native_type` / `status` / `in_force` | 源站原生类型（约 45 种词表）、效力状态（15 种词表，如 obowiązujący=现行有效、uchylony=已废止）、施行状态 |
| `promulgation` / `announcement_date` / `entry_into_force` / `change_date` | 公布日 / 公告日 / 施行日 / 数据变更时间戳 |
| `released_by` / `keywords` | 发布机关、主题词（JSON 数组） |
| `raw_path` | act.json 路径（九类修订关系图的原始留档） |

documents 主要字段：

| 列 | 内容 |
|---|---|
| `doc_id` | `POL_{公布日 YYYYMMDD}_{hash8(source_url)}`（无公布日的一次性文书落在 00000000 日期段，实测存在：Dz.U. 2024 poz. 1723） |
| `source_url` | 条目规范地址 `https://api.sejm.gov.pl/eli/acts/DU/{year}/{pos}`（可重建；取条目级而非文件级，格式策略变化不换 doc_id） |
| `publication_date` | 公布日（研究时间轴）；公告日/施行日/变更时间戳在 meta |
| `doc_type` | 软映射（Ustawa→STATUTE、Rozporządzenie→SECONDARY_LEGISLATION、Dekret→DECREE，其余 OTHER）；原词永存 `meta.native_type` |
| `entity_ref` | 颁布件 `acts:{自身 ELI}`；编纂文本 `acts:{原法 ELI}` |
| `meta` | `doc_kind`（enacted/consolidation）、`consolidation_of`、`native_status`、`keywords`、`text_types`、`files`（兄弟文件）等 |

文件夹布局（一法一夹，`01_raw/isap/` 顶层 = 源名）：

```
{data_root}/POL_policy/
├── state.db
├── 02_cleaned/{sha256(doc_id) 前 2 位}/{doc_id}.txt   ← 框架派生
└── 01_raw/isap/DU/2024/0001/
    ├── act.json                 ← 条目详情原始响应（含九类修订关系图）
    ├── text.html                ← 颁布原样正文 HTML（主文件）
    └── text.pdf                 ← 排版原件 PDF（兄弟文件）
```

## 5. 完整案例走查（库内实值，2026-09-21/22 实跑）

**DU/2024/1 —— 国防部长海外服役津贴条例**（2024-01-02 公布）：

1. **发现**：`year=2024 from=2024-01-02 to=2024-01-02` 窗口命中 4 件（含它）；
2. **实体行**：`acts` 一行，`eli=DU/2024/1`，`native_type=Rozporządzenie`，`status="akt posiada tekst jednolity"`（拥有编纂文本），`entry_into_force=2024-01-17`；
3. **颁布文档**：`text.html` 125,753 字节（实测，与 API 响应逐字节一致）落 `01_raw/isap/DU/2024/0001/`，`text.pdf` 270,714 字节作排版件；doc_id `POL_20240102_aff824a1`，entity_ref 指向自身；
4. **版本链自动展开**：详情引用 `Inf. o tekście jednolitym → DU/2025/803`，采集自动去取那份公告——**国防部长 2025-06-23 公布的编纂公告**，其 `text.pdf` 229,521 字节即新编纂全文，登记为文档 `POL_20250623_58c3073d`，**entity_ref 指向 `acts:DU/2024/1`**；
5. **版本查询**：`SELECT * FROM documents WHERE entity_ref='acts:DU/2024/1'` 一次返回颁布 HTML + 编纂 PDF 两行——一部法的两个文本状态。

**DU/2026/1226 —— 跨 29 年的版本链**：增量变更流发现 1997 年的《政府行政部门法》 被触碰（changeDate 2026-09-21），其详情拉出 2026-09-18 公布的最新编纂公告，登记为 `POL_20260918_f12f1bd1`（PDF 主载体，376,039 字节），entity_ref = `acts:DU/1997/943`。

**窗口合计**（2026-09-21/22 实跑）：2026-09-14..20 窗口 24 件 + 2024-01-02 窗口 4 件 + 增量变更流回放 223 个变更——合计 **564 部法、564 份文档（467 份 HTML + 97 份 PDF）、1,595 个原始文件、467 份已清理纯文本**；57 部法拥有 ≥2 个文本状态（共 468 份文档），全部任务零失败。三方对账：564 份文档 sha256 与磁盘逐一吻合、盘上文件零孤儿、两个窗口的条目多重集与 API 逐一相同；重复运行增量近乎零请求（见 §7）。

## 6. 怎么跑

```bash
# 演练（不入队执行，看计划）
python cli.py collect --country pol --source isap year=2026 from=2026-09-14 to=2026-09-20 --dry-run

# 小窗口试跑（上节案例的实际命令）
python cli.py collect --country pol --source isap year=2026 from=2026-09-14 to=2026-09-20

# 全年（先试 max_acts=20 观察量级）
python cli.py collect --country pol --source isap year=2024

# 增量（见 §7）
python cli.py collect --country pol --source isap sync=1

# 清理为纯文本 / 状态 / 快照 / 修复
python cli.py clean --country pol --source isap
python cli.py status --country pol --source isap
python cli.py export --country pol
python cli.py requeue --country pol
```

## 7. 更新与增量

- **双入口一漏斗**：`year=` 是回溯/窗口入口（年清单一次拿全，窗口口径在任务参数里，放宽零清库）；`sync=1` 是增量入口（变更流）。两个入口生成的条目任务身份相同，自动去重汇合。
- **游标 `isap_last_change`**：变更流的 changeDate 水位线。`sync` 从游标起翻页回放（每页 100 行、按行偏移推进），**翻尽才推进**游标到本批最大 changeDate；变更条目携带 changeDate 作信号——已完成的条目只有被源站再次修改才重开（重读详情、自动补抓新出现的编纂公告），下游文本任务无信号、完成即跳过，重复运行近乎零成本（2026-09-22 实测复跑：1 个任务、零新增）。
- **首次增量**：先跑一个 `year=` 窗口建立基线，再把 kv 游标对齐到当前（一条 sqlite 语句：`INSERT INTO kv(key,value) VALUES('isap_last_change','<当前UTC时间T00:00:00>') ON CONFLICT(key) DO UPDATE SET value=excluded.value`——写入 state.db）。
- 修订与编纂的到达都体现为 changeDate 变化 → 原法重开 → 新编纂公告自动入队，无需独立重访机制。

## 8. 已知边界与缺口

| 项 | 说明 |
|---|---|
| **HTML 覆盖不均** | 条目是否有 text.html 以其**详情**的 textHTML 标志为准；2026 年 9 月中旬窗口 24 件中 21 件无 HTML（PDF 主载体），而 2024/1 有 125,753 字节 HTML——不要从年份外推。无 HTML 条目的 `text.html` 端点返回 **200 + 空字节**（不是 404），采集按标志门控不会踩到 |
| **无公布日的条目** | 极少数"一次性文书"（公布前已废止，如 Dz.U. 2024 poz. 1723）连详情都没有公布日——文档落在 00000000 日期段，meta 里 announcement_date 为空 |
| **texts 类型码 T** | 详情的 texts 清单类型码 T/O/U/H/I 中 T 未完全定标（2026-09-21 实测它与 U 成对出现在 2026 年条目的编纂变体文件上：`D20260001L.pdf`(T) 与 `D20260001Lj.pdf`(U)）；采集只取 text.html/text.pdf 端点，类型码仅留档 |
| Monitor Polski 不收 | M.P. 只载非规范性政府文件；同 API 同构，将来需要时另立一源（零框架改动） |
| 深历史年份 | 1918–1989 可枚举，未逐年核验文本覆盖与质量；全量回填时逐窗口验收 |
| 清理两处已知观感 | ① h1 内多个 span 连排（"…Narodowejz dnia…"），是行内标签拼接的确定性结果；② 极少数条目正文极短。清理规则升级走版本机制（v+1 全量重清） |
| 负载均衡 403 | `/eli/changes/acts` 不带 since 参数必 403（规则拒绝，非鉴权）；传输层重试语义覆盖偶发 403 |
| 网络可达性 | 波兰部分政府站点（dziennikustaw.gov.pl、dane.gov.pl）对部分网络不可路由；api.sejm.gov.pl 全球可达，不通时走 HTTPS_PROXY |

## 9. 端点速查表

均在 `https://api.sejm.gov.pl/eli` 下（全部 GET；OpenAPI 定义见 `/eli/openapi/`，Swagger UI 见 `/eli/openapi/ui/`）：

| 用途 | 端点 |
|---|---|
| 出版方清单 | `/acts`（DU=97,808 件 1918–2026；MP=66,655 件 1930–2026） |
| 按年枚举（无翻页） | `/acts/{publisher}/{year}` |
| 分册枚举 | `/acts/{publisher}/{year}/volumes[/{volume}]` |
| 条目详情 | `/acts/{publisher}/{year}/{position}` |
| 引用关系 | `/acts/{publisher}/{year}/{position}/references` |
| 条目结构（篇章条文） | `/acts/{publisher}/{year}/{position}/struct` |
| 正文 HTML / PDF | `/acts/{publisher}/{year}/{position}/text.html` · `…/text.pdf` |
| 清单内具名文件 | `/acts/{publisher}/{year}/{position}/text/{type}/{fileName}` |
| 变更流（增量） | `/changes/acts?since={ISO时间戳}&limit=100&offset={行偏移}` |
| 词表 | `/types` · `/statuses` · `/institutions` · `/keywords` · `/references` |
| 检索 | `/acts/search` · `/titles` |

**源里还有但暂未用的**：分册编址端点（早年逐册枚举，按年枚举已覆盖）；`struct` 篇章结构（条文级定位，条款研究可用）；`/titles`/`/acts/search` 检索（主题发现）；`/keywords`/`/institutions` 词表（提取阶段对齐）。

---

*更新日期：2026-09-22；数据快照：2026-09-21；数据由 2026 年 9 月 14–20 日窗口 + 2024-01-02 窗口 + 增量变更流实跑背书（564 部法、564 份文档、1,595 个原始文件零孤儿，账本≡磁盘≡API 三方对账通过，幂等复跑零新增）。*
