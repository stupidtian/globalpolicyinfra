# 土耳其（TUR）数据源说明——resmigazete（官方公报 Resmî Gazete）

> 数据快照日期：2026-09-27。文中期号、条目数、字节数与状态码均为当日对源站直连实测的真实值（可重放复核）；账本内计数在首次真实运行后补记（§5 末行）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。土耳其全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：Resmî Gazete 是什么、装了谁的产出

**Resmî Gazete**（土耳其官方公报，"官方报纸"之意）是土耳其**国家层级规范文件的法定公布媒介**，纸媒自 1921-02-07 起出版，现由**总统府**在网上出版运营（www.resmigazete.gov.tr）。现行依据是 **Cumhurbaşkanlığı Kararnamesi No. 10**（《关于官方公报的总统令》，2018-07-15 公布于第 30479 期公报）：

- 第 2 条：公报由总统府在网上出版，必要时可印制纸质版；
- 第 3 条：**除法定节假日外每日出版**（必要时节假日亦出刊）；同日可出多期，加注 **Mükerrer**（土耳其语"重复/增刊"，指同一日期、同一期号的额外分册）；
- 第 4 条列举内容：法律（Kanun）、TBMM 决定、国际条约、总统令（Cumhurbaşkanlığı Kararnamesi）与总统决定/通告、法律指定的法院判决、依 3011 号法须在公报公布的规章（Yönetmelik）等。

每期公报按**节（bölüm）**组织，常见形态（2026-09-26 实测）：

| 节 | 内容 | 本源是否采集 |
|---|---|---|
| YÜRÜTME VE İDARE BÖLÜMÜ（行政节，历史期称 YASAMA VE İDARE） | 成品规范：法律、总统令、规章（Yönetmelik）、规程（Tüzük）、通告（Tebliğ）、各委员会决定、人事决定等，按类型分组 | **是（默认）** |
| İLÂN BÖLÜMÜ（公告节） | 法院公告、拍卖/招标公告、杂项公告、央行汇率表等 | 否（默认；`scope=all` 参数放宽，§3） |

**不在本源里的东西**：议会立法过程（TBMM 审议系统）、**整编现行文本**（历次修正合并后的"现在有效版"——那是 mevzuat.gov.tr 法规信息系统的职责，见 [mevzuat-zh.md](./mevzuat-zh.md)）、1921-02 至 2000-06 的更早年代（§8）。

### 1.2 数字化档案的覆盖与编址

公报站的**逐日结构化档案自 2000-06-28 起**（该日 = 第 24093 期，2026-09-27 直连实测；此前日期一律重定向回主页）。更早年代（1921–2000-06）只有按期号的整期扫描 PDF 通道（`/arsiv/{期号}.pdf`），无逐条结构，本期不采（§8）。

档案的三套编址（全部 2026-09-27 实测）：

| 通道 | URL 模式 | 说明 |
|---|---|---|
| **逐日索引页（fihrist）** | `GET /fihrist?tarih={YYYY-MM-DD}[&mukerrer={N}]` | fihrist 为土耳其语"索引/目录"，指每期公报的目录页。**服务端直接输出完整 HTML**（无脚本依赖），一期一页：期头（日期+期号+增刊号）→ 节 → 类型 → 条目链接。**本源的枚举唯一入口** |
| **单文文件（eskiler）** | `https://www.resmigazete.gov.tr/eskiler/{YYYY}/{MM}/{YYYYMMDD}[M{k}]-{seq}.{htm\|pdf}` | 一条目一文件，链接由 fihrist 直给。`M{k}` 后缀 = 第 k 增刊的条目；htm 为 Word 导出 HTML（**Windows-1254** 编码），pdf 为原始版式 |
| 公告文件（ilanlar） | `/ilanlar/eskiilanlar/{YYYY}/{MM}/…` | 公告节的文件，仅**类别级**（一天一类一文件，无逐条拆分）——默认范围外（§3） |

**无刊日与无增刊的语义**：fihrist 请求遇"该日无刊"或"该日无第 N 增刊"时重定向回主页（HTTP 302，传输层自动跟随得 200 主页 HTML）。区分办法是**指纹**：fihrist 页必含 `preview-title` 标记（期头块），主页/日报页没有（2026-09-27 以 8 个真实页面对照实测）——见 §3 的判定纪律。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 无（无 cookie 依赖、无 token；全部请求无状态直连，2026-09-27 裸 curl 实测） |
| 请求头 | 无特殊要求（普通浏览器 User-Agent 即可） |
| 限额 | 无公开限额；站内搜索接口连续请求实测正常。框架统一限速（0.5–1 秒/请求）足够安全 |
| 反爬 | 无（无 Cloudflare 类防护） |
| 响应格式 | fihrist 页 UTF-8 HTML（典型 78–85 KB/期）；条目 htm 为 **Windows-1254** 编码（土耳其语 ANSI 代码页，存储原样字节、解码属清洗阶段）；条目 pdf 为 application/pdf（实测 278,909 字节至 5.3 MB 不等） |
| robots | 只含搜索引擎 Noindex 提示，无 Disallow、无 Crawl-delay（2026-09-27 实测） |
| 再利用条款 | 站点未检出专门的数据再利用声明（2026-09-27）；官方公报内容为公开官报，引用时注明来源与 URL |

## 3. 抓什么：任务类型清单

每种任务 = 一次下载 + 一次解析。共 **2 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `rg_day`（种子，逐期一个 = 日期 × 增刊号） | GET fihrist 页（§1.2） | 解析期头（期号/日期/增刊号）与 节→类型→条目 层级；每条目（默认范围内）生成一个 `rg_item` 种子（携带期内序号、扩展名、期号、节、类型、标题——PDF 条目无文件内元数据，书目字段全靠种子携带）；同时生成下一增刊探测种子 `rg_day(mukerrer+1)`（§7）；页面无 `preview-title` → 判"该日无刊/无该增刊"，记合法空产出并推进游标；有期头而零结构化条目（2000 年首月个别日，§8）→ 记合法空产出并推进游标；其他未知形状 → 响亮失败 |
| `rg_item` | GET 单文文件（URL 由种子参数重建） | 一个文档记录 + 一个文件落盘（响应字节原样为主文件）；htm 条目从文件头部补齐发文机关与原生标题 |

任务链：`rg_day × 每日（含增刊链）→ rg_item × 每条目`。

命令行参数（key=value 形式）：

```
window=FROM:TO    闭区间日期窗口，如 2026-09-21:2026-09-26（必填，或改用 sync=1）
sync=1            增量：起点 = 游标 rg_last_date 次日，终点 = 昨天（为什么不是今天见 §7）
scope=mevzuat     范围过滤：mevzuat（默认，排除公告节 İLÂN）| all（公告节一并收）
```

**范围过滤在条目层执行**：fihrist 的公告节只有类别级链接（§1.2），默认范围内跳过 İLÂN BÖLÜMÜ 子树；该选择随任务参数走，将来改 `scope=all` 重跑会自动补抓，无需清库。

**"302 → 主页 = 无刊/无增刊"的判定纪律**（本源与多数国家"404 = 空分区"形态不同的一处）：

1. 传输层自动跟随重定向，解析拿到的是主页 HTML（HTTP 200）；
2. 解析先验指纹：**含 `preview-title` = 真 fihrist 页**（正常处理）；不含 = 主页形状 → 判"该日无刊（或无该增刊）"，任务记完成、游标按 §7 规则处理；
3. 既非 fihrist 又非已知主页形状（如半截 HTML、错误页）→ 按故障升级，绝不静默吞掉。

## 4. 数据落到哪

**零领域表**（扁平文档型路径，同西班牙 BOE / 德国 BGBl / 法国 JORF）：公报刊出即定、条目即文档本体，语料里没有跨文档的持久实体。一切研究字段进 `documents` 一张表：

| 列 | 内容 |
|---|---|
| `doc_id` | `TUR_{公报日YYYYMMDD}_{hash8(source_url)}` |
| `title` | fihrist 条目标题（去掉装饰前缀；htm 条目以文件头部原生标题为准） |
| `publication_date` | 公报刊出日（fihrist 的 tarih）——研究时间轴的主日期 |
| `issuing_authority` | 发文机关（htm 文件头部"Ticaret Bakanlığından:"式行；PDF 条目无法从文件取得，留空） |
| `source_url` | 单文文件 URL（`https://www.resmigazete.gov.tr/eskiler/2026/09/20260926-2.htm` 式，全年代稳定、可重建，无会话参数） |
| `raw_format` / `language` | `htm` / `pdf`（按链接扩展名与响应实形） / `tur` |
| `doc_type` | 由 fihrist 类型分组标题映射的受控类型（下表）；土耳其语原词永存 meta |
| `entity_ref` | NULL（扁平国家） |
| `meta` | 见下 |

**meta 字段**（原生字段无损收，全字符串）：`sayi`（期号）、`mukerrer`（增刊号，0 = 当日基础版）、`bolum`（节标题，如 YÜRÜTME VE İDARE BÖLÜMÜ）、`native_type`（类型分组标题，如 YÖNETMELİKLER）、`seq`（期内文件序号）、`kanun_karar_no`（标题内的文号，可解析则收，如 Karar Sayısı: 11752）。

**doc_type 映射**（原生优先：土耳其语原词永存 meta；跨国可比的统一类型学不在采集层做）：

| fihrist 类型分组（土耳其语原词） | doc_type |
|---|---|
| KANUNLAR（法律） | STATUTE |
| KANUN HÜKMÜNDE KARARNAMELER（法律效力令 KHK）/ CUMHURBAŞKANLIĞI KARARNAMELERİ（总统令）/ CUMHURBAŞKANI KARARLARI（总统决定）/ BAKANLAR KURULU KARARLARI（部长会议决定） | DECREE |
| TÜZÜKLER（规程）/ YÖNETMELİKLER（规章，含大学规章等子分组） | REGULATION |
| TEBLİĞLER（通告） | ORDER |
| 其余（委员会决定、人事决定、宪法法院/上诉法院判决分组等） | OTHER |

文件落点（一年一夹、一期一夹，文件名 = 源站原文件名，零转写）：

```
{data_root}/TUR_policy/
├── state.db
├── failures/
└── 01_raw/resmigazete/
    └── 2026/
        ├── D20260926/                     ← 一期一夹（公报日）
        │   ├── 20260926-1.pdf             ← 条目文件原样字节（一文件即一文档）
        │   ├── 20260926-2.htm
        │   └── …
        └── D20260906/
            ├── 20260906-1.htm             ← 当日基础版条目
            └── 20260906M1-1.pdf           ← 第 1 增刊条目（源文件名自带 M1 后缀）
```

- 每个条目文件即文档主文件（账本 local_path 指向它，doc_id 挂靠）；
- **整期 PDF 不抓**（`{YYYYMMDD}.pdf` 与 `{YYYYMMDD}M{k}.pdf`，fihrist 期头的"PDF Görüntüle"按钮链接）：内容与条目文件重复，条目齐则期齐；URL 不入账（需要时按编址规则直接可重建）。

## 5. 完整案例走查（2026-09-26 一期与 2026-09-06 增刊日，源站直连实值）

1. **常规日**：`GET /fihrist?tarih=2026-09-26` → 200，80,749 字节。期头 = "26 Eylül 2026 Tarihli ve 33382 Sayılı Resmî Gazete"（2026-09-26 · 第 33382 期）。行政节下 5 个规范类条目：Hâkimler ve Savcılar Kurulu 决定（→ `20260926-1.pdf`，application/pdf，278,909 字节）、Ticaret Bakanlığı 规章等 3 部规章（→ `20260926-2.htm` 至 `-4.htm`，Windows-1254）、EPDK 委员会决定（→ `20260926-5.pdf`）；公告节 4 个类别级链接（默认范围跳过）。
2. **htm 条目内部**（`20260926-2.htm`，30,715 字节）：文件头部自带 `26 Eylül 2026 CUMARTESİ` / `Resmî Gazete` / `Sayı : 33382` / 类型 `YÖNETMELİK` / 机关 `Ticaret Bakanlığından:` / 标题 `TİCARET BAKANLIĞI DİSİPLİN AMİRLERİ YÖNETMELİĞİ`，其后为条文正文（MADDE 1- …）——发文机关与原生标题由此补齐。
3. **增刊日**：`GET /fihrist?tarih=2026-09-06` → 200（基础版，第 33362 期）；同页自带导航链接 `fihrist?tarih=2026-09-06&mukerrer=1`（"6/9/2026 tarihli ve 33362 mükerrer sayılı…"）。取 `&mukerrer=1` → 200，期头多"1. Mükerrer"字样，唯一条目 = Orta Vadeli Program（2027-2029）批准决定（Karar Sayısı: 11752）→ 文件 `eskiler/2026/09/20260906M1-1.pdf`（application/pdf，5,310,422 字节）。
4. **无刊日语义**：`GET /fihrist?tarih=2000-06-26` → 302 → 主页（无 `preview-title`）；同日 `2000-06-28`（第 24093 期）正常——档案起点前一日即此形态。
5. **跨源核对**（与 mevzuat 源对账，2026-09-27 实测）：7595 号法律（Millî Dayanışma ve Toplumsal Bütünleşmenin Güçlendirilmesine Dair Kanun）在本源 2026-08-18 期（第 33344 期）条目 3（`20260818-3.htm`），与 mevzuat 源名录记录的公报日期/期号（18.08.2026 / 33344）逐字一致。
6. **窗口合计**（2026-09-28 真实运行，账本实值）：`window=2026-09-21:26` 六日窗 = 50 任务全 done（6 基础日 + 6 增刊探测 + 38 条目），零失败零告警；38 文档（htm 28 / pdf 10）落 `01_raw/resmigazete/2026/`；游标 `rg_last_date=2026-09-26`；随后 `sync=1` 自动追 09-27 一日（+2 任务 +6 文档，游标推进 09-27）；同窗重跑零请求；抽样三方对账（磁盘 ≡ 账本校验和 ≡ 源站直连字节）3/3 逐字节一致。七日内均无增刊（探测全落主页 = 预期空产出）。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country tur --source resmigazete window=2026-09-21:2026-09-26 --dry-run

# 小窗口真实抓取（§5 的窗口）
python cli.py collect --country tur --source resmigazete window=2026-09-21:2026-09-26

# 每日增量（从上次游标的次日追到昨天）
python cli.py collect --country tur --source resmigazete sync=1

# 连公告节一起收（scope 放宽将来生效，无需清库）
python cli.py collect --country tur --source resmigazete window=2026-09-21:2026-09-26 scope=all

# 状态 / 快照 / 修复
python cli.py status --country tur --source resmigazete
python cli.py export --country tur
python cli.py requeue --country tur
```

## 7. 更新与增量

- **游标**：`rg_last_date`。每个 `rg_day` 完整消费**自己那一天**才把游标推到该日——200 且解析完成（无论有无条目）、或 302 经指纹验证为"无刊/无该增刊"，都算完整消费；同日多个增刊任务对同键写入同值（取当日日期），先完成者先写、后完成者覆盖为同值，无乱序风险；中途崩溃该日不推，下次自愈。
- **增刊发现 = 链式探测**：每个 `rg_day(日期, m)` 完成后无条件生成 `rg_day(日期, m+1)` 种子，直到某级 302（= 该级增刊不存在）自然终止。代价 = 每日恰一次探测请求（约占总请求 13%）；基础版页面自带的增刊导航链接（§5.3 实测）作为双保险同时解析，两级机制互为校验。多增刊日（一日两增刊以上）是否在导航中列全未实测——链式探测保证不漏。
- **sync 终点取昨天、不取今天**：当日刊晨间生成，生成前访问与"无刊"同形（302 → 主页），为杜绝误判，增量默认只到昨天。
- **抓的是快照，不设重开**：公报刊出即定，同窗口重复运行安全（任务确定性去重，已抓直接跳过、零请求）。
- 往 2000-06-28 至今之间任何日期回填安全；更早日期一律 302——那是档案边界，不是故障。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **1921-02 至 2000-06 未覆盖** | 该年代只有整期扫描 PDF（`/arsiv/{期号}.pdf`，按期号编址，无逐条结构、无元数据）——回填另立项，需要 PDF + OCR 通路 |
| 档案首月空壳日 | 2000-06-28 起的首月内个别日 fihrist 内容为空的 Word-HTML 外壳（无结构化条目，2026-06-28 实测；2000-08-01 起稳定结构化）——按合法空产出处理，不丢期 |
| **公告节默认排除** | İLÂN 节为类别级文件（无逐条），且多为拍卖/法院公告/汇率表等非政策类；`scope=all` 放宽（§3）。站内搜索接口的公告分支参数形状未探明（2026-09-27 实测两种日期格式均不可用），如需逐条公告通道需另行研究 |
| PDF 条目元数据薄 | 无文件内元数据，书目字段全部来自 fihrist 种子（标题/类型/节/期号）；发文机关无法取得（htm 条目才有） |
| 整期 PDF 不抓 | 与条目文件内容重复（§4）；编址规则已记录，需要时可直接重建 URL 补抓 |
| 生效日无独立字段 | 公布日与（htm 头部的）通过日已收；生效日期写在条文内（"yürürlüğe girer" 条款），源站无结构化字段——清洗/分析阶段从正文提取 |
| 英文译本 | 站内搜索接口返回字段中有 `translateUrl`（实测均为 null）——官方英文译本通道存在与否未证实 |
| 限速 | 无公开限额实测；全量回填（约 9,590 天 ≈ 7.3 万请求）按默认限速约 10–20 小时，建议分年分批 |

## 9. 端点速查表

**在用**：

| 用途 | URL 模式 |
|---|---|
| 逐日索引页（枚举唯一入口） | `GET https://www.resmigazete.gov.tr/fihrist?tarih={YYYY-MM-DD}[&mukerrer={N}]`（无刊/无增刊 = 302 → 主页，指纹判定见 §3） |
| 单文文件（文档本体） | `GET https://www.resmigazete.gov.tr/eskiler/{YYYY}/{MM}/{YYYYMMDD}[M{k}]-{seq}.{htm\|pdf}`（链接由 fihrist 直给） |

**已确认存在、本源未用**（各自一句话研究价值）：

| 端点 | 价值 |
|---|---|
| `POST /Home/Filter`（站内搜索的数据接口，JSON） | 日期窗口 + 类型 + 关键词的条目检索——**对账/补漏工具**（其条目 URL 字段只指回 fihrist 页，作枚举通道反而多一跳；camelCase 参数 + ISO 日期，2026-09-27 裸请求实测可用） |
| `GET /arsiv/{期号}.pdf` | 1921–2000 年代整期扫描件——历史回填的主通道 |
| `GET /{DD.MM.YYYY}`（日报页） | 当日/指定日的浏览器视图（条目由脚本动态渲染，内容与 fihrist 同源）——人看用，采集不走 |
| `GET /ilanlar/eskiilanlar/{YYYY}/{MM}/…` | 公告节类别级文件——`scope=all` 时使用 |
| `GET https://www.resmigazete.gov.tr/eskiler/{YYYY}/{MM}/{YYYYMMDD}[M{k}].pdf` | 整期 PDF——版式核对用 |

---

*更新日期：2026-09-28；数据快照：2026-09-28；数据由 window=2026-09-21:26（50 任务 38 文档零失败）+ sync=1 追 09-27（+6 文档）实跑背书，抽样三方逐字节一致。*
