# 澳大利亚（AUS）数据源说明——frl（联邦立法登记册 FRL）

> 文中数量为真实运行的实测参考值；你运行时的产出取决于所选窗口。
> 阅读前提：了解仓库根目录 `python cli.py` 的用法即可，不需要读代码。
> 本文是 frl 单源的说明；澳大利亚全部源的总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：FRL 是什么、装了谁的产出

**FRL**（Federal Register of Legislation，联邦立法登记册，[legislation.gov.au](https://www.legislation.gov.au)，联邦司法部运营）是澳大利亚**联邦层级立法的官方登记册**——Acts（法律）、legislative instruments（立法文书）、notifiable instruments（可告知文书）只有登记在此才可查询与引用。澳大利亚宪法体制下联邦与各州分权立法，本源**只覆盖联邦单一层**（州立法在各州自己的登记册）。

一个关键概念是**"标题"（title）**：一部 Act 或一份文书在登记册里是一个持久条目（稳定 id 如 `C2004A00485`），它的**版本谱系**挂在标题之下——每个版本是文本在某个时间点效力窗口内的形态。版本分三种：

| 版本种类 | 标记 | 有无全文 | 语义 |
|---|---|---|---|
| as-made（颁布原样版） | `compilationNumber=0` | 有 | 制定当日的原样文本 |
| compilation（编纂版） | `compilationNumber=N` | 有 | 把已生效修订编入后的官方权威文本，每编一次 N 递增 |
| 修订标记时点 | `compilationNumber=null` | **无** | 修订已生效但尚未编纂的空窗 |

登记册的日常节奏是**登记事件流**：每个版本都带 `registeredAt`（登记时间戳），工作日每天约 19–33 个事件（2026-08-25 至 2026-08-28 六日实测），主体是新标题的 as-made 登记，另有少量新编纂版；周六可为 0、周日约 1。

覆盖范围与体量（2026-08-31 实测，132,129 个标题）：

| collection | 标题数 | 说明 |
|---|---|---|
| LegislativeInstrument | 94,679 | 立法文书（含历代 SR/SLI 编号系列） |
| Gazette | 18,587 | 联邦公报（周期性出版物，非政策文书） |
| Act | 13,732 | 联邦法律，1901 年起全量（含已废止） |
| NotifiableInstrument | 4,669 | 可告知文书（2016 年制度设立后） |
| ContinuedLaw / Prerogative / AAO / Constitution | 274 / 164 / 36 / 1 | 边角小类（继续适用的领地法、特权文书、行政安排令、宪法） |

全部标题合计约 79 万份可下载文件（Word/PDF/EPUB 三格式合计；EPUB 与 PDF 为常用两种）。

### 1.2 数据通道：官方 OData API（免 key、无浏览器）

网站改版（2023 年）后的 legislation.gov.au 没有公开的 API 文档页，但**网站前端自己就在调用一个完整的 OData v4 接口**——`https://api.prod.legislation.gov.au/v1`（网页源码内嵌的取数地址全部指向它，/About、/Latest、/Series 三页 2026-08-31 验证一致）。本源走这个接口：免 key、无会话、无 cookie、无反爬迹象（2026-08-31 连续约 60 个冷请求零失败）。

实体模型是规整的三层：**Titles（标题台账）→ Versions（版本谱系）→ Documents（格式文件清单）**，文件本体经 `documents/find(...)` 函数端点取得——该端点对部分标题返回 JSON 信封（`bytes` 字段是 base64 编码的完整文件，实测解码后字节数与元数据 `sizeInBytes` 逐一吻合），对另一部分标题直接流裸文件字节（两种形状并存且请求头无法强制选择，解析按响应首字节分流）。

### 1.3 版本口径：两层都抓

一部法律的 as-made 与编纂版研究语义不同——前者回答"政府在日期 X 制定了什么"（事件口径），后者回答"此刻有效的是什么"（现行口径）。本源**分层入账，两层都抓**：

- **as-made 层（无条件抓）**：每个标题的颁布原样版（EPUB，无 EPUB 时 PDF 兜底）；文书类（instruments）另抓 **ES（Explanatory Statement，解释声明）**——文书类唯一的官方政策理由文件；
- **编纂锚点层（默认抓）**：每个标题最新有全文的编纂版（现行有效文本的官方权威编纂）；
- **编纂全史层（参数 `comp=all` 才抓）**：该标题全部历史编纂版。

修订标记时点在源站本就没有全文，只入版本谱系表、不产生文档。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 不需要（无 cookie、无令牌） |
| 限额 | 无公开限额；分页单页上限 100 条（`$top` 超限报错并明示），框架统一限速（0.5–1 秒/请求）足够安全 |
| 反爬 | 无（python urllib 默认指纹直连实测通过） |
| 响应格式 | 全部 JSON（UTF-8）；文件下载端点返回 JSON 信封内嵌 base64 |
| 单响应大小 | 文件下载响应约 0.3–1 MB（文件越大信封越大，base64 膨胀约 33%） |

## 3. 抓什么：任务类型清单

每种任务 = 一次请求 + 一次解析。共 **4 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `frl_day`（种子） | `Versions` 实体集，`registeredAt` 落在当日 00:00–23:59 的版本（`$top=100` 翻页） | 当日登记事件的标题去重清单 → 每标题一个 `frl_title`（携带最新登记时间作更新信号）；当日无事件（周末）= 合法空产出；推进日期游标 |
| `frl_title` | `Titles('{id}')?$expand=versions` | 标题台账一行 + 版本谱系整组重写（titles / title_versions 两表）；派生 `frl_docs` |
| `frl_docs` | `Documents?$filter=titleId eq '{id}'` | 该标题全部可下载文件清单 → 按版本口径筛选（as-made + ES + 最新编纂，或 `comp=all` 全部编纂）→ 每份文件一个 `frl_doc` |
| `frl_doc` | `documents/find(titleid='{id}',asat={版本生效日},type=...,format=...)` | 响应嗅探（JSON 信封 → base64 解码；裸流 → 直接收文件）+ ZIP/PDF 魔数校验 → 文件落盘 + documents 一行（挂靠标题实体） |

任务链：`frl_day → frl_title → frl_docs → frl_doc`。一请求 = 一份完整文件（内容内联在响应里，无第二跳）。

命令行参数（key=value 形式）：

```
window=FROM:TO    登记日闭区间，如 2026-08-27:2026-08-28（必填，或改用 sync=1）
sync=1            增量：起点 = 游标 frl_last_date 的次日，终点 = 今天
max_titles=N      每个登记日实际深抓的标题数上限（测试护栏）
comp=anchor|all   编纂层口径（默认 anchor = 只抓最新编纂版；all = 全部历史编纂版）
gazette=0|1       公报是否下载正文（默认 0：标题台账保留公报条目，正文不下载）
```

## 4. 数据落到哪

**两张领域表 + documents 表 + 每标题一个文件夹**。与"扁平文档型"国家（法国/德国公报）不同，登记册的条目不是一次性出版物而是**持续演化的实体**：一部法的 as-made 与第 69 号编纂版是同一标题的两个时点，因此建立标题实体，全部版本文档挂靠其下。

| 位置 | 记什么 |
|---|---|
| `titles` 表 | 标题台账一行：稳定 id、名称、collection、状态（InForce/Ceased/Repealed/NeverEffective）、制定日、是否主体法、年/号/系列、现行版本指针、**废止链（status_history：谁在何日以何条款废止了它）** |
| `title_versions` 表 | 版本谱系：一版本一行（标题 id + 生效窗口起点为主键），编纂号、登记时间、是否现行/最新、**修订影响注记（reasons：哪部修订法哪些条款促成了这个时点）** |
| `documents` 表 | 一份文件一行：as-made、ES、编纂版都是文档，`entity_ref='titles:{title_id}'` 挂靠标题 |
| `01_raw/frl/{id 前两位}/{title_id}/` | 该标题的全部材料（人读镜像，路径入账） |

documents 主要字段：

| 列 | as-made / ES 文档 | 编纂版文档 |
|---|---|---|
| `title` | 标题名称（ES 加 " — Explanatory Statement"） | 标题名称 + 编纂号 |
| `publication_date` | 标题的**制定日**（makingDate） | 版本的**生效窗口起点**（该文本形态开始有效的日期） |
| `source_url` | `…/{title_id}/asmade/{生效日}/text/original/{格式}`（ES 为 `text/es`） | `…/{title_id}/latest/{生效日}/text/original/{格式}` |
| `raw_format` / `language` | `epub`（PDF 兜底时 `pdf`）/ `eng` | 同左 |
| `doc_type` | Act→`STATUTE`；LegislativeInstrument/NotifiableInstrument→`SECONDARY_LEGISLATION`；其余软映射，原词在 meta | 同左（ES 为 `OTHER`） |
| `meta` | `title_id`、`version_start`、`compilation_number`、`doc_kind`（primary/es）、`registered_at`、`making_date`、`is_authorised`、`size_in_bytes`、`series`、`status_history`（仅 as-made） | 同左 |

> 为什么 publication_date 不用登记时间戳：1901 年的老法是 2005–2013 年间批量回迁登记的（`asMadeRegisteredAt=2013-01-22` 一类），拿它当发布日会把百年前的立法事件搬到 2013 年的研究时间轴上；制定日与版本生效日才是内容自身的法律日期，登记时间戳保留在 meta 与谱系表里。

文件夹布局（真实示例，EPBC Act 1999）：

```
01_raw/frl/C2/C2004A00485/
├── title.json                    ← 标题元数据 + 全部版本谱系（原始响应）
├── asmade/
│   └── C2004A00485.epub          ← 1999 年颁布原样版（309,939 B）
└── comp069_2026-07-01.epub       ← 第 69 号编纂版（生效窗口 2026-07-01 起，687,238 B）
```

## 5. 完整案例走查

一个真实标题的全链数据（2026-08-31 库内实值，每步可复查）：

**F2022L00347 — Higher Education Support (Other Grants) Guidelines 2022**（立法文书，教育部 2022 年制定、2026 年 8 月修订）：

1. **发现**：2026-08-27 登记流出现它的新版本事件（第 20 号编纂注册）→ 生成标题任务；
2. **谱系**：`Titles('F2022L00347')?$expand=versions` 一次返回标题元数据 + **22 个版本**（2022 制定 → 历次修订/编纂 → 2026-08-18 第 20 号编纂 → 2026-08-18 起的现行窗口），整组写入 `title_versions`（22 行），标题行记录现行锚点 2026-08-18；
3. **口径选择**：as-made 版（2022-03-17 生效窗口）+ 其 ES + 最新编纂版（comp 20，start 2026-08-18）三个版本进入下载，其余 19 个历史编纂版按默认口径跳过（`comp=all` 可全取）；
4. **下载**：三个文件全部 EPUB 落盘，documents 三行全部 `entity_ref='titles:F2022L00347'`：

| doc_id | publication_date | 大小 | 文件 |
|---|---|---|---|
| `AUS_20220317_5ccf2145` | 2022-03-17（制定日） | 111,210 B | `01_raw/frl/F2/F2022L00347/asmade/F2022L00347.epub` |
| `AUS_20220317_3d5f3bf5` | 2022-03-17 | 15,910 B | `…/asmade/F2022L00347ES.epub`（解释声明） |
| `AUS_20260818_01681b4f` | 2026-08-18（编纂生效日） | 157,499 B | `…/comp020_2026-08-18.epub` |

同一文件夹里另有 `title.json`（标题+谱系原始响应快照）。窗口合计（2026-08-27 至 08-28 两日 + 08-27 无上限日 + 追sync）：**200 任务全部完成、68 个标题（Act 12 / LegislativeInstrument 19 / NotifiableInstrument 23 / Gazette 14〔仅台账〕）、351 行版本谱系、69 份文档（55 正文 + 14 解释声明，全部 EPUB）、磁盘文件与账本逐一哈希吻合**；重复运行同窗口零请求。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country aus --source frl window=2026-08-27:2026-08-28 max_titles=5 --dry-run

# 小窗口真实抓取（两天登记流，每日至多 5 个标题深抓）
python cli.py collect --country aus --source frl window=2026-08-27:2026-08-28 max_titles=5

# 每日增量（从上次游标追到今天）
python cli.py collect --country aus --source frl sync=1

# 状态 / 快照 / 修复
python cli.py status --country aus --source frl
python cli.py export --country aus
python cli.py requeue --country aus
```

## 7. 更新与增量

- **日期游标 `frl_last_date`**：每个 `frl_day` 完成**自己那一天**才把游标推到该日——中途崩溃不会跳过未完成的日期。当日无登记事件（周末）也照推：完整扫完的空窗口同样代表"该日已确认无事件"；
- **登记事件流覆盖一切更新形态**：新标题登记、既有标题新编纂、修订标记时点，全是 `Versions` 上的登记事件，按日窗口一网打尽，不需要另外的重访机制；
- **重开规则**：`frl_title` 携带该标题最新登记时间作更新信号——已完成的标题任务只有信号变新才重开（重读谱系 + 自动补抓新出现的编纂版）；`frl_docs` / `frl_doc` 无信号、已完成即跳过，重复运行同一窗口近零成本；
- 往更早日期开窗口即历史回填，游标回拉幂等无害。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **`asat` 只认具体日期** | 下载端点的 asat 参数给 `AsMade`/`Current`/`Latest` 等枚举名会 404（元数据里有这些枚举但函数不认）；必须给具体日期，本源用版本自身的生效日精确命中 |
| **"已修未编"窗口无全文** | 当前处于修订标记时点（修订生效、尚未编纂）的标题，其现行窗口内取不到任何全文——这是源站数据形态不是缺陷；抓取以最新**有全文**的编纂版为锚点。**注意**：用"今天的日期"去取任何标题都会在这类窗口上 404，这正是本源坚持"先取清单、按版本生效日精确取"的原因 |
| **下载端点双形状** | 同一下载端点对部分标题返回 JSON 信封（base64 内嵌文件与元数据），对另一部分直接流裸文件字节——实测两种标题并存且请求头无法强制选择，解析按响应首字节嗅探分流；裸流路径的元数据相应少（无注册号文件名等，账目 meta 字段随之缺省） |
| **索引与下载服务偶发不一致** | 个别条目文件清单里有 EPUB/PDF，下载端点却 404（2026-08-31 实测 1 例）——源站索引先行、渲染缺位；任务如实记永久失败并在 failures/ 留档，重试通道（requeue）可后补 |
| 服务端 bug 清单 | ① `$count` 端点配 collection 过滤返回错误哨兵值（-9223372036854775808）——裸用或配 seriesType 正常，collection 过滤的普通查询自动附行内计数；② collection 过滤与 `$orderby` 组合报 400（seriesType 过滤无此问题）；③ 嵌套 `$expand` 报 400——版本与文档清单分两请求取；④ 单页行数上限 100（`$top` 超限报错并明示）；⑤ 单标题直取加 `$expand` 时再带 `$top` 报 400——单键请求不带分页参数 |
| 公报（Gazette） | 默认标题入账、正文不下载（`gazette=1` 开启）；公报是周期性出版物，不是政策文书 |
| Word 格式 | 不抓（EPUB/PDF 的衍生格式，无独立信息量） |
| 多卷大部头 | 少数大部头法律的 PDF 按卷拆分（volumeNumber>0）；EPUB 始终是整卷单文件，故 EPUB 优先策略不受影响；无 EPUB 只有多卷 PDF 的极端情形只取首卷并在 meta 标记 |
| ELI URL | 站点支持 ELI 形式（`/eli/A2004A85/...`）但未在账目中使用——正门 URL 已满足可重建要求，ELI 映射待研究需求 |
| 州与领地立法 | 不在本源（各州自己的登记册）；议会法案过程数据（bill → Act 之前）在 parlinfo.aph.gov.au，标题元数据里的 `originatingBillUri` 保留了跳转线索 |

## 9. 端点速查表

均位于 `https://api.prod.legislation.gov.au/v1` 下（全部 GET + JSON；分页 `$top`≤100 + `$skip`；过滤/投影/单层展开可用）：

| 用途 | 端点与参数 |
|---|---|
| 标题台账 | `/Titles`（`$filter=makingDate ge..le`、`$filter=seriesType eq 'Act'`、`$filter=id in ('A','B')` 批量、`$orderby`、`$select`） |
| 单标题 + 版本谱系 | `/Titles('{id}')?$expand=versions`（一请求拿全谱系；嵌套展开不可用） |
| 按日登记事件流 | `/Versions?$filter=registeredAt ge {日}T00:00:00 and registeredAt le {日}T23:59:59` |
| 某标题版本谱系 | `/Versions?$filter=titleId eq '{id}'` |
| 文件清单 | `/Documents?$filter=titleId eq '{id}' [and format eq 'Epub']`（唯一键 = 标题 + 生效日 + 纠正版 + 卷号 + 类型 + 格式） |
| 文件下载 | `/documents/find(titleid='{id}',asat={YYYY-MM-DD},type='Primary'\|'ES',format='Epub'\|'Pdf',uniqueTypeNumber=0,volumeNumber=0,rectificationVersionNumber=0)` → JSON 信封，`bytes` 字段 base64 |
| 计数 | `/Titles/$count`（裸用或配 seriesType；配 collection 过滤会返回错误哨兵值）；collection 过滤的普通查询自动附 `@odata.count` |

**源里还有但暂未用的**（每项 = 将来可加一种任务类型）：修订影响网络 `Affects`（谁修订/废止了谁，跨标题政策影响链）、主管部门 `Departments`（部委维度）、议会审查事件 `ParliamentaryScrutiny`（文书提交议会与驳回动议）、日落条款检索 `_FutureSunsetDateSearch`、时点检索 `_PointInTimeSearch`、全文检索 `_TextSearchContexts`、议会原法案链接（`originatingBillUri` → parlinfo.aph.gov.au）。

---

*更新日期：2026-08-31；数据快照：2026-08-31；数据由 window=2026-08-27:2026-08-28（max_titles=8）、window=2026-08-27:2026-08-27（无上限）与 sync=1 追跑实跑窗口背书（200 任务、68 标题、69 文档，磁盘≡账本逐文件哈希吻合，幂等重跑零请求）。*
