# 斯洛文尼亚（SVN）数据源说明——uradnilist（官方公报 Uradni list RS）

> 数据快照日期：2026-10-12。文中状态码、字节规模、计数与日期均为实测真实值（可重放复核）；账本内计数以 **2026-09-28..2026-10-09 十个出刊日窗口 + 1991-01-18 首期**两次真实采集为准（§5）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。斯洛文尼亚全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：斯洛文尼亚的官方公布媒介是什么

斯洛文尼亚的官方出版物是**《Uradni list Republike Slovenije》**（RS 官方公报），自 **1991-01-18**（独立后首期）连续出版至今（实测：公报接口内置的全部出刊日期表首日为 1991-01-18，共 3,801 期，2026-10-12 计）。

出版方在近年发生一次换代（2026-10-12 读站内公告并经独立报道互证）：

- **至 2026-02-28**：由国家企业 Uradni list d.o.o. 出版，纸质+电子并行，官网 uradni-list.si（该企业现已进入清算）。
- **自 2026-03-01**：新公报法（ZOUL，Zakon o objavljanju v Uradnem listu Republike Slovenije，2025-10-17 通过）生效——公报刊行权移交**政府立法局**（Služba Vlade Republike Slovenije za zakonodajo），一切公布**仅以电子形式经 PISRS 门户**进行，纸质版废止，并改行"一法一期"编号（每部法规一个独立期号，如 `1612/26`）。

**PISRS**（Pravno informacijski sistem RS，斯洛文尼亚法律信息系统，pisrs.si）由政府立法局运营，承担多重角色：①官方公布门户（2026-03-01 起）并托管 **1991 年至今的公报全档**（含按期 PDF 原件）；②现行法规登记库（每部法规一个总览页，含历史废止法规，全库 204,293 个法规 id，2026-10-12 sitemap 计）；③"非官方编纂文本"库（NPB，neuradno prečiščeno besedilo——编纂到某次修订为止的文本状态，168,368 页）；④判例、EU 法与国际条约汇编。

**本源的采集完全走 PISRS 的机器接口**：出刊日历、按日清单、公布 PDF 三个功能由同一 REST API（免 key、免会话的纯 GET）供给——清单行自带公报 slug 与 PDF 文件名，清单与文件本体在同源内连接，无需第二个网站分工。旧官网 uradni-list.si 已退化为按公报法第 33 条的存档站点，本源不使用它。

**收录范围**：按日清单把当日刊出条目按发布者分组——`drzavniOrgani`（国家机关：议会、政府、各部委……）、`lokalneSkupnosti`（地方自治体：市镇条例）、`nosilciJavnihPooblastil`（公共权力持有者：律师公会、公证人商会等专业团体）。本源默认采集**国家级**（scope=state，只取国家机关组），地方与公共权力持有者组放开口径即可补采（§3 的 scope 参数）。非法规类公报内容（公告、招标等）不在按日清单的法规登记口径内。

**文档形状**：每条法规一条公布记录（as-published 快照——公布时定格，不随后续修订变化）。修订后的编纂文本在 PISRS 有原生版本序列（NPB 库），但其数据结构与公报时间序列不同（§8）。

### 1.2 与欧盟法的关系

1. **转化立法——在本源内，正常逐条抓取。**斯洛文尼亚把 EU 指令转化为国内法用的是普通法律/政府条例，与本国产出同通道。
2. **直接生效的 EU 条例——不在本源。**需要 EU 法原文须去《欧盟官方公报》；PISRS 另有 EU 法登记角（§9），本源不采。
3. 官方译文版：PISRS 为部分法律提供英文版（"Zakonodaja v angleščini"汇编），公报原件保持斯洛文尼亚语单语；本源语料即斯语（§8）。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 无（全部端点无状态 GET；PDF 下载同样直连，2026-10-12 连续上百请求实测） |
| 字符编码 | 接口为 UTF-8 JSON；PDF 为二进制原字节 |
| 限额 | 无公开限额。框架统一限速（默认 0.5–1 秒/请求）即可；实测零拦截 |
| 反爬 | 无 Cloudflare 类防护，curl 直连即可。PISRS 网页端对登录/评论流有工作量证明挑战，但本源使用的公开只读端点完全不触发 |
| 响应格式 | 枚举层与日历层为 JSON；文档层为 PDF（`application/pdf` 原字节） |
| 空窗口行为 | 无刊日在出刊日历中直接缺席（日历即权威枚举，本源不会请求无刊日）；若日历断言有刊而清单返回空（`{"data":null}`），按接口形状故障响亮上报，不当作空日 |

## 3. 抓什么：任务类型清单

每种任务 = 一次下载 + 一次解析。共 **5 种**。2026-03-01（ZOUL）是**载体分界**：此前的法规每条都有存档 HTML 正文页（主文件、可直接清洗出纯文本），整期 PDF 原件作为第二载体一并存档；此后的法规只在 PISRS 有 PDF 原件（主文件）。

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `ul_month`（种子，每月一个） | GET 出刊日历 `/api/uradni-list/izdaje-datumi`（1991 年至今全部出刊日一次返回） | 过滤出该月落在窗口边界内的真实出刊日 → 每日一个 `ul_date` 种子；无出刊日的月份是合法空产出 |
| `ul_date`（每出刊日一个） | GET 按日清单 `/api/uradni-list/izdaje-seznam?datumObjave={日期}` | 解析发布者两级树 → 按 scope 过滤 → **登记当日全部文档行** + 按载体分界发后继种子（ZOUL 前：每法规一个 `ul_html` + 每份去重 PDF 一个 `ul_pdf`；ZOUL 后：每份 PDF 一个 `ul_pdf` 携带文档号）+ 推进游标 |
| `ul_html`（ZOUL 前，每法规一个） | GET 存档站正文页 `uradni-list.si/glasilo-uradni-list-rs/vsebina/{slug}/{标题slug}?h=` | 页面原样落盘为该法规的**主文件**（挂文档号）；正文容器 `div#divSection` 缺失即响亮上报（存档缺页或标题拼写漂移，绝不静默跳过） |
| `ul_pdf`（每份 PDF 一个） | GET `/api/uradni-list/objava/{文件名}.pdf` | PDF 原字节落盘。ZOUL 前=第二载体（一期一文件存一份，路径记在各法规 meta.ul_pdf_path）；ZOUL 后=主文件（挂文档号） |
| `uradnilist_clean`（清理，本地读不发网络） | 按文档号读本地主文件，**魔数嗅探分流** | HTML → 白名单容器 `div#divSection` 提纯文本；PDF → 说明性空产出（ZOUL 后主文件，纯文本属 PDF 清理子任务，见 §8） |

任务链：`ul_month × 月 → ul_date × 出刊日 →（ZOUL 前）ul_html × 法规 + ul_pdf × 去重 PDF／（ZOUL 后）ul_pdf × 去重 PDF → uradnilist_clean × 法规`。

命令行参数（key=value 形式）：

```
window=FROM:TO    闭区间日期窗口，如 2017-07-26:2017-07-29（必填，或改用 sync=1）
sync=1            增量：起点 = 游标 uradnilist_last_date 次日，终点 = 昨天
                 （当日刊可能尚未出齐；"今日尚无"与"当日无刊"不可辨，只到昨天）
scope=state       采集范围：state = 仅国家机关组（默认，按组过滤、零名字猜测）；
                  all = 全部（含市镇与公共权力持有者，改口径自动补抓、无需清库）
pdf=on            ZOUL 前法规是否同时存档整期 PDF 原件（第二载体，路径记
                  meta.ul_pdf_path）：on = 默认；off = 只抓 HTML 主文件
                  （2000–2025 全量回填口径可省约 2,900 请求与 7 GB；PDF 规范
                  地址始终记在 meta.ul_pdf_url，随时可按 URL 补抓）。ZOUL 后
                  的法规主文件就是 PDF，本参数不影响该年代
```

**窗口按"公布日期"**：清单按公布日编址，账本 `publication_date` 也是公布日——抓取轴与研究轴一致。

## 4. 数据落到哪

**零领域表**（扁平文档型路径，同德国 BGBl / 西班牙 BOE / 拉脱维亚 vestnesis）：本源采集单元是公布事件（as-published 文本一次定格），一条法规 = documents 一行。法规间的修订关系（如标题自带的"spremembe in dopolnitve"修订字样）是**字段**不是实体，随源照收进 meta。

一切研究字段进 `documents` 一张表：

| 列 | 内容 |
|---|---|
| `doc_id` | `SVN_{公布日YYYYMMDD}_{hash8(source_url)}` |
| `title` | 完整题名（清单行标题即权威，无截断问题） |
| `publication_date` | **公布日**；研究时间轴主日期。法规的采纳日/生效日清单行不给（原生缺失，记档不猜） |
| `issuing_authority` | 发布者（树第二级名称，如 `Državni zbor Republike Slovenije`） |
| `source_url` | `https://pisrs.si/pregledPredpisa?id={法规 id}`——每法规唯一、可重建、无一次性参数；全库 204,293 个 id 均落在 PISRS 官方 sitemap 内（2026-10-12 实证，含 1991 年最老与 2026 年最新样本） |
| `raw_format` / `language` | `pdf` / `slv` |
| `doc_type` | 由法规 id 前缀映射的受控类型（下表）；前缀永存 meta |
| `entity_ref` | NULL（扁平国家） |
| `meta` | 见下 |

**meta 字段**（原生字段无损收，全字符串）：`pisrs_id`（法规 id 全串，如 `ZAKO9575`；市政条目带 `MP_` 前缀）、`id_prefix`（类型前缀，如 `ZAKO`）、`ul_slug`（公报条目号，如 `2026-01-2272`——与旧官网及历史抓取同一命名空间，可作对账桥）、`ul_pdf`（PDF 文件名，如 `u20261612.pdf`）、`ul_pdf_url`（PDF 规范地址）、`ul_issue`（期号，如 `1612/26`）、`issuer_group`（发布者组：drzavniOrgani / lokalneSkupnosti / nosilciJavnihPooblastil）、`scope_slice`（state/all）；ZOUL 前的法规另有 `ul_pdf_path`（整期 PDF 原件的入库路径——主文件是 HTML 页，PDF 是第二载体，路径照记不缺）。

**doc_type 映射**（法规 id 前缀 → 受控类型；前缀是源站的原生类型编码，映射只是一层受控别名，跨国可比的统一类型学不在采集层做。2026-10-12 对 20.4 万 id 普查并抽验真实标题定表）：

| 前缀（斯洛文尼亚语原词） | doc_type |
|---|---|
| ZAKO（zakon 法律）、USTZ（ustavni zakon 宪法性法律） | STATUTE |
| URED（uredba 政府条例） | REGULATION |
| PRAV（pravilnik 规章）、NAVO（navodilo 指引）、TARI（tarifa 价目）、POSL（poslovnik 议事规则）、KOLP（kolektivna pogodba 集体合同）、STAT（statut 章程） | SECONDARY_LEGISLATION |
| ODLO（odlok 法令）、ODLU（odločba 行政决定）、SKLE（sklep 决议）、SKLU（sklep vlade 政府决议） | DECREE |
| ODRE（odredba 命令）、UKAZ（ukaz 通令） | ORDER |
| AKT、DRUG（drugo 其他）、ODLB、RESO（resolucija 战略性决议）、NEZN（neznano 未明）、其余未见前缀 | OTHER（原生编码永存 meta） |

文件落点（按年分片；ZOUL 前每法规一个 HTML 主文件 + 每期一份 PDF 原件，ZOUL 后一法一 PDF）：

```
{data_root}/SVN_policy/
├── state.db
├── failures/
└── 01_raw/uradnilist/
    ├── html/                          ← ZOUL 前：每法规一个存档 HTML 主文件（可直接清洗）
    │   ├── 1991/1991-01-0025.html
    │   └── 2017/2017-01-2065.html
    ├── 2017/
    │   └── u2017041.pdf               ← 整期 PDF 原件（第二载体，期内 N 法规共享，路径记 meta.ul_pdf_path）
    └── 2026/
        └── u20261612.pdf              ← ZOUL 后：一法一 PDF（主文件，数字原生有文字层）
```

- HTML 与 PDF 均为**源站原字节原样落盘**（实测抽验：磁盘文件与源站现取字节 sha256 一致，2026-10-12/15）。
- 老年代（1991–1994）的 PDF 为整期扫描件（无文字层）——但其存档 HTML 主文件有正文（1991 年样本实测 1,4–2,2K 字符/条），纯文本经清理层直接可得。
- 1995–2026-02 的整期 PDF 数字原生（有文字层）；2026-03-01 起一法一 PDF。

## 5. 完整案例走查（2026-09-28..10-09 十日出刊窗口 + 双载体窗口实跑，源站直连实值）

一个真实窗口的全链数据（每步可重放，账本内计数可从 state.db 复查）：

1. **种子**：2 个月任务（9 月边界切片 + 10 月边界切片）。日历对该窗口断言 10 个出刊日（9/28–10/2 五日 + 10/5–10/9 五日；10/3–4 为周末无刊、日历直接缺席）。
2. **清单**：10 个 `ul_date` 任务全部完成。以 2026-10-09 为例：当日国家机关组 2 个发布者（议会 1 条 + 政府 5 条）共 6 条，如《Zakon o spremembah in dopolnitvah Zakona o izvrševanju proračunov …》（法规 id `ZAKO9575`，公报条目号 `2026-01-2272`，期号 `1612/26`）——登记一行 documents：STATUTE、发布者 `Državni zbor Republike Slovenije`、公布日 2026-10-09、meta 全套（§4）。
3. **文件**：6 个 `ul_pdf` 任务（ZOUL 后一法一文件）。主例 `u20261612.pdf` = 160,354 字节，磁盘与源站 sha256 一致。
4. **窗口合计**（库内实值，2026-10-12 实跑）：**59 任务全部 done（3 月 + 11 日 + 48 PDF），0 永久失败、0 升级；51 文档（窗口 47 + 首期 4）**。窗口类型分布：DECREE 13 / SECONDARY_LEGISLATION 12 / STATUTE 9 / REGULATION 8 / OTHER 3 / ORDER 2。文件按年分片落 `01_raw/uradnilist/`。
5. **三方对账**（2026-10-12 核对）：① 磁盘 sha256 ≡ 账本，47/47（窗口）；② 源站独立复走 10 天清单，法规 id 多重集 ≡ 账本，10/10 日全等（47 ≡ 47）；③ 两份代表 PDF（新制一法一档 + 老制整期扫描档）源站复取逐字节一致。
6. **捆包年代的样子（双载体）**：2017-07-28 窗口实测（2026-10-15 载体改造后）——5 条法规各有一个存档 HTML 主文件（80–120 KB，`01_raw/uradnilist/html/2017/{slug}.html`）+ 共享整期 PDF 原件 `u2017041.pdf`（3.69 MB，路径记在各法规 meta.ul_pdf_path）；`clean` 一条命令把 5 页全部提为纯文本（1,154–24,050 字符，正文自含官方文头、装饰零泄漏）。独立后首期 1991-01-18 同构：4 条法规 HTML 主文件（1.4–2.2K 字符正文）+ 整期扫描件 `u1991002.pdf`（2,252,750 字节）存档。
7. **幂等重跑**：同窗口再次运行 → 入队 0、执行 0、零网络请求；`clean` 重跑同样零重写（已清理的跳过，ZOUL 后 PDF 主文件文档的说明性空产出也不重播）。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country svn --source uradnilist window=2026-09-28:2026-10-09 --dry-run

# 小窗口真实抓取（§5 的十日出刊窗口）
python cli.py collect --country svn --source uradnilist window=2026-09-28:2026-10-09

# 独立后首期（最老年代：整期扫描件共享形状）
python cli.py collect --country svn --source uradnilist window=1991-01-18:1991-01-18

# 每日增量（从上次游标的次日追到昨天）
python cli.py collect --country svn --source uradnilist sync=1

# 含地方自治体与公共权力持有者条目（改口径自动补抓、无需清库）
python cli.py collect --country svn --source uradnilist window=2026-09-28:2026-10-09 scope=all

# 清理：HTML 主文件 → 纯文本（本地读不发网络；演练/限量/全量）
python cli.py clean --country svn --dry-run
python cli.py clean --country svn --limit 500
python cli.py clean --country svn

# 状态 / 快照 / 修复
python cli.py status --country svn --source uradnilist
python cli.py export --country svn
python cli.py requeue --country svn
```

## 7. 更新与增量

- **游标**：`uradnilist_last_date`。清单任务完整消费自己那一天就把游标推到该日——解析完成即算（有无产出一律）；中途崩溃该日不推，下次自愈。多任务并发的完成顺序可能使游标短暂落后于真实前沿（如回填更早窗口会把游标带回），下次增量从游标处幂等重扫：已完成的日直接跳过、零网络请求，无害。
- **sync 终点取昨天、不取今天**：当日刊日内逐步上网（ZOUL 后一法一期逐条出现）；"今日尚无"与"当日无刊"不可辨，增量默认只到昨天。
- **抓的是公布快照，不设重开**：公布文本与书目字段一次定格，同窗口重复运行安全（任务确定性去重，已抓直接跳过、零请求）。效力状态类活视图字段本源不收。
- **清理版本**：规则升级 = 清理版本 +1，重跑 `clean` 即以新版本全量重清（与抓取重开同族的参数化重开）。当前 v2——v1→v2（2026-10-15）因可清理载体定义变化（最早一批 PDF 主文件文档的存档 HTML 转为主文件后需重清）。
- 回填任意年代与增量任意交错：入口重叠靠任务身份去重消化（多入口一漏斗），中间不重不漏。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **1991–1994 的 PDF 为整期扫描件** | 首页无文字层（实测 1991/1993/1994 三年样本均为 0 字符），PDF 直提正文需要 OCR——超出本框架清理层边界。但该年代每条法规的存档 HTML 主文件有正文（1991 年样本 1,4–2,2K 字符/条，2026-10-15 实测），纯文本经清理层直接可得；PDF 仅作原件存档 |
| **ZOUL 后（2026-03-01 起）无存档 HTML** | 存档站自身声明只收 2026-02-28 前期次（实测证实）；此后的法规主文件就是 PISRS 的 PDF（数字原生有文字层），纯文本提取属 PDF 清理子任务（几何通道，JPN/ISL 先例），`clean` 对其给出说明性空产出 |
| **版本序列（NPB 编纂文本）不收** | PISRS 有原生版本序列（`pregledNpb` 页按"基本法 + 截至某次修订"双参数编址，168,368 页，2026-10-12 sitemap 计）；但那是"编纂文本状态"这一种数据结构，与公报 as-published 时间序列不同构，本源定位是后者。需要版本序列时另立源 |
| **地方自治体与公共权力持有者默认不收** | scope=state 按组过滤（lokalneSkupnosti 与 nosilciJavnihPooblastil——后者为公会/商会类，2026-09-29 首次在窗口运行中实测出现）；`scope=all` 一键放开，改口径自动补抓 |
| **采纳日/生效日不收** | 按日清单行不携带这两个日期（源站原生缺失）；需要时在 PISRS 法规登记页（pregledPredpisa）另有字段，属登记库源的范畴 |
| **公告类公报内容不在清单** | 按日清单的登记口径是法规类条目；公告/招标等不进清单（与拉脱维亚同形）。如需公告类另立通道 |
| **一次性会话参数与登录面** | 本源全部端点免 key 免会话；PISRS 网页的登录/评论功能不在采集面内 |
| **南斯拉夫时代不覆盖** | 公报全档自 1991-01-18 起（斯洛文尼亚独立）；此前属前南斯拉夫法制序列，出界 |

## 9. 端点速查表

**在用**：

| 用途 | URL 模式 |
|---|---|
| 出刊日历（枚举主干） | `GET https://pisrs.si/api/uradni-list/izdaje-datumi`（一次返回 1991-01-18 至今全部出刊日，3,801 个日期，2026-10-12 计） |
| 按日清单（唯一发现入口） | `GET https://pisrs.si/api/uradni-list/izdaje-seznam?datumObjave={YYYY-MM-DD}`（发布者两级树；行内自带 slug/标题/法规 id/PDF 名/期号） |
| 公布原件 PDF | `GET https://pisrs.si/api/uradni-list/objava/{文件名}.pdf`（application/pdf 原字节） |

**已确认存在、本源未用**（各自一句话研究价值）：

| 端点/资产 | 价值 |
|---|---|
| `GET https://pisrs.si/api/uradni-list/leto-stevilka?datumObjave={日期}` | 按日返回期号列表——期次完整性对账的辅助通道 |
| `GET https://pisrs.si/api/sitemap/sitemap_pregledPredpisa_id{1-5}.xml` | 现行法规登记库全量枚举（204,293 个法规 id，2026-10-12 计）——source_url 覆盖性与登记库源的对账基准 |
| `GET https://pisrs.si/api/sitemap/sitemap_pregledNpb{1-4}.xml` | 非官方编纂文本全量枚举（168,368 页）——版本序列源的入口 |
| `GET https://pisrs.si/pregledPredpisa?id={法规 id}` | 单部法规的登记页（现行文本、采纳/生效字段、EuroVoc 主题）——登记库源的主通道（本源只用作 source_url 指称） |
| `GET https://pisrs.si/swagger`（`/api/v3/api-docs`） | 官方开发者 API 文档（评论/外部集成控制器）——PISRS 对外接口的权威索引 |
| `GET https://www.uradni-list.si/` | 旧公报官网（2026-02-28 前期次的存档站，清算中的 Uradni list d.o.o. 运营）。**每法规一页 HTML 正文仍在线**（`/glasilo-uradni-list-rs/vsebina/{slug}/{标题slug}?h=`，正文容器 `div#divSection`；2026-10-12 实测 4 点：1991 年 1,490 字符、2000 年 12,107 字符、2006 年 19,641 字符、2025 年 4,195 字符均可提取——**2000–2025 全区间可用**；ZOUL 后期次〔2026-03-01 起〕按站内声明不在）——文字备援与对账通道，本源不依赖 |

---

*更新日期：2026-10-15（pdf=off 回填口径当日启用）；数据快照：2026-10-15；数据由 uradnilist 源多次真实窗口背书（2026-09-28..10-09 十出刊日 59 任务零失败 / 多重集对账 10/10 / 幂等零请求；2017-07 与 2025-07 双载体窗口：HTML 主文件 + 整期 PDF 副本全链落账，clean 6+4 份纯文本、ZOUL 后 PDF 主文件说明性空产出免重播；存档站覆盖探针 32/32 命中）。*
