# 芬兰（FIN）数据源说明——finlex（Finlex 法规数据库：法规公报层）

> 数据快照日期：2026-09-13。文中条目计数、字节数、日期与状态均为当日对源站直连实测的真实值（响应样本已存档、可重放复核）；账本内计数在首次真实运行后补记（§5 末行）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。芬兰全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：Finlex 装了谁的产出

**Finlex**（finlex.fi，芬兰司法部 Oikeusministeriö 运营的官方法规数据库）是芬兰**国家层级一切规范文件的法定公布媒介**。其**法规公报**（säädöskokoelma，瑞典语 Finlands författningssamling）按年编卷、年 内连续编号：一件规范在公报上刊出即生效公布，一条 = 一个编号（如 2025 年第 51 号 = `51/2025`）。

芬兰国家层级的规范出自两个系统（宪法第 81 条框架）：

| 系统 | 工具 | 谁产出 | 公报里的占比（2025 年实测） |
|---|---|---|---|
| 立法 | **法律**（laki / lag；宪法性法律 perustuslaki 另有专门程序） | 议会（Eduskunta / Riksdagen）通过、共和国总统确认 | 927/1508 = 61% |
| 行政 | **政府令**（valtioneuvoston asetus / statsrådets förordning）与**部委令**（ministeriön asetus / ministeriöns förordning） | 政府内阁或各部委依法律授权发布 | 537/1508 = 36% |
| 行政 | 当局决定、通告、预算案等杂项（见 §1.2） | 各类机关 | 3% |

**双语制度**：芬兰语与瑞典语同为官方语，**同一件规范的两种语言文本同等效力**，在数据模型里是一件作品（work）下的两个语言表现（fin@ 与 swe@），各有自己的标题、自己的文件。2025 年实测双语覆盖 100%（1508 部 × 2 语逐一配对）；历史年代不对称（存在单语规范），以接口返回的表现为准。**采集口径（2026-09-14 调整）：默认只抓芬兰语**（主语言、语料原生语言）——瑞典语与芬兰语内容同效力，研究需要时以 `langs=fin,swe` 重跑即自动补抓（任务身份随语言参数变化，已抓部分零重复）；接口支持服务端语言过滤（`langAndVersion=fin@`），单语枚举页数减半。

**一个对研究重要的事实**：法律被修订或废止时，**修订案/废止案作为独立的新法案刊出**（有自己的编号），原法案的公报文本保持颁布原样——公报层是"颁布快照"序列，不是"现行文本"库（现行文本在另一套整合层，见 §1.4 与 §9）。

### 1.2 公报里有什么：工具类型与类别（2025 全年实测闭合）

工具类型（typeStatute，源站原生词表）：

| 类型 | 芬兰语标签 | 是什么 | 2025 年数量 |
|---|---|---|---|
| `act` | Laki（Lag） | 议会法律 | **927（61%）** |
| `decree` | Asetus（förordning） | **政府令与部委令同码** | **537（36%）** |
| `decision` | Päätös | 当局决定（如税务署 Verohallinnon päätös——依法须在公报刊发的行政决定） | 28 |
| `rules-of-procedure` | Työjärjestys | 议事规则类——**国家预算（Valtion talousarvio）与补充预算挂此码** | 6 |
| `announcement` | Ilmoitus | 部委通告 | 6 |
| `letter` | Avoin kirje | 总统公开信（如政府改组说明） | 3 |
| `list` | Luettelo | 清单（如 2026 年市镇所得税率清单） | 1 |

校验：927+537+28+6+6+3+1 = **1508**。词表随年代变化（1917 年含帝国元老院决定，同挂 `decision` 码）——未见过的码一律按 OTHER 兜底、原码照存。

类别（categoryStatute，与工具类型正交）：新订 `new-statute` **333** + 修订案 `amending-statute` **1126** + 废止案 `repealing-statute` **49** = **1508** ✓——修订与废止各占公报条目的大头，都是独立编号的法案。

### 1.3 数据通道：官方开放数据 REST API（免 key、无会话、无浏览器）

- 基址 `https://opendata.finlex.fi/finlex/avoindata/v1`，数据格式 **Akoma Ntoso 3.0 XML**（国际法律文档标准）；接口描述（OpenAPI）在 `/v3/api-docs`，共 36 个路径，分三族：`act/*`（法规：本源）、`judgment/*`（判例，不采）、`doc/*`（政府提案等，不采）。
- **枚举**：`GET /akn/fi/act/statute/list` 返回 JSON 行 `{akn_uri, status}`（每行 = 一个语言表现）。支持**服务端过滤**：`dateIssued=YYYY-MM-DD`（按制定日逐日，本源的日常入口）、`startYear/endYear`（按年回填）、`publishedSince`（变更喂送）、`typeStatute` / `categoryStatute` / `langAndVersion` / `titleContains` / `documentNumber`；`sortBy ∈ {number, dateIssued, modified}`。**每页上限 10 行**（超限 HTTP 400），`page` 从 1 起，**短页即末页**（逐日、逐年都要链式翻页——2025-02-13 一天就有 12 行两页）。
- **正文**：`GET /akn/fi/act/statute/{year}/{number}/{lang}@` 单请求单表现，返回完整 Akoma Ntoso XML（含全文）；`{number}` 按源串原样（历史年代有 `1-001`、`119-007` 复合格式）。
- `status` 两值：`NEW` / `MODIFIED`。MODIFIED 表示该条目文件在刊出后被源站**批量再生成**（文件生产时间戳晚于刊出日；2025 年 968/1508 部有此标记，再生成日期高度聚集于 2025-12-09 等少数几天）。实测确认它与"被修订"无关（被 2025/10 修订的原法 2021/294 状态仍为 NEW）、不是新版本（标题不变、无勘误标记）——**对"哪天出台了什么"的时间序列零影响**；状态与生产时间戳照收入账备查。

### 1.4 与现行法库的关系（本源不采，边界记录）

`/akn/fi/act/statute-consolidated/*` 是**现行法整合层**（ajantasainen lainsäädäntö）：同一批规范按"一部法一实体、随修订滚动出整合版"组织，URI 带时点版本码（如 `fin@20221250`），带结构化生效日（dateEntryIntoForce）、效力状态（isInForce）、废止链（repeals）、主管部委（administrativeBranch）。公报层没有任何效力状态字段——两层严格分离。整合层机器通道 2026-09-13 实测确认可用，**另行扩展**（清单见 §9）。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 无（无 cookie、无 token；全部请求无状态直连） |
| 请求头 | **每个请求必须带 `User-Agent`**（官方集成指南明示 required；缺失会被拒） |
| 限额 | 无公开限额。**实测**（2026-09-13）：无连接复用 + 约 0.4 秒间隔连发会被服务器**直接断连**（无 429、无错误体）；连接复用 + 0.6 秒间隔连发 302 页零掉线。建议 `--delay 0.5:1.5`，框架的传输层重试可自动穿过偶发断连 |
| 反爬 | 未发现（无验证码、无 IP 封禁迹象；断连为限流行为） |
| 响应格式 | 枚举：JSON（UTF-8）；正文：Akoma Ntoso XML（UTF-8），单件典型 5–30 KB（大型整合记录可达 400 KB+，本源公报层少见） |
| 许可 | Finlex 开放数据按其公开条款可自由再利用；正文为国家法令文本。引用建议注明来源 Finlex（finlex.fi）与司法部 |

## 3. 抓什么：任务类型清单

每种任务 = 一次请求 + 一次解析。共 **3 种** + 1 条可选修正通道：

| 任务类型 | 请求 | 产出 |
|---|---|---|
| `sd_day`（种子，一次扫描一个） | GET list `format=json&limit=10&dateIssued={D}&page=N`（满页翻下一页） | 每行 → 生成一个 `sd_fetch`；**当日扫完（含 0 行空日）→ 推进游标 `sd_last_date` 并链出次日**（扫描终点 `to_date` 随链携带）——逐日串行发现，窗口/增量都只入队一个种子 |
| `sd_year_page`（种子+链式，按年回填入口） | GET list `startYear=endYear={Y}&sortBy=number&page=N` | 同上产出 `sd_fetch`；走完该年即收口（不推日游标） |
| `sd_fetch` | GET `/akn/fi/act/statute/{y}/{n}/{lang}@` | `statutes` 台账一行（一部规范）；documents 一行（该语言表现）；XML 原样落盘 |
| `sd_fix`（可选，默认关） | GET list `publishedSince={水位}`（**时间戳必须带时区**，如 `2026-01-01T00:00:00Z`——无时区源站答 HTTP 400，包内已前置校验） | 变更行 → 对应 `sd_fetch` 带新信号重抓；水位只在整个返回消费完后推进 |

任务链：`sd_day × 每天 → sd_fetch × 每表现`；`sd_year_page × 每年 → sd_fetch`；`sd_fix → sd_fetch`。三个入口一漏斗——去重靠任务身份（`sd_fetch` 参数 = 年/号/语言，各入口产出同身份任务自动汇合），入口重叠只是重复枚举请求，无害。

命令行参数（key=value 形式）：

```
window=FROM:TO    按制定日闭区间逐日开 sd_day 种子，如 2025-02-13:2025-02-15（日常入口）
sync=1            增量：起点 = 游标 sd_last_date 次日，终点 = 昨天（为什么见 §7）
year=Y[:Z]        按年回填入口（如 year=1917 或 year=1734:1916）
langs=fin         语言口径（**默认只抓芬兰语**；补抓瑞典语用 langs=fin,swe——
                  新任务身份自动补抓，已抓的不重复）
types=...         工具类型过滤（默认全收；取值见 §1.2 表）
max_items=N       单次运行实际深抓的表现数上限（护栏参数）
fix=1             修正通道：从水位 sd_fix_watermark 起抓源站变更行
```

**空日即空分区**：周末与节日无新制定记录，接口返回空数组（HTTP 200），任务照常完成、游标照推——不是故障。404 只在真正异常时出现（如接口路径错误），按永久失败响亮报警。

## 4. 数据落到哪

**一张领域表**（判据：一部规范跨两个语言文档——work 是跨文档持久实体）。Finlex 的年+编号编址全库唯一，故主键即 (year, number)：

| `statutes` 列 | 内容 |
|---|---|
| `year` / `number` | 联合主键；number 为源串原样字符串（2025 年为整数串，历史年代有 `1-001` 复合格式） |
| `type_code` / `type_label` | 工具类型原码与芬兰语标签（如 `decree` / Asetus） |
| `category_code` / `category_label` | 类别原码与标签（如 `amending-statute` / Muutossäädös） |
| `date_issued` / `date_published` | 制定日（研究"何时出台"主轴）/ 公报刊出日——两者可差数日（国家预算 2025/1329：制定 12-19、刊出 12-23） |
| `eli` | 欧洲立法标识别名（如 `http://data.finlex.fi/eli/sd/2025/51/alkup`；老条目可能缺） |
| `title_fi` / `title_sv` | 双语原生标题（单语规范缺一侧，如实空） |
| `authority` | 签发机关，仅从芬兰语标题的签发语直读（"«机构»:n asetus/päätös/ilmoitus"句式 → 机构名，如 Valtioneuvoston asetus → Valtioneuvosto）；标题不含机关（Laki 类从不写）→ **留空**。源站自带的 FRBRauthor 字段恒标议会（部委令亦然），**不可作机关用**，仅入 meta 备查 |
| `list_status` | 最近一次观测的接口状态（NEW/MODIFIED） |
| `date_produced` | 源站文件生产时间戳（再生成痕迹，备查） |

**documents 一部规范两行**（每语言一行，各自独立文档）：

| 列 | 内容（以 2025/51 芬兰语行为实值） |
|---|---|
| `doc_id` | `FIN_{公布日}_{hash8(source_url)}` → `FIN_20250214_255c675c`（瑞典语行为 `FIN_20250214_8dbd58dd`） |
| `title` | 该语言原生标题 |
| `publication_date` | 公报刊出日（datePublished，2025-02-14）——研究时间轴主日期 |
| `issuing_authority` | 同 statutes.authority 规则（本例 Valtioneuvosto） |
| `source_url` | `https://opendata.finlex.fi/finlex/avoindata/v1/akn/fi/act/statute/2025/51/fin@`（接口表现地址，可重建、无会话参数） |
| `raw_format` / `language` | `xml` / `fin`（瑞典语行 `swe`） |
| `doc_type` | 类型受控映射（下表）；原码永存 meta |
| `entity_ref` | `statutes:2025/51` |
| `meta` | doc_number（51/2025）、type/category 原码+标签、date_issued、date_produced、eli、list_status、frbr_author（备查）、files（同规范另一语言文件路径） |

**doc_type 映射**（原生优先；跨国统一类型学不在采集层做）：

| typeStatute 原码 | doc_type |
|---|---|
| `act` | STATUTE |
| `decree` | DECREE |
| `decision` | SECONDARY_LEGISLATION |
| `rules-of-procedure` / `announcement` / `letter` / `list` / 未知新码 | OTHER |

文件布局（"一项政策一个文件夹"，年分片）：

```
{data_root}/FIN_policy/
├── state.db
├── failures/
└── 01_raw/finlex/
    └── sd/
        └── 2025/
            └── 51/                ← 一部规范一个文件夹
                ├── fin.xml         ← 芬兰语表现原样字节（12,365 字节，2026-09-13 实测）
                └── swe.xml         ← 瑞典语表现原样字节（12,400 字节）
```

## 5. 完整案例走查（2025-02-13 一个制定日，源站直连实值）

1. **日桶枚举**：`dateIssued=2025-02-13` → 12 行 **两页**（首页 10 行 + 第 2 页 2 行，短页即末页）= 当日 6 部：49、50、51、52、53、55（其中 49 为农业部令、51 为政府令、52 为政府修订令）。
2. **案例 2025/51**《Valtioneuvoston asetus vuodelta 2024 maksettavasta sokerijuurikkaan kuljetustuesta》（2024 年糖用甜菜运输补贴令；瑞典语标题 Statsrådets förordning om transportstöd för sockerbeta 2024）：类型 `decree`（Asetus）→ doc_type DECREE；类别 `new-statute`；**制定日 2025-02-13、刊出日 2025-02-14**；生效日在正文条款（"tulee voimaan 17 päivänä helmikuuta 2025"，即 2025-02-17——公报层无结构化生效日字段）；签发机关按标题直读 = Valtioneuvosto；ELI `http://data.finlex.fi/eli/sd/2025/51/alkup`；接口状态 NEW；两语文件各一份落盘（12,365 / 12,400 字节），documents 两行如 §4 表。
3. **同日的 2025/52**（修订令，类别 `amending-statute`）：制定 2025-02-13、**刊出 2025-02-17**（滞后 4 天——两日期分开入账的意义）；接口状态 MODIFIED（文件曾被源站批量再生成）。
4. **空日形态**：2025-02-14（周五）与 02-15（周六）日桶均 0 行 → 合法空产出、游标照推。
5. **一个年份的量级**：2025 全年 1508 部 / 3016 表现 / 枚举 302 页；与 www.finlex.fi 网站统计站点地图（60,095 条全库链接）逐年核对，2025 年 1508 ≡ 1508。
6. **账本内计数**（2026-09-14 首次实跑）：小窗口 `window=2025-02-13:2025-02-15` = 16 任务零失败（4 个日任务含链式第 2 页 + 12 个表现任务）、documents 12 行（6 部 × 双语）、`statutes` 6 行、游标单调推进至 2025-02-15、幂等重跑零请求；`year=1917 max_items=4` = 4 部帝国时代记录入账（复合序号 1-001 等、单语、发布日期留空）；其后一次修正通道实跑（`fix=1 since=2026-01-01T00:00:00Z`）把 2026 年增量与全部变更表现一并入账。**2000–2026 年回填（2026-09-15 完成，单语口径）**：芬兰语正文 **37,550 件**（对 sitemap 网站直方图逐年核对 37,503/37,528 = 99.93%，无年份级缺口；差值 25 部属刊出跨年归年差异与 API/网站同步差）+ 早期遗留的瑞典语 23,700 余份。账本累计 **documents 61,900 / statutes ~39,000**；磁盘 01_raw 1.15 GB + state.db 89 MB；抽样三方对账（磁盘 ≡ 账本 hash ≡ 源站字节）6/6 逐字节一致。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country fin --source finlex window=2025-02-13:2025-02-15 --dry-run

# 小窗口真实抓取（三天：一个正常日 + 两个空日）
python cli.py collect --country fin --source finlex window=2025-02-13:2025-02-15 --delay 0.5:1.5

# 每日增量（从上次游标的次日追到昨天）
python cli.py collect --country fin --source finlex sync=1 --delay 0.5:1.5

# 按年回填（某年全部，护栏示例只深抓 4 部）
python cli.py collect --country fin --source finlex year=1917 max_items=4 --delay 0.5:1.5

# 远古散件（1734 年法典等，量小一次收）
python cli.py collect --country fin --source finlex year=1734:1916 --delay 0.5:1.5

# 修正通道（源站变更行，默认不用，需要时手动跑）
python cli.py collect --country fin --source finlex fix=1 --delay 0.5:1.5

# 状态 / 快照 / 修复
python cli.py status --country fin --source finlex
python cli.py export --country fin
python cli.py requeue --country fin
```

## 7. 更新与增量

- **游标 `sd_last_date`**：`sd_day` 完整扫完自己那一天（无论几行、含 0 行）才推进；中途崩溃该日不推，下次自愈。
- **sync 终点取昨天**：某日制定的记录当天何时进入开放数据未逐时验证——与"当日无刊"的空桶同形的"尚未入库"若被误扫过就会永久漏掉，故增量默认只到昨天。即便偶有晚入库（>1 天），`fix=1` 的 `publishedSince` 通道也能兜底——实测它同样返回新增行（NEW）。
- **按年回填与增量重叠无害**：`sd_fetch` 任务身份（年/号/语言）确定，已完成的直接跳过（零请求）；回填更早日期会把日游标往回带，下次 sync 幂等重扫（无害）。
- **修正通道默认关**：`publishedSince={水位}` 只返回水位后变过的行（含新增与源站再生成），变更行以水位时间戳为信号重开对应 `sd_fetch`（文件与台账幂等覆盖）；水位 `sd_fix_watermark` 只在返回页全部消费完后推进。
- **抓的是颁布快照**：同一窗口重复运行安全（确定性去重）；MODIFIED 再生成不改变条目的颁布语义（§1.3），需要最新文件时跑一次 `fix=1` 即可。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **生效日无结构化字段** | 公报层日期只有制定日/刊出日/文件生产时间；生效日写在正文条款（"tulee voimaan …"），采集层不解析——现行法整合层有结构化生效日，其通道已确认（§9），另行扩展 |
| **日期字段的三种源站形态**（2000–2026 回填实测：涉及 43% 的语料） | 现代记录（约 2019 年起）制定日+刊出日双全；**2000–2018 年代的大量记录（1.6 万件级）只有制定日**——源站 XML 三层（work/expression/manifestation）均无刊出日，数字档案早期原生如此，非采集缺口；另有少量目录性条目（如 1994/787《最高法院工作规则》）只有**源站生成的近似日期**（dateIssuedGenerated，如 1994-01-01，meta 标记 `date_issued_generated`）。刊出日缺失时文档的发布日期**留空**（doc_id 日期段为 00000000），研究时间轴请用 `statutes.date_issued`（全量覆盖）——宁可空不可错 |
| **签发机关无结构化字段** | 源站 FRBRauthor 恒标议会（部委令亦然）不可用；`authority` 列按标题直读，标题不含机关则留空（宁可空不可错） |
| **制定日 ≠ 刊出日** | 两日期分开入账（实例：2025/1329 差 4 天）；按制定日分桶枚举，"某日出台了什么"两种口径都可查 |
| **MODIFIED 的字节级差异不可考** | 源站批量再生成无修改前版本可对比（网页存档与旧数据均无，2026-09-13 实测确认）；不影响颁布快照语义，状态与时间戳已入账备查 |
| **历史年代覆盖** | 1917 年（独立）起连续（当年 278 部）；1734 年法典 3 行 + 1868–1907 零星散件；1918–1916 间无记录是源站事实不是漏抓 |
| **历史单语规范** | 早期存在单芬兰语或单瑞典语的规范（如 1920 年代），按接口返回的表现收，缺侧不虚补 |
| **类型/类别词表随年代变化** | 1917 年已有不同用法（帝国元老院决定挂 decision 码）；未知新码一律 OTHER、原码照存 |
| **PDF 不抓** | 正文 XML 已内联全文；PDF 直链（`{表现URL}/main.pdf`，实测 GET 可用）不落盘，需要时可按 URL 补抓 |
| **当日入库时点** | 见 §7（sync 到昨天 + fix 兜底） |
| **不在本源** | 现行法整合层、机构规章与指引（authority-regulation 族）、政府提案（HE）、判例、萨米语与外语翻译版本、市镇地方层、欧盟法原文——各自通道与扩展建议见 §9 与 overview |

## 9. 端点速查表

**在用**：

| 用途 | URL 模式 |
|---|---|
| 逐日枚举（日常入口） | `GET …/avoindata/v1/akn/fi/act/statute/list?format=json&limit=10&page=N&dateIssued={YYYY-MM-DD}` |
| 按年枚举（回填入口） | `GET …/statute/list?format=json&limit=10&page=N&startYear={Y}&endYear={Y}&sortBy=number` |
| 变更枚举（修正通道） | `GET …/statute/list?format=json&limit=10&page=N&publishedSince={ISO 时间戳}` |
| 正文（每表现一请求） | `GET …/avoindata/v1/akn/fi/act/statute/{year}/{number}/{fin@&#124;swe@}` |

**已确认存在、本源未用**（各自一句话价值）：

| 端点/资源 | 价值 |
|---|---|
| `…/act/statute-consolidated/list` 与 `…/statute-consolidated/{y}/{n}/{lang}@{版本码}` | **现行法整合层**：版本谱系、结构化生效日、效力状态（isInForce）、废止链（repeals）、主管部委（administrativeBranch）——版本序列研究的直接素材（2026-09-13 实测可用） |
| `…/doc/authority-regulation/list`（按 `{authority}/{year}/{number}` 编址） | 各行政机构自发规章与指引（类比"机构指引层"），不在公报内 |
| `…/doc/{docDocumentType}/list` | 政府提案（HE）等决策过程文档族 |
| `…/judgment/{judgmentDocumentType}/list` | 判例族（最高法院/最高行政法院等） |
| `…/act/statute/{y}/{n}/{lang}@/main.pdf` | 公报正文 PDF 直链（实测 GET 200；HEAD 被拒 403，勿用 HEAD 探测） |
| `https://www.finlex.fi/sitemaps/statute.xml`（13 页 60,095 条） | 网站统计站点地图——全量对账与正门 URL（`/fi/lainsaadanto/saadoskokoelma/{y}/{n}`）来源 |
| `https://opendata.finlex.fi/v3/api-docs` 与 集成指南 `https://www.finlex.fi/en/open-data/integration-quick-guide` | 官方接口描述（36 路径、参数全集）与集成指南 |

---

*更新日期：2026-09-15；数据快照：2026-09-15；数据由 window=2025-02-13:2025-02-15、year=1917 与 2000–2026 年回填实跑背书（37,550 件芬兰语正文 / 逐年对账 99.93% / 三方抽样 6/6 逐字节一致 / 幂等重跑零请求），计数见 §5 第 6 条。*
