# 荷兰（NLD）数据源说明——bekendmakingen（Officiële bekendmakingen · Staatsblad）

> 数据快照日期：2026-09-29。文中计数、字节数与状态码均为当日对源站直连实测的真实值（可重放复核）；账本内计数见 §5 末行（真实运行后补记）。
> 阅读前提：了解仓库根目录 `python cli.py` 的用法即可，不需要读代码。
> 本文是 bekendmakingen 单源的说明；荷兰全部源的总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：Staatsblad 是什么、装了谁的产出

**Staatsblad**（*Staatsblad van het Koninkrijk der Nederlanden*，荷兰王国国家公报）是荷兰**国家层级法律与法令的法定公布媒介**——国家的 Wet（法律）、AMvB（*Algemene Maatregel van Bestuur*，行政管理一般措施，即次级法令）、Koninklijk Besluit（王国法令）等只有在 Staatsblad 刊出才对外生效。每期刊登若干件公布，一件公布（如"Wet van 20 december 2023 tot vaststelling van de begrotingsstaten van het Ministerie van Economische Zaken en Klimaat (XIII) voor het jaar 2024"，即 stb-2024-1）就是本源的一条数据。

公布按**公布物（blad）**分刊：Staatsblad（国家公报，本源默认）、Staatscourant（政府公报，部委决定/人事/招标公告为主）、Tractatenblad（条约公报）、Gemeente- 与 Provinciale bladen（市/省公报）。本源只收 Staatsblad：它是"国家出台了什么"的公布事件流，其他各刊要么不是政策文书（Staatscourant 里大量人事与招标通告），要么明确不在范围内（地方、条约）。

体量与节奏（2026-09-29 实测）：Staatsblad 年约 300–1000 件（2026 年至 9 月 298 件；2010 年 901 件），公布日集中在周一至周五、日均 0–6 件（2026-09-21 至 09-25 一周五日实测 4/0/6/3/6——周二可为零刊日）。索引覆盖自 **1951 年**起（1950 及以前不在索引；1956、1959 两年为数字化缺口，实测为 0）；**全文 XML 自 1995 年**起，此前仅有扫描 PDF。

### 1.2 与 wetten.overheid.nl 的分工（两层并存）

荷兰与澳大利亚/瑞士同型：**公布层与编纂层原生并存**。

| 层 | 渠道 | 性质 | 本源 |
|---|---|---|---|
| 公布层 | Officiële bekendmakingen（SRU API） | 一次刊出 = 一条数据，颁布原样快照 | **本源采集**（时间序列） |
| 编纂层 | wetten.overheid.nl（BWB 基础法文件库） | 同一部法的现行有效文本与版本谱系 | 未采（2026-09-29 实测主页可达但法规深链对直连请求 404，暂无稳定机器通道） |

要"政府在某日公布了什么"用本源；要"某法此刻有效文本"需编纂层，另行扩展。

### 1.3 数据通道：KOOP 官方 SRU 2.0 API（免 key、无会话、无浏览器）

官方公布门户的检索能力由 KOOP 的 SRU 接口提供（官方使用手册《Handleiding SRU 2.0》公开可下），端点：

```
GET https://repository.overheid.nl/sru
    ?operation=searchRetrieve&version=2.0
    &query=<CQL 查询式>
    &maximumRecords=N [&startRecord=N]
```

CQL 查询式（本源用的按日枚举）：

```
c.product-area=="officielepublicaties" AND
c.content-area=="officielepublicaties/stb/{年}" AND
dt.issued=="YYYY-MM-DD"
```

- **每天一个查询**，日期直接构造，无需先抓任何索引（与 ESP BOE 同型；Staatsblad 无刊日也照常返回 200，记录数为 0——不是 404）；
- 每条记录自带**完整元数据 + 全部载体直链**（XML/HTML/PDF/ODT/metadata 六种 manifestation，即同一公布的不同文件形态）：
  - 元数据：`dcterms:identifier`（如 `stb-2024-1`）、`dcterms:title`、`dcterms:type`（如 Wet/AMvB）、`dcterms:creator`（部委）、`dcterms:issued`（刊出日）、`datumOndertekening`（签署日）、`publicatienaam`/`publicatienummer`/`jaargang`、`behandeldDossier`（议会案卷号）；
  - 载体：`gzd:itemUrl manifestation="xml"` 指向 `repository.overheid.nl/frbr/officielepublicaties/stb/{年}/{id}/1/xml/{id}.xml`——**全文内联的 XML**，本源主文件取它；
- 翻页 `maximumRecords` + `startRecord` 均实测生效（用 3.2 万条的 Staatscourant 年度查询验证），Staatsblad 日均个位数记录、翻页仅是护栏；
- 记录内的 XML 载体若不存在（1994 年前的扫描年代），记录仍给出 PDF 与 metadata 直链——扫描件不产生正文文档，元数据照收入账（§3）。

**编号不连续的实证（为什么必须按 API 枚举、不能按号构造 URL）**：stb-2026 期号 290 存在（HTTP 200）而 294–296 无（404），同年记录总数 298——期号与实际公布件数不一一对应，构造式枚举必然漏抓。索引式枚举（本源做法）不受影响。

### 1.4 正文格式：多代 XML 形状并存

| 形状 | 根元素 | 出现处 |
|---|---|---|
| 现代件（约 2014–今） | `officiele-publicatie` | op-xsd-2014 schema（如 stb-2024-1.xml，29,152 B，2026-09-29 实测） |
| 旧 SDU DTD 第一代（1995–约 2014） | `staatsbl` | staatsbl-11.dtd（如 stb-1995-78.xml，32,688 B） |
| 旧 SDU DTD 第二代 | `staatsblad` | staatsblad-1_61.dtd（如 stb-2010-138.xml，29,171 B） |
| 改良版件（verbeterblad，公报页的勘误重印） | `vblad` | 同 staatsbl-11.dtd 族（如 stb-2000-30-v1.xml，1,375 B） |
| 无全文件 | `metadata` | 源站没有正文时 xml 载体实为约 300 B 的元数据存根（如 stb-2009-601-b1） |

解析按根元素分流，五种形状全部接受：**文档元数据一律取自 SRU 记录**（随任务参数传递），正文 XML 只作原样落盘的语料——schema 差异不影响入账字段。标识符也有两处源站不一致：改良版/附件后缀既可为连字符段（`stb-2000-30-v1`、`stb-2009-548-b3`）也可直接粘在期号上（`stb-2007-562v1`），均如实按原标识符入账与命名文件夹。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 无（无 cookie、无 token，全部请求无状态直连，2026-09-29 连续数十请求实测） |
| 限额 | 无公开限额；框架统一限速（0.5–1 秒/请求）足够安全 |
| 反爬 | 无；robots.txt 只禁 HTML 搜索结果页（`/zoeken/resultaat*`），API 通道不受限；源站官方立场即"批量取数用 API、勿爬网页" |
| 响应格式 | SRU 响应 XML（UTF-8）；单日查询典型 60–260 KB（含该日全部公布物记录） |
| 许可 | 法律、法令与条例按荷兰《著作权法》第 11 条不受著作权保护 |

## 3. 抓什么：任务类型清单

每种任务 = 一次下载 + 一次解析。共 **3 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `bek_day`（种子，逐日一个） | SRU 按日查询（§1.3 查询式） | 每条记录派一个 `bek_item`（记录元数据随参数传递）；**无 XML 载体的记录**直接登记 metadata-only 文档（PDF 直链入 meta，正文缺口如实标记）；当日 0 条 = 合法空产出；推进游标 `bek_last_date`（账本里"已完整消费到哪一天"的进度标记，详见 §7） |
| `bek_item` | GET 记录内 XML 载体直链 | 响应字节原样落盘 `doc.xml` 主文件 + documents 一行（元数据取自参数，正文只验形状） |
| `bek_year`（扫尾入口，逐年一个） | 同端点整年查询（只按 content-area 年，**不带日期过滤**，自动翻页） | 同 `bek_day` 的记录处理；**不推游标**。存在理由：改良版件（-v1）是前一年公报页的勘误重印，发布日多在次年 1 月而 content-area 仍挂前一年——按日查询按"日期年份"构造范围，这类件结构性查不到（2000–2025 实测每年 0–14 件，共 89 件）。与按日入口在身份层自然汇合（同标识符 → 同文档 → 已完成即跳过），重复扫描零成本 |

任务链：`bek_day × 每天 → bek_item × 每条记录`；`bek_year × 每年 → bek_item × 尚未抓过的记录`。

命令行参数（key=value 形式）：

```
window=FROM:TO    闭区间日期窗口，如 2026-09-21:2026-09-25（与 sync=1、years= 三选一）
sync=1            增量：起点 = 游标 bek_last_date 次日，终点 = 昨天（为什么见 §7）
years=2000:2025   整年扫尾（补跨年改良版件；单年 years=2007 亦可）
blad=stb          收哪些公布物，逗号分隔（默认 stb；如 stb,stcrt 连政府公报一起收）
```

## 4. 数据落到哪

**零领域表**（扁平文档型路径，同德国 BGBl / 法国 JORF / 西班牙 BOE）：公布条目刊出即定、条目即文档本体，语料里没有跨文档的持久实体；条目间的关联字段（议会案卷号、对其他公布的引用）是**字段**不是实体，随源照收进 meta。一切研究字段进 `documents` 一张表：

| 列 | 内容 |
|---|---|
| `doc_id` | `NLD_{刊出日YYYYMMDD}_{hash8(source_url)}` |
| `title` | 完整题名（如 `Wet van 20 december 2023 tot vaststelling van de begrotingsstaten van het Ministerie van Economische Zaken en Klimaat (XIII) voor het jaar 2024`） |
| `publication_date` | 刊出日（dcterms:issued）——研究时间轴的主日期 |
| `issuing_authority` | 提出部门（dcterms:creator，如 `Ministerie van Economische Zaken en Klimaat`） |
| `source_url` | `https://zoek.officielebekendmakingen.nl/{id}.html`——官方永久链接（公布物明示永久链接保证），可重建 |
| `raw_format` / `language` | `xml` / `nld` |
| `doc_type` | 由原生类型映射的受控类型（下表）；原生词永存 meta |
| `entity_ref` | NULL（扁平国家） |
| `meta` | 见下 |

**meta 字段**（原生字段无损收，全字符串）：`identifier`（stb-… 主键）、`publicatienaam`（Staatsblad）、`publicatienummer`（期号）、`jaargang`（年卷）、**`datum_ondertekening`（签署日）**（与刊出日合成研究日期两件套）、`creator`/`publisher`（部委，如提出=EZK、刊行=Justitie en Veiligheid）、`behandeld_dossier`（议会案卷号）、`native_type`（原生类型词：Wet/AMvB/Klein Koninklijk Besluit/RijksAMvB…）、`content_area`、`xml_url`、`pdf_url`、`html_url`、`preferred_url`、`records_found`（当日记录数）、`files`（文件清单）；扫描年代件另有 `scan_era=true`、无 `xml_url`。

**doc_type 映射**（原生优先：native_type 永存 meta，映射只是一层受控别名）：

| 原生类型词（荷语） | doc_type |
|---|---|
| Wet / Rijkswet | STATUTE |
| AMvB / RijksAMvB / (Klein) Koninklijk Besluit | DECREE |
| 其余（Goedkeuringswet 等） | OTHER |

文件落点（"一项公布一个文件夹"，年/公布双层）：

```
{data_root}/NLD_policy/
├── state.db
├── failures/
└── 01_raw/bekendmakingen/
    └── 2026/                        ← 年分片（约 300–900 件/年，单层够用）
        └── stb-2026-281/            ← 一条公布一个文件夹（identifier 命名）
            └── doc.xml              ← 全文 XML 原样字节（文档主文件）
```

## 5. 完整案例走查（stb-2024-1，源站直连实值）

一个真实公布的全链数据（2026-09-29 实测，每步可重放）：

1. **发现**：按日查询 `dt.issued=="2024-01-17"`（该日全库 66 条记录中 Staatsblad 恰 2 条，双查询互证）→ 派出 stb-2024-1 与 stb-2024-2 两条 `bek_item`；
2. **元数据**（SRU 记录）：标题"Wet van 20 december 2023 tot vaststelling van de begrotingsstaten van het Ministerie van Economische Zaken en Klimaat (XIII) voor het jaar 2024"；类型 Wet（→ STATUTE）；签署日 2023-12-20；刊出日 2024-01-17；提出部门 Ministerie van Economische Zaken en Klimaat；案卷号 36410-XIII；六种载体直链齐全；
3. **正文**：`GET https://repository.overheid.nl/frbr/officielepublicaties/stb/2024/stb-2024-1/1/xml/stb-2024-1.xml` → 200，29,152 B（op-xsd-2014 形状，含 aanhef/wettekst 全文）；
4. **入账落盘**：`01_raw/bekendmakingen/2024/stb-2024-1/doc.xml`；documents 一行（doc_id 以刊出日 2024-01-17 与永久链接计算）。

窗口实跑合计（2026-09-21:2026-09-25，库内实值）：**24 任务全部完成（5 个 `bek_day` + 19 个 `bek_item`）、0 失败、0 告警；19 文档（7 STATUTE + 12 DECREE）、游标 `bek_last_date=2026-09-25`**。2026-09-22（周二）为确认零刊日（合法空产出、游标照推）。三方对账：磁盘文件 ≡ 账本 file_hash 19/19 一致；源站重取抽样 3 份字节级一致。重复运行同窗口零种子零请求。

**2000–2026 全量回填后账内实值（2026-09-30）**：16,465 文档（2000–2025 年 content-area 集合 16,165 + 2026 年 299 + 1 件无载体现代件），01_raw 0.99 GB，state.db 106.5 MB；磁盘 ≡ 账本逐文件哈希 16,464/16,464 全等；按 content-area 年的标识符集合对账 26 年 missing=0 / extra=0。

**清理层（2026-10-03 全量完成）**：每份有文件的文档都有一条确定性纯文本产物，落在 `02_cleaned/{sha256(doc_id) 前 2 位}/{doc_id}.txt`，台账在 `cleaned` 表（版本、路径、哈希、字符数）。五形状共用一套块映射表（47 个断行标签 + 12 个行内不拆词标签 + 元数据/印刷厂号剪除），按根元素白名单分流、表外文本叶响亮报错；`metadata` 存根 4 份无正文，清理记合法空产出。字符数分布与异常短清单见 §8。

**2000–2026 全量回填后补记（2026-09-30）**：§6 的 `years=` 扫尾入口即回填期间实证补上的通道（详见 §3/§7/§8）。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country nld --source bekendmakingen window=2026-09-21:2026-09-25 --dry-run

# 小窗口真实抓取（一周，含一个零刊日）
python cli.py collect --country nld --source bekendmakingen window=2026-09-21:2026-09-25

# 每日增量（从上次游标的次日追到昨天）
python cli.py collect --country nld --source bekendmakingen sync=1

# 历史回填（1995 年起有全文 XML；并发四线程，全局限速不变）
python cli.py collect --country nld --source bekendmakingen window=2010-01-01:2010-12-31 --workers 4

# 整年扫尾（收按日入口看不到的跨年改良版件；建议每年 1–2 月对上一年跑一次）
python cli.py collect --country nld --source bekendmakingen years=2025

# 清理（格式转换 + 装饰剥离：XML 公报 → 确定性纯文本；本地读，不走网络）
python cli.py clean --country nld --dry-run          # 看会清理哪些
python cli.py clean --country nld --limit 500        # 小批试跑
python cli.py clean --country nld                    # 全量（幂等，已清理自动跳过）

# 状态 / 快照 / 修复
python cli.py status --country nld --source bekendmakingen
python cli.py export --country nld
python cli.py requeue --country nld
```

## 7. 更新与增量

- **游标**：`bek_last_date`。每个 `bek_day` 完整消费**自己那一天**才把游标推到该日——SRU 对任何日期都返回 200（0 条记录 = "该日确认无刊"的完整回答，照推游标）；中途崩溃该日不推，下次自愈。并发采集下完成顺序乱序，游标可能落在已抓区间内——`sync` 按游标重扫时已完成的日任务零成本跳过，只真实抓取缺口（2026-09-30 实测：游标落回年内时 sync 自动补齐当年缺口并追到昨天，零失败）。
- **sync 终点取昨天、不取今天**：当日公布上午生成（KOOP 网络时间未逐时实测），生成前去问当天与"当日无刊"返回完全相同的 0 条——为杜绝把"尚未生成"误判为"当日无刊"，增量默认只到昨天。
- **跨年改良版件的扫尾**：按日增量对"前一年公报次年 1 月出改良版"结构性失明（§3），建议每年 1–2 月对上一年跑一次 `years={上一年}` 扫尾（身份层去重，扫过的自动跳过）。
- **快照语义，无重开**：公布刊出即定，同窗口重复运行安全（任务确定性去重，已抓直接跳过、零请求）。
- 往更早日期开窗口即历史回填，游标回拉幂等无害；1951 年前的日期一律 0 条——那是索引边界，不是故障。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **只收 Staatsblad** | Staatscourant（2026 年 31,619 条实测）/ Tractatenblad / 地方公报未收；`blad=` 参数可扩（§3） |
| **扫描年代无正文** | 1995 年前仅有 PDF 扫描：记录照常入账（metadata-only，PDF 直链入 meta），正文文档缺——全量回填 1995 前需先解决 PDF 通路 |
| **个别现代件无载体** | 极少数现代记录源站也无 xml/pdf 载体（2000–2026 全程实测仅 1 件：stb-2025-105，2025-04-25 刊出，截至 2026-09-30 源站仍无正文文件）——metadata-only 入账，载体重生成后重扫即补 |
| **短文档是真实内容** | 勘误件（VERBETERING，数百字符）与"仅 PDF 格式可用"的附件通知（stb-2009-548/573-b*，8 份约 160–260 字符）本就只有通知文字——非清理缺陷，字符数雷达的低尾即此 |
| **源站元数据脏值 1 例** | stb-2019-129 的发布日期在源站为 0004-03-01（原始脏值原样入账）；阅读按 doc_id/标识符定位不受影响 |
| **数字化缺口两年** | 1956、1959 年在索引内为 0（SRU 与直连 PDF 双重复核一致）——源站数字化缺口，回填时按年核对 |
| **编号不连续 + 标识符后缀不规则** | 期号与件数不一一对应（stb-2026 期号 294–296 无而 290 有）；改良版/附件后缀有连字符（-v1/-n1/-b*）与粘着（562v1）两种写法——枚举一律走 API、标识符原样入账，禁止按号构造 URL |
| **多代 XML 形状** | 五种正文根元素并存（§1.4）；元数据取自 SRU 记录不受影响，正文落盘原样保留，语义级清洗按形状分流 |
| **编纂层未采** | wetten.overheid.nl 现行文本与版本谱系不在本源（§1.2） |
| **议会过程不在** | Kamerstukken / Kamervragen / Handelingen 在同一 API 内（content-area ah/kv/kst/nds/blg 等）但默认查询已按 content-area 排除，不会混入 |
| **当日生成前抓不到** | sync 到昨天规避（§7）；显式 window 含今天时自行承担时点风险 |

## 9. 端点速查表

**在用**：

| 用途 | URL 模式 |
|---|---|
| 按日枚举（唯一枚举入口） | `GET https://repository.overheid.nl/sru?operation=searchRetrieve&version=2.0&query=c.product-area=="officielepublicaties" AND c.content-area=="officielepublicaties/stb/{年}" AND dt.issued=="{YYYY-MM-DD}"&maximumRecords=100` |
| 全文 XML（主文件） | `GET https://repository.overheid.nl/frbr/officielepublicaties/{blad}/{年}/{id}/1/xml/{id}.xml`（取自记录内 manifestation="xml" 直链，勿自行构造） |
| 文档正门 URL（source_url 基底） | `https://zoek.officielebekendmakingen.nl/{id}.html`（浏览器可开；采集不走此通道） |

**已确认存在、本源未用**（各自一句话研究价值）：

| 端点/内容 | 价值 |
|---|---|
| 同一查询去掉 content-area 限制 | 一网收全部公布物（议会文件、省/市公报）——扩展源层时零改造 |
| 记录内 pdf / odt / metadata / metadataowms 载体直链 | 扫描年代回填走 pdf；odt 是版式最全的衍生格式 |
| `dt.available` / `dt.modified` 索引 | 按入库/修订时间轴的更新通道（现按刊出日枚举已足） |
| SRU facets（`facetLimit=…:dt.type,100:w.organisatietype`） | 类型/机关分布统计，回填前量级预检 |
| 同接口其余 connection（cvdr=地方规章 / BWB=编纂库 / eur / pod / wgk / oo） | `zoekservice.overheid.nl/sru/Search?x-connection=…`——BWB 是版本序列层的候选通道（2026-09-29 未验证通过） |
| wetten.overheid.nl 网页 | 现行编纂文本的人读入口；机器通道待另立 |

---

*更新日期：2026-10-03；数据快照：2026-10-03；数据由 **2000–2026 全量回填**实跑背书（26,409 任务零 permanent；16,465 文档 / 0.99 GB；26 个年份标识符集合对账 missing=0 extra=0、磁盘 ≡ 账本逐文件哈希全等）及 **全量清理**实跑背书（16,464 份清理任务零失败：16,460 份纯文本产物 + 4 份存根合法空产出；幂等重跑零重写）。*
