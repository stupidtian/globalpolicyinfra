# 丹麦（DNK）数据源说明——retsinformation（Retsinformation / Lovtidende）

> 数据快照日期：2026-09-16。文中条目计数、字节数与日期均为 2026-09-15/16 对源站直连实测或实际运行账本中的真实值（可复查）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。丹麦全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：Retsinformation 是什么、装了谁的产出

**Retsinformation**（retsinformation.dk，丹麦官方法律数据库）是丹麦**国家层级成文法的官方公布与查询系统**，由**国家行政署**（Civilstyrelsen，隶属司法部系统）运营。丹麦的官方公报是**Lovtidende**（法律公报），分两部：**Lovtidende A** 刊法律（lov）、整合版法律（lovbekendtgørelse，LBK）、行政命令（bekendtgørelse，BEK）、条例（anordning）等；**Lovtidende B** 刊极少数特殊文件（法罗/格陵兰相关，全年个位数）。通告（cirkulære）、指引（vejledning）、行政决定等**不刊公报、只在网络库**公布。议会立法过程文件（Folketinget 提案）与议会监察专员文件也在站内但不属公报。

一个对理解数据很关键的事实：**丹麦的"整合"（kodifikation）方式是重新公布**——修订累积到一定程度，主管部以 LBK 形式把现行文本重新刊出（本身就是一次 Lovtidende A 公布事件）。因此公报事件流与版本谱系天然咬合：同一部法的历史 = 主法 + 历次修订法（LOV Æ）+ 历代整合版（LBK），站内为每部法维护这条**版本时间线**。

覆盖范围与体量（2026-09-15/16 实测）：全库（含公报、网络库、议会、监察专员文件）**193,801 条**（搜索端点计数），ELI sitemap 全库 URL ≈ 21 万，年代跨度 **1665→2026**；丹麦语单语。数字化全文自 **1986 年**起，更早只有印刷版（藏于部分图书馆，站内时间线自带此注记）。

### 1.2 数据通道：三条官方通道（免 key、无浏览器）

站方 API 文档页（www.retsinformation.dk/static/api.html）明示两条官方开放数据服务；实测另有一条站内检索 API，共三条：

| 通道 | 用途 | 关键约束 |
|---|---|---|
| 站内检索 API `/api/documentsearch` | **枚举**（按公布日降序的全量行流，字段全） | **page 硬顶 99**（99 页 × 每页 100 行 = 9,900 条 ≈ 只回溯到 2024-04-26）；无服务端日期/类型过滤 |
| 官方收割 API `api.retsinformation.dk/v1/Documents` | **刷新**（按日变更喂送：新文档/内容变更/元数据变更/删除） | **每 10 秒 1 次**（违反回 429）；仅丹麦时间 03:00–23:45 开放；date 参数仅近 10 天 |
| ELI sitemap | **全库穷尽枚举**（≈21 页 × 1 万规范 URL，1665→2026） | URL 只有刊物+年+号，无日期；回填入口 |

**正文通道**：`GET {规范路径}/xml` 直回官方 LexDania 2.1 XML（站方收割服务的链接也指向此形式）。**全文年代边界**：约 2008 年起 XML 含全文；更早为纯元数据桩（结构性字段齐全——签署日、刊物、部委、期刊号、修订引用），老年代全文唯一出口是 POST 型 JSON 接口（本包已接入，见 §3 `rt_text`）。1986 年前的全文不在站内。

一个容易踩的坑：**文档网页是 React 单页应用**（服务端只回壳），但 XML 通道绕开渲染，全程无需浏览器。

### 1.3 两层口径：公报层与版本谱系层都抓

- **公报层（时间序列主源）**：默认收 **Lovtidende A/B** 的全部公布事件。检索行的规范路径前缀即刊物（`/eli/lta/`=A、`/eli/ltb/`=B、`/eli/retsinfo/`=仅网络库），枚举期零成本过滤；正文 XML 的 `AnnouncedIn` 字段为权威归属、与检索前缀互为核验。`scope=` 参数可扩至 ltc（C 部，年约 20 件）或网络库文件。
- **版本谱系层**：`/api/document/{id}/timeline`（仅法律与整合版两类文档有）一次返回整部法的版本链——主法、历次修订法、历代整合版，带签署日与现行标记。本包为每部法建一行台账（`laws` 表，锚点=时间线最早成员或主法项，**2026 年的整合版会正确收敛到 2001 年主法的同一行**，2026-09-16 实测），原始时间线 JSON 落盘。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 不需要（无 cookie、无令牌） |
| 限额 | 检索与正文通道无公开限额（实测连续约 200 请求零拦截，2026-09-15/16）；**收割 API 每 10 秒 1 次**（429 实测），刷新时用 `--delay 10:12` |
| 反爬 | www 站有 Cloudflare，按 **TLS 指纹**拦截 curl 类工具（403 实测），标准 HTTP 库直连正常——采集全程走框架传输层即可 |
| 响应格式 | 枚举=JSON；正文=XML（LexDania 2.1）；老年代文本=JSON 内嵌 HTML；sitemap=XML |
| 许可 | 国家行政署开放数据条款：**免费、非独占、无限制**再利用（可商用）；法律文本不受版权法保护（丹麦《版权法》§9）。条件：不得暗示官方背书、不得过度负载接口 |

## 3. 抓什么：任务类型清单

每种任务 = 一次请求 + 一次解析。共 **6 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `rt_window`（种子+链式） | 检索 API 第 N 页（按公布日降序） | 窗口内、目标刊物的每行 → `rt_timeline`（法律/整合版）或 `rt_doc`（其余）；整页走完且页内最老日期 < 窗口起点 = **终页**，推进游标 `rt_last_date`；到 page 帽仍未达起点 → 不推游标（窗口未完整消费）并说明 |
| `rt_timeline` | 该文档的版本时间线 | `laws` 表一行（锚点、主管部门、现行版本指针）+ `timeline.json` 原样落盘 → 链 `rt_doc`（携带法的键，注册时即有挂靠） |
| `rt_doc` | 正文 XML | documents 一行 + `doc.xml` 主文件落盘；**桩文档**（XML 无正文元素）→ 链 `rt_text` |
| `rt_text` | POST 型 JSON 接口（documentHtml） | 桩文档的老年代全文 → 兄弟文件 `text.html` + `doc_texts` 表入账（真实公布日随行记录）；或为收割变更解析出规范路径 → 链 `rt_doc`（保持原身份，防重复建行） |
| `rt_harvest`（默认关） | 收割 API 某日变更清单 | 每条变更（除删除）→ `rt_text` 解析链：解析出刊物后先对范围（范围外 = 说明性跳过）、解析出规范路径后链 `rt_doc` → 变更文档按**原身份**重抓（防重复建行） |
| `rt_sitemap` | sitemap 索引页/数据页 | URL 按刊物+年份过滤 → `rt_doc`（无公布日参数：此类文档 doc_id 日期段为 00000000，真实日期在 meta 与 `doc_texts`） |

任务链：`rt_window × 每 collect 窗口 → (rt_timeline →) rt_doc → (rt_text)`；`rt_harvest → rt_text → rt_doc`；`rt_sitemap → rt_doc → (rt_text)`。

命令行参数（key=value 形式）：

```
window=FROM:TO    公布日闭区间，如 2026-09-11:2026-09-15（必填，或改用 sync/years/harvest）
sync=1            增量：起点 = 游标 rt_last_date 次日，终点 = 昨天
years=Y[:Z]       sitemap 回填入口（如 years=1963 或 years=1998:2002）
scope=lta,ltb     刊物范围（默认 lta,ltb；可扩 ltc、retsinfo 等）
timeline=1        版本谱系开关（默认开；timeline=0 关闭）
harvest=1         刷新清扫（默认关），harvest_days=N 控制回看天数（默认 1，上限 10）
max_docs=N        每枚举页的抓取上限（测试护栏）
```

## 4. 数据落到哪

**两张领域表 + documents 表 + 每文档一个文件夹**。跨文档持久实体真实存在（一部法跨几十个文档），故有 `laws`；老年代文本是同文档的兄弟文件，而账本对 documents 行是"首写有效"，兄弟文件走 `doc_texts` 入账。

| 位置 | 记什么 |
|---|---|
| `laws` 表 | 法条目台账一行：谱系键（如 `lta-2001-166`）、法名、主管部门、**现行版本指针**（现行文档路径 + 其签署日）、timeline.json 路径 |
| `doc_texts` 表 | 老年代全文登记：doc_id（与 documents 同键）、text.html 路径、真实公布日 |
| `documents` 表 | 一份公报文档一行（颁布事件即文档本体） |
| `01_raw/retsinformation/{刊物}/{年}/{刊}-{年}-{号}/` | 该文档全部材料：`doc.xml`（主文件）+ `text.html`（老年代全文，如有） |
| `01_raw/retsinformation/laws/{法键}/` | `timeline.json`（版本时间线原样） |

documents 主要字段：`publication_date` = 检索行的公布日（研究时间轴主日期；sitemap 回填的桩年代文档缺此值时 doc_id 日期段记 00000000，真实日期见 `doc_texts`/meta）；`doc_type` 由类型码映射（LOV/LBK/FIN/DSK→STATUTE，BEK/AND/ABR→SECONDARY_LEGISLATION，其余→OTHER；**丹麦语原码永存 meta**）；`issuing_authority` = XML 的 Ministry；`language` = `dan`；meta 收：ELI 路径、刊物（AnnouncedIn）、类型原码与原词、签署日（DiesSigni）、XML 表现日（DiesEdicti——注意这不是公布日：1986 年文档标 2007-03-16 是数字化导入日）、现行状态（Status）、Rank、accession 号、站内唯一 id、期刊号、修订引用（Ref_Accn）。

文件夹布局（真实示例，2026-09-16 库内实值）：

```
01_raw/retsinformation/
├── lta/2026/lta-2026-747/doc.xml            ← LBK nr 747 af 03/08/2026（整合版法律，32,246 B）
├── lta/1963/lta-1963-259/
│   ├── doc.xml                              ← 1963 年元数据桩（无正文）
│   └── text.html                            ← POST 通道全文（3,446 B，1963-06-28 公布）
└── laws/lta-2001-166/timeline.json          ← 该法版本时间线（锚点=2001 年主法）
```

## 5. 完整案例走查

一个真实文档的全链数据（2026-09-16 库内实值，每步可复查）：

**LBK nr 747 af 03/08/2026**（"Lov om elevers og studerendes undervisningsmiljø" 的整合版，教育大臣 2026-08-03 签署、09-05 刊 Lovtidende A）：

1. **发现**：窗口 `2026-09-05:2026-09-09` 的检索行命中它（类型码 LBKH）→ 走 `rt_timeline`；
2. **谱系**：时间线返回该法整条版本链 → `laws` 行锚定为 **lta-2001-166**（2001 年的主法——2026 年的整合版正确收敛到 25 年前的法条目），现行指针 = 本文档（/eli/lta/2026/747，签署 2026-08-03）；timeline.json 落盘；
3. **正文**：`GET /eli/lta/2026/747/xml` → 32,246 B 官方 XML（含正文）→ documents 一行 + `doc.xml` 落盘；
4. **入账**：`DNK_20260905_cfe27bf7`，公布日 2026-09-05，doc_type STATUTE，机关 Undervisningsministeriet，`entity_ref='laws:lta-2001-166'`，meta 含 accession A20260074729、签署日 2026-08-03、刊物 Lovtidende A、期刊号等。
5. **对照案例（老年代）**：`years=1963` 经 sitemap 命中 `/eli/lta/1963/259`（1963 年大陆架条例）——XML 是桩（无正文）→ POST 通道取回 3,446 B 全文 → `text.html` 落盘、`doc_texts` 行记真实公布日 1963-06-28；doc_id 日期段为 00000000（检索行不可得的回填形态），签署日 1963-06-07 在 meta。
6. **全程合计**（2026-09-16 结题时库内实值）：两个真实窗口（09-11:09-15、09-05:09-09）+ 一次幂等重跑零请求 + 1963 回填抽查（sitemap 入口）+ 收割清扫（harvest=1，10 秒限速下 154 任务）+ sync 追平：**243 任务全部 done（4 rt_window + 2 rt_timeline + 108 rt_doc + 106 rt_text + 22 rt_sitemap + 1 rt_harvest）、0 失败 0 升级、failures 目录为空**；108 文档（97 lta 窗口/回填 + 7 sync 自愈补齐 + 4 accn 兜底身份）、2 行法条目、34 行老年代文本；**108 文档三方对账（源站直连 ≡ 磁盘 ≡ 账本 file_hash）逐一吻合、doc_id 零重复**；重复运行同窗口零请求。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country dnk --source retsinformation window=2026-09-11:2026-09-15 --dry-run

# 小窗口真实抓取（五个日历日，约 20 份公报文档）
python cli.py collect --country dnk --source retsinformation window=2026-09-11:2026-09-15

# 每日增量（从上次游标追到昨天）
python cli.py collect --country dnk --source retsinformation sync=1

# 历史回填抽查（sitemap 入口，1963 年，限每页 2 份）
python cli.py collect --country dnk --source retsinformation years=1963 max_docs=2

# 刷新清扫（收割 API 受每 10 秒 1 次硬限，必须配 --delay）
python cli.py collect --country dnk --source retsinformation harvest=1 --delay 10:12

# 状态 / 快照 / 修复
python cli.py status --country dnk --source retsinformation
python cli.py export --country dnk
python cli.py requeue --country dnk
```

## 7. 更新与增量

- **游标 `rt_last_date`**：检索按公布日降序翻页，**终页**（页内最老日期 < 窗口起点）完整消费了从最新到窗口起点的全部条目后才把游标推到窗口终点——中途崩溃游标不动，下次自愈；空日（周日/节日）自然零命中、终页语义照推。
- **窗口帽**：检索通道只够回溯约 9,900 条（≈17 个月，实测 2026-09-15 时边界为 2024-04-26）。sync 间隔超限会在帽页停住、**不推游标**并说明——那是 `years=` 回填入口的工作范围。
- **重开规则**：公报"刊出即定"，窗口任务确定性去重、重跑零请求；已刊文档的内容/元数据变更由**收割通道**发现（`harvest=1`，变更条目携带变更日期作信号，已 done 的文档任务只有信号变新才重开）；删除条目说明性跳过（账本不删行）。
- 丹麦的"整合版"（LBK）本身是新公布事件，按普通文档自动入账——现行文本的追踪不需要额外机制；`laws` 表的现行指针在每次抓到该法新成员时随时间线刷新。
- 往更早日期回填用 `years=`（sitemap 入口）；把游标往回带无意义（窗口与回填两入口靠任务身份层去重）。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **检索通道窗口帽 9,900 条** | 结构性硬帽（page≤99，pageCount 谎报 1939）；老日期一律走 `years=` sitemap 入口 |
| **桩年代 doc_id 日期段** | sitemap 回填无检索行 → doc_id 记 00000000（框架对缺日期的规定形态）；真实日期在 meta 签署日与 `doc_texts.publication_date`。专项回填时可改为"POST 先行"翻转载体归属，届时重新设计 |
| **XML 全文年代边界** | 约 2008 年起 XML 含全文；1986–2007 的全文走 `rt_text`（每文档多一请求）；1986 年前不在站内 |
| **DiesEdicti 不是公布日** | 它随 XML 表现更新（重生成会变），仅入 meta；公布日主口径 = 检索行 offentliggoerelsesDato（与 DiesEdicti 可差 1 天，实测 /eli/lta/2026/788：09-15 vs 09-14） |
| **生效日无结构化字段** | 丹麦法律生效日写在正文条款里，账本如实记缺；meta 的 valid_from/valid_to 是提交记录效力窗，不作生效日用 |
| **检索 API 属旧后端** | 新前端已不调用它（仍在服务、字段最全）；若日后退役，增量改走收割通道、回填走 sitemap，数据结构不变 |
| **收割 API 时段与限速** | 仅丹麦时间 03:00–23:45；每 10 秒 1 次（429 实测）；`date` 参数仅近 10 天——它是刷新通道不是回填通道 |
| **只收国家层级** | 地方（市镇规章）不做；判例（dom/ken）、监察专员（fob）、议会过程文件（ft）不在默认范围 |
| **accn 兜底身份（罕见）** | 个别老文档的 POST 元数据缺"刊物"字段（实测 1993 年通告），范围过滤与规范路径推导均不可得——按 accn 兜底身份入账（2026-09-16 结题账本 4 例，local_path 形如 `accn/accn-{号}/`） |
| **网络库文件默认不收** | cirkulære、vejledning、adm. afgørelse 等不刊公报的文件默认跳过（`scope=` 可扩） |
| Cloudflare 指纹拦截 | curl 类命令行工具整站 403；任何自写脚本请用标准 HTTP 库 |

## 9. 端点速查表

**在用**：

| 用途 | URL 模式 |
|---|---|
| 枚举（按公布日降序） | `GET https://www.retsinformation.dk/api/documentsearch?o=80&page={N}&ps=100`（N≤99） |
| 正文 XML | `GET https://www.retsinformation.dk{规范路径}/xml`（如 `/eli/lta/2026/788/xml`） |
| 老年代全文 + 元数据 | `POST https://www.retsinformation.dk/api/document{规范路径}`（JSON 体 `{}`） |
| 版本时间线 | `GET https://www.retsinformation.dk/api/document/{数字id}/timeline`（仅 LOV/LBK） |
| 变更喂送 | `GET https://api.retsinformation.dk/v1/Documents[?date=YYYY-MM-DD]`（10 秒 1 次，03:00–23:45） |
| 全库枚举 | `GET https://retsinformation.dk/sitemap.xml?page={N}`（N=0 即索引） |
| 文档正门 URL（source_url 基底） | `https://www.retsinformation.dk{规范路径}`（浏览器可开；采集不走此通道） |

**已确认存在、本源未用**（各一句话价值）：

| 端点 | 价值 |
|---|---|
| `GET /api/document/{id}/references/{0\|1}` | 站内引用关系图（谁引谁）——修订网络研究的直接素材 |
| `GET /api/document/{id}/reprintNotes`、`/timeline` 的勘误注记 | 重印/勘误追踪 |
| `GET /api/eli/named-authority-lists`、`/api/ressort` | 官方受控词表（机构、类型全表）——跨国类型学对齐的权威对照 |
| `GET /api/document/documentLinks/...` | 文档链接组（附件组） |
| ELI Atom Feed | 官方文档页提及（"ELI sitemap og ELI Atom Feed"）但常见路径未定位到；收割 API 已覆盖其用途 |

**ELI 编址速记**：`/eli/{刊物}/{年}/{号}`，刊物段 `lta`=Lovtidende A、`ltb`=B、`ltc`=C、`retsinfo`=仅网络库、`ft`=议会、`fob`=监察专员；别名形式 `/eli/accn/{accession号}`（accession = 类别字母+年+序号，A=法律类 B=命令类 C=其他）。类型码 110 个（LOVH 新法律、LOVC 修订法、LBKH 整合版、BEKH/BEKC 命令/修订命令、CIR 通告、VEJ 指引……），全表随源。

---

*更新日期：2026-09-16；数据快照：2026-09-16；数据由 window=2026-09-11:2026-09-15、window=2026-09-05:2026-09-09、years=1963（max_docs=2）、harvest=1（--delay 10:12）与幂等复跑/sync 实跑背书（243 任务零失败 / 108 文档 / 2 行法条目 / 34 行老年代文本 / 108 文档三方对账逐一吻合 / 幂等重跑零请求）。*
