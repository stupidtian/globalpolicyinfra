# 冰岛官方公报（Stjórnartíðindi）数据源说明

> 一个源一个文件。本文件说明冰岛官方公报源的结构、抓取方式与数据落点；国家总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

**Stjórnartíðindi**（"政府时报"，官方公报）是冰岛共和国的官方公布媒介：法律、行政条例与官方公告都在此公布，公布本身即产生法律效力。现行法定依据是 2005 年第 15 号法《官方公报与颁布令法》（Lög um Stjórnartíðindi og Lögbirtingablað nr. 15/2005）；958/2005 号条例进一步规定，公布的效力绑定公报**电子版**（www.stjornartidindi.is，今并入政府门户 island.is）——查公报原文即查法定文本。公报由总理府（Forsætisráðuneytið）辖下出版，工作日日更。

公报按内容分三个部门（deild）：

| 部门 | 刊登什么 | 现代实例（2025 年） |
|---|---|---|
| A deild | 议会通过的法律（LÖG）全文 + 总统确认令，另有个别公告 | 109 条（2026-09-17 查） |
| B deild | 部长条例（REGLUGERÐ）、收费表（GJALDSKRÁ）等行政法规，含地方市政条目 | 1,722 条（同日查） |
| C deild | 条约生效公告、任命等官方公告（含欧洲经济区 EEA 相关） | 少量 |

条目内部结构：每个公布事件一条记录，含发布机构（involvedParty，如 Utanríkisráðuneytið 外交部）、原生类型词（如 LÖG / REGLUGERÐ / GJALDSKRÁ）、公报编号（`{序号}/{卷年}`，如 107/2025）、签署日期、公布日期，正文以 HTML 内联并另有 PDF 版面原件（`https://adverts.stjornartidindi.is/{A|B|C}_nr_{序号}_{年}.pdf`）。

**数字化覆盖边界**（2026-09-17 实测）：API 覆盖 **2001 年起全部条目**（2001 年 1,223 条；2024 年 2,064 条）；**1995–2000 年为选择性数字化**（每年 21–48 条，全部是 C deild 的 EEA 类公告，且 HTML 只含刊期存根、正文只在 PDF）；更早年代（1878 年起）只有扫描件（timarit.is 等历史文库），无机器通道。

**关键日期语义**：`publicationDate` 字段对现代实时条目就是真实刊日（如 1011/2026 号 → 2026-09-16，与公报网站当日展示一致）；对回溯补录的历史条目则是**入系统日期**（如 1995 年第 43 号 → 2003-09-26 入库）。区分二者看 `createdDate`（入系统时刻）：补录条目的 createdDate 与 publicationDate 同为远晚于签署日的时刻。本源按公布事件原样记录这两个字段，口径见第 7 节。

**访问通道**：`https://api.stjornartidindi.is`（"The Official Journal of Iceland API"）——免 key、无会话、无反爬，提供完整 OpenAPI 3.0 规范（`GET /swagger` 可查）。正文内联在详情响应里，一个条目一个请求。

## 2. 访问准备

- **无需 API key**。所有端点匿名可读（2026-09-17 全部样本以无 cookie 的普通 HTTP 客户端取得）。
- 无需浏览器；无已知反爬。框架默认限速即可（源站为国家官方开放数据接口，建议保持 0.5–1 秒间隔的礼貌节奏）。
- 列表接口单页上限 **100 条**（pageSize 超传按 100 处理），翻页用 `page` 参数，`paging.totalPages/totalItems` 随响应返回。
- `.env` 无需为本源配置任何变量。

## 3. 抓什么：任务类型清单

| 任务类型 | 请求 | 产出 |
|---|---|---|
| `stjornartidindi_list` | `GET /api/v1/adverts-lean`（轻量列表，无正文）。两种枚举轴（进任务参数）：**公布日轴** `dateFrom=dateTo={日}&sortBy=publicationDate&direction=ASC`，逐日一个任务；**卷年轴** `year={年}&department={deild}&sortBy=publicationNumber&direction=ASC`，每（年，部门）一族、按页续接 | 每行一个 `stjornartidindi_advert` 种子（行内自带 id、刊号、发布机构、类型、公布时间）；日轴在当日完整消费后推进游标；空日 = 干净空单（说明后照常记完成） |
| `stjornartidindi_advert` | `GET /api/v1/adverts/{uuid}`（详情，正文内联） | 文档入账（documents 表一行）；`doc.html` 主文件 + `meta.json` 原始响应存档落盘；若 HTML 除刊期戳外无正文（1995–2000 代数字化的条目）则再派 `stjornartidindi_pdf` 兜底 |
| `stjornartidindi_pdf` | `GET` 详情里给出的 `pdfUrl` 直链 | `doc.pdf` 落盘（存根条目的唯一正文载体；现代条目不产生本任务） |

命令行入口（参数详见第 6 节）。

## 4. 数据落到哪

**零领域表**——公报型扁平源：一个公布事件 = documents 表一行，没有跨文档持久实体（修订引用如 "(6.) breytingu á reglugerð nr. 406/2010" 原样保留在标题里；修订关系建图属分析阶段）。

**文件夹布局**（顶层 = 源名；一层卷年、一层刊号文件夹，一个公布事件一个文件夹）：

```
{数据根}/ISL_policy/
└── 01_raw/stjornartidindi/
    └── 2025/                          ← 公报卷年（publicationNumber.year）
        ├── 0107-2025/                 ← 刊号（零补位），本例 107/2025 号法律
        │   ├── doc.html               ← 正文（主文件，file_hash 对应它）
        │   ├── meta.json              ← 详情 API 响应原样存档
        │   └── doc.pdf                ← 仅存根条目才有（1995–2000 代）
        └── 0108-2025/
            └── …
```

**documents 表承担**：全部书目字段（标题、公布日、发布机构、类型、语言 `isl`）+ 国家特色字段进 `meta`（签署日、入系统时间、部门、刊号、状态、类别、各 URL 等，见第 7 节）。`local_path` 指向 `doc.html`；`meta.json` / `doc.pdf` 的路径记在 `meta.files`。

**真实案例走查**（107/2025 号，2026-09-17 实测）：A deild 法律《LÖG um breytingu á lögum um úrvinnslugjald, nr. 162/2002…》（回收处理费法修正案），发布机构 Umhverfis-, orku- og loftslagsráðuneytið（环境、能源与气候部）；签署 2025-12-24，公布 2025-12-29；正文 HTML 约 214 万字符（颁布令 + 逐条修正文本），PDF 直链 `A_nr_107_2025.pdf`。抓取后：documents 一行（publication_date=2025-12-29，doc_type=STATUTE），文件夹 `01_raw/stjornartidindi/2025/0107-2025/` 内 doc.html + meta.json 两个文件。

## 5. 完整案例走查

以试跑窗口中的 **550/2026 号公告**（Kópavogsbær 科帕沃于尔市，规划事务公告，2026-05-29 刊）为例：

1. **发现**：日轴列表任务 `stjornartidindi_list(axis=pubdate, date=2026-05-29)` 命中 `GET /api/v1/adverts-lean?dateFrom=2026-05-29&dateTo=2026-05-29&sortBy=publicationDate&direction=ASC`，返回该日全部条目的轻量行；本条行内字段：`publicationNumber.full=550/2026`、`involvedParty.title=Kópavogsbær`、`department.slug=b-deild`、`publicationDate=2026-05-29T…`。
2. **scope 过滤**：Kópavogsbær（市镇名）命中市政过滤 → scope=state（默认）下该行被过滤，**不生成种子**；同日国家级条目照常派发。过滤计数在任务结果里说明。
3. **条目抓取**（以国家级条目 548/2026 为例，Húsnæðis-, mannvirkja- og skipulagsstofnun 住房建设规划局的规划公告，2026-05-26 刊）：`stjornartidindi_advert` 任务 `GET /api/v1/adverts/{uuid}`，响应含元数据与内联 HTML → documents 入账、两个文件落盘（`01_raw/stjornartidindi/2026/0548-2026/doc.html` + `meta.json`）。
4. **游标**：当日最后一个分页任务完成时 `stjornartidindi_last_date` 推进到 2026-05-29；下次 `sync=1` 从 2026-05-30 开始。
5. **复查**：账本可查——`SELECT title, publication_date, issuing_authority, doc_type FROM documents WHERE doc_id LIKE 'ISL_20260526%'`；磁盘可查——`01_raw/stjornartidindi/2026/0548-2026/doc.html`。

## 6. 怎么跑

```bash
# 回溯：公布日窗口（逐日枚举；默认 scope=state，--delay 控制礼貌间隔）
python cli.py collect --country isl --source stjornartidindi window=2026-05-25:2026-05-29

# 回溯：公报卷年（按年×部门；deild 缺省 = 三个部门全跑）
python cli.py collect --country isl --source stjornartidindi years=2025:2025 deild=a-deild

# 增量：从上次游标的次日到昨天（首次增量前需先跑过一次 window）
python cli.py collect --country isl --source stjornartidindi sync=1

# 含市政条目的全量口径（改口径 = 新任务身份自动补抓，无需清库）
python cli.py collect --country isl --source stjornartidindi window=2026-05-25:2026-05-29 scope=all

# 只列计划不抓取 / 状态查询 / 失败重排
python cli.py collect --country isl --source stjornartidindi window=2026-05-25:2026-05-29 --dry-run
python cli.py status --country isl --source stjornartidindi
python cli.py requeue --country isl --task-id {task_id}
```

参数：`window=FROM:TO`（公布日闭区间）或 `sync=1` 或 `years=FROM:TO`（卷年闭区间，须配合 `deild=a-deild[,b-deild[,c-deild]]`）；可选 `scope=state|all`（默认 state：按发布机构名过滤市政条目——市镇名以 -bær/-hreppur 结尾或以 Sveitarfélagið 开头）。缺参报错并打印上述用法。

## 7. 更新与增量

- **游标**：kv 键 `stjornartidindi_last_date`，存"已确认完整消费到"的公布日；`sync=1` 从游标次日到**昨天**（当日条目可能尚未挂出）。
- **空日照常推进游标**：查询型接口对无刊日返回空列表，这本身就是"该日完整消费"的确认。
- **两条轴各管一头**：增量与近期回扫走公布日轴（现代条目实时入库，公布日即真实刊日；跨年迟到条目按实际公布日落位——2024 全年 2,064 条中 168 条的公布日在次年 1 月，日轴天然覆盖）；历史回填走卷年轴（`publicationNumber.year` 全年代可靠）。两轴入口可任意重叠，重复条目靠任务身份去重（同一 uuid → 同一任务 id，已完成即跳过）。
- **重开规则**：本源无源站更新信号（公布即定格，快照语义）；需要重扫某段就换 window/years 参数（参数变 = 任务身份变 = 自动重走）。
- **回溯条目的日期口径**：publicationDate 照收源站展示的"Útg"日期（补录条目即入系统日，如 1995 年第 43 号 → 2003-09-26），**不改写不猜测**；`meta.created_date`（入系统时刻）与 `meta.signature_date`（签署日）随行记录，研究端可据 createdDate 甄别补录条目。生效日无结构化字段（只在正文文本内），如实缺失。

## 8. 已知边界与缺口

- **市政条目**：B deild 大量地方市政公告/收费表，默认 scope=state 下在枚举层过滤（市镇官方名单 + 常规命名后缀匹配）。2026-09-19 试跑窗口曾有 9 条市政条目在过滤规则补全前入账（Borgarbyggð、Norðurþing 等），保留在账中——`scope=all` 本就是合法口径，条目本身是真实的公报数据。
- **正文刊期戳**：每条正文的 HTML 末尾都带一行刊期戳（如 "A deild - Útgáfud.: 17. janúar 2025"，2025 年总统信函实例），它不是正文的一部分（清洗阶段可剥除）；**只有除戳之外再无其他文字**的条目才是数字化的空壳（1995–2000 代），其正文只在 PDF——该时段每条目自动多一次 PDF 请求；1995 年前无任何机器通道（扫描件层）。
- **Reglugerðasafn（现行条例汇编）未覆盖**：司法部维护的现行有效条例整并库（reglugerd.is / island.is/reglugerdir，2021 年第三版起修正折入正文），与公报不一致时以公报文本为准（其自述条款）。整并文本页可直读，但缺机器可枚举通道（无公开 API、站点 sitemap 不含条例 URL、列表页仅展示最新约 33 条），故本框架暂未收录——需要"现行文本/版本序列"时另行立项。
- **议会侧（Alþingi）未覆盖**：法律制定过程与 lagasafn 整编汇编在 althingi.is，本框架采集期实测该站对自动化 HTTP 访问全程返回 403（Cloudflare 挑战），需要浏览器通道，暂未建设。法律全文已由公报 A deild 覆盖（as-published 口径），不受此影响。
- **生效日**：API 无结构化生效日字段，缺失如实记录（正文内可读，属清洗阶段工作）。
- **附件与更正**（`attachments` / `corrections` 字段）：探查样本中均为空数组；非空时原样 JSON 串入 meta，未建结构。

## 9. 端点速查表

**在用**：

| 端点 | 参数 | 用途 |
|---|---|---|
| `GET /api/v1/adverts-lean` | year / department / dateFrom / dateTo / sortBy / direction / page / pageSize(≤100) | 列表枚举（两轴），无正文 |
| `GET /api/v1/adverts/{id}` | id（UUID） | 条目详情：元数据 + 内联 HTML 正文 + pdfUrl |
| `GET {pdfUrl}` | — | PDF 版面原件（adverts.stjornartidindi.is 直链） |

**源里还有、暂未用**（每项一句话研究价值）：

| 端点 | 价值 |
|---|---|
| `GET /api/v1/adverts` | 同 lean 但内联正文——本框架用详情端点取正文，无需重复通道 |
| `GET /api/v1/advert-types/types` / `main-types` | 95 个原生类型词全表——doc_type 映射表扩充时的词表底册 |
| `GET /api/v1/departments` | 三部门字典（含 UUID 主键） |
| `GET /api/v1/institutions` | 发布机构字典——研究"哪些机构高频发文"的底册 |
| `GET /api/v1/rss/{deild}` | 每部门最新条目 RSS——"今天有什么"的轻量探针 |
| `GET /api/v1/cases` / `signatures` / `categories` / `maincategories` | 案卷/签署/主题分类——主题维度研究候选 |
| `GET /api/v1/issues` / `POST /issues/generate` | 刊期表（实测对部分年代表返回空）与刊期生成（POST 型，采集不需要） |
| `GET /api/v1/pdf/{id}` / `pdf/case/{id}` / `pdf/application/{id}` | 备用 PDF 通道（详情里已带直链） |

---

*更新日期：2026-09-19；数据快照：2026-09-17（探查）/ 2026-09-19（试跑）；数据由 2026-09-19 试跑窗口背书——公布日轴 2026-05-25..29（57 条源站条目，48 条国家级入账，多重集逐一相同）+ 卷年轴 2025 年 A deild（109 部法律，刊号 1..109 连续，多重集逐一相同）；157 文档三方一致，幂等重跑零请求。*
