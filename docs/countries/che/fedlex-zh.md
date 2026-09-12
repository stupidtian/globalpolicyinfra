# 瑞士（CHE）数据源说明——fedlex（Fedlex 联邦法律发布平台：官方汇编 AS + 系统汇编 SR）

> 数据快照日期：2026-09-09（源站实测）。文中条目计数、字节数与字段值均为当日对源站的实测真实值（查询原文与响应样本已存档，可重放复核）；账本内计数在首次真实运行后补记（§5 末行）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。瑞士全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：Fedlex 装了什么、两类载体的分工

**Fedlex**（[fedlex.admin.ch](https://www.fedlex.admin.ch)，联邦总理府 Bundeskanzlei 运营）是瑞士**联邦层级法律的官方法律发布平台**。瑞士联邦法律的两类官方载体都在此，且**原生并存**：

| 载体 | 全称 | 性质 | 在本源的角色 |
|---|---|---|---|
| **AS** | Amtliche Sammlung（德，官方汇编；法 Recueil officiel，RO；意 Raccolta ufficiale，RU） | **公布媒介**：法律在此公布（Verkündung / promulgation）即定，按年连续编号、按期（Memorial）组织——一次刊登 = 一条公布事件 | **时间序列主体**（必抓层） |
| **SR** | Systematische Sammlung（德，系统汇编；法 Recueil systématique；英 Classified Compilation） | **现行法编纂库**：按主题分类号（如 741.01）组织的现行法全集，每部法一个条目、每个整合时点一个版本 | **版本序列层**（条目谱系全收 + 锚点版正文） |

两个载体的关系：一件法律先在 AS 公布（事件、不再变化）；随后进入 SR 的编纂体系（实体、随修订持续演化——修订生效即出现新的整合时点版本）。同一件法律在两侧以不同的身份存在，SR 条目带 `basicAct` 字段指回它在 AS 的原始公布——**两层一次配齐**是本源的结构价值。

**多语言制度**（本源是这套工具遇到的第一个多语言源，口径见 §4）：联邦三种正式语言为德/法/意，罗曼什语（Romansh）为部分场合的官方语。**同一件 AS 法律以三语并行公布、三语文本同等效力**——在数据模型里体现为一件作品（work）下的三个语言表达（expression），各有自己的汇编编号（AS 2026 449 / RO 2026 449 / RU 2026 449，纪念册名随语言）、自己的标题、自己的文件。AS 层全量实测（2026-09-09）：三语 = 德/法/意，罗曼什与英语表达计数为 **0**；SR 层的时点版本则偶尔带罗曼什（如 1958 年《道路交通法》条目）或英语（如其 2014-01-01 版本）译文。远古条目的三语编号可以不同（1848 年首件：德 AS I 45 / 法 RO I 45 / 意 RU I 47——打印时代各语版独立排页）。

**语料范围**（2026-09-09 实测）：AS 全量 **49,594** 件，自 **1848-11-15**（联邦建国当年首件 `eli/oc/I/45_45_47`）；近年年量约 800（2023：847 / 2024：799 / 2025：873）。**数字正文文件自 1998-09-01 起**（电子汇编起点，首件 `eli/oc/1998/2009_2009_2009`）——此前 41,000+ 件为纸质时代，平台只存元数据（正文扫描件在联邦档案馆 [bar.admin.ch](https://www.bar.admin.ch)，不在本平台，见 §8）。SR 侧：**17,299** 个条目 + **56,370** 个时点版本；版本深度差异极大（1958 年《道路交通法》SR 741.01 已 151 版，多数法只有 1–3 版）。

**不在本源里的东西**：《联邦公报》（Bundesblatt / Feuille fédérale，联邦公报平台代号 fga，162,252 件——议会咨文、法案、磋商文件，属决策过程层）、州（canton）立法（各州自己的公报）、国际条约的全文库（SR 层有条约条目与元数据）。

### 1.2 数据模型：ELI 三层（work → expression → manifestation）

Fedlex 的数据层是一个**机器可读的关联数据图**（欧洲 ELI 本体 + Jolux 扩展，SPARQL 端点全量可查，§9）。三层模型正好对应"作品—语言—文件"：

```
eli/oc/2026/449                                  ← work（一件法律/一次公布事件）
├── publicationDate 2026-09-04（公布日）
├── dateDocument 2026-08-27（制定日）
├── dateEntryInForce 2027-01-01（生效日）
├── sequenceInTheYearOfPublication 449（年序号）
├── isPartOf → eli/collection/oc/2026/139（期，带期号与公布日）
├── typeDocument → 类型词表（多语标签，如 Departementsverordnung）
├── responsibilityOf → 机构词表（如 Generalsekretariat VBS）
├── classifiedByTaxonomyEntry → SR 分类号（skos:notation，如 172.220.111.310.2）
└── isRealizedBy
    ├── eli/oc/2026/449/de    ← expression（德语表达：identifier "AS 2026 449"、标题、简称）
    │   └── isEmbodiedBy eli/oc/2026/449/de/html、…/pdf-a、…/docx、…/xml
    │                          ← manifestation（格式体现：isExemplifiedBy 给出文件直链）
    ├── eli/oc/2026/449/fr    ← 法语表达（identifier "RO 2026 449"）
    └── eli/oc/2026/449/it    ← 意大利语表达（identifier "RU 2026 449"）
```

SR 侧同构再加一层版本结构：

```
eli/cc/1959/679_705_685                            ← SR 条目（一部法的编纂实体，常青不失效）
├── classifiedByTaxonomyEntry → notation "741.01"（SR 分类号）
├── basicAct → eli/oc/1959/679_705_685（指回 AS 原始公布）
├── inForceStatus → 效力词表（0=In Kraft 现行 … 5=Sistiert 中止，6 值）
└── 成员版本（isMemberOf 反向）：
    eli/cc/1959/679_705_685/20240101               ← 时点版本（Consolidation）
    ├── dateApplicability 2024-01-01（本版生效日）
    ├── dateEndApplicability 2024-04-30（下一版接替日；最新版无此字段）
    └── isRealizedBy /20240101/de|fr|it → manifestation（同上，含文件直链）
```

三个实测要点（都会影响使用，写进了解析规则）：

1. **条目级"现行"表达没有文件**：`eli/cc/{…}/{lang}`（无日期段）只有元数据；**现行文本 = 该条目下 dateApplicability 最大且已生效的时点版本**。要下载现行整合版必须先找到最新版本、再取它的 manifestation（想当然地对条目地址发下载请求会一无所获）。
2. **文件直链只认图里给的**：manifestation 的 `isExemplifiedBy` 字段给出确定性文件地址（§9 规律）。**自行拼 URL 会被骗**：不存在的地址返回的不是 404 而是一个 HTTP 206 的 HTML 错误页（2026-09-09 实测）——所以一切下载地址以图内字段为准，响应另做魔数校验。
3. **同一个 manifestation 会带两个格式标签**（userFormat 词表的 pdf-a 与 pdf 双标记）——查询结果出现重复行属正常，按文件地址去重即可。

### 1.3 数据通道：SPARQL 端点 + 文件库直链（免 key、无会话、无浏览器）

- **查询**：`GET https://fedlex.data.admin.ch/sparqlendpoint?query={SPARQL}`，响应 JSON（SPARQL 1.1 标准结果格式）。免 key、免会话、无 cookie。查询能力覆盖全部语料（按日过滤、分页、图遍历、词表标签内联）。
- **下载**：`https://www.fedlex.admin.ch/filestore/{图内给出的路径}`——门户域文件库直链，PDF/HTML/XML/DOCX 皆可直取（2026-09-09 实测 PDF 魔数与 HTML 结构完好）。
- **robots**：门户域 `www.fedlex.admin.ch` 对自动化访问全放行（仅禁打印参数）并公布 sitemap；数据域 `fedlex.data.admin.ch` 的 robots 声明不让抓其文件库路径——因此**下载一律走门户域同路径**（两个域的文件库路径相同，门户域合规且可用）。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 无（全部请求无状态直连） |
| 请求头 | 查询需 `Accept: application/sparql-results+json`；下载无特殊要求 |
| 限额 | 无公开限额。**实测**（2026-09-09）：连发约 6 个查询后连接被瞬时断开（无状态码、响应体为空），约 3–10 分钟自动恢复；恢复后单查询正常（生产尺寸的查询响应 36.8KB / 1.7 秒）。**保持 3 秒以上间隔安全**——命令行 `--delay 3:6` 是本源的推荐节奏；框架的传输层重试会自动穿过偶发断连 |
| 反爬 | 未发现（无验证码、无 UA 检查、无 IP 封禁迹象——断连为限流行为且自愈） |
| 响应格式 | 查询：JSON（UTF-8，SPARQL 结果绑定结构）；文件：按格式（HTML/ PDF / XML / DOCX） |
| 单响应大小 | 一日窗口全要素查询约 37KB；单文件多为几十 KB 到几百 KB |
| 许可 | 门户域 robots 全放行；正文为国家法令文本 |

## 3. 抓什么：任务类型清单

每种任务 = 一次请求 + 一次解析。共 **5 种**，分属两层（参数入口也分层）：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `che_as_day`（种子，逐日一个） | SPARQL：该公布日的全要素查询（作品属性 + 三语表达 + 文件直链，一次拿全） | 每件作品一行 `as_works` 台账；每（作品 × 语言 × 格式）一个 `che_file`；当日无公布 = 合法空产出；推进日期游标 `fedlex_as_last_date` |
| `che_sr_walk`（种子） | SPARQL：SR 条目分页枚举（每页 500，翻页链） | 每条目一个 `che_sr_entry`；走完全量即收口 |
| `che_sr_feed`（种子，增量入口） | SPARQL：时点版本按 `modified`（源站变更时间戳）> 上次水位 过滤 | 每个有变更的条目重新生成 `che_sr_entry`（携带变更时间戳作更新信号）；推进水位 `fedlex_sr_last_modified` |
| `che_sr_entry` | SPARQL：单条目全量（条目属性 + 全部成员版本 + 最新适用版本的文件直链） | `sr_entries` 一行（upsert）；`sr_versions` 整组重写；锚点版每语言一个 `che_file` |
| `che_file` | GET 门户域文件库（图内直链） | 魔数校验（HTML/PDF 按格式）→ 文件落盘 + documents 一行（多语言口径见 §4） |

任务链——AS：`che_as_day(日) → che_file × (3 语 × 1 格式)`；SR 回填：`che_sr_walk → che_sr_entry × 17,299 → che_file × 条目数`；SR 增量：`che_sr_feed → che_sr_entry → che_file`。

**命令行参数**（key=value 形式；`as_*` 与 `sr_*` 前缀区分两层入口）：

```
as_window=FROM:TO   AS 层闭区间日期窗口，如 2024-01-03:2024-01-05（或改用 as_sync=1）
as_sync=1           AS 增量：起点 = 游标 fedlex_as_last_date 次日，终点 = 昨天
sr_walk=1           SR 全量回填：分页枚举全部条目（可配 max_entries 护栏）
sr_sync=1           SR 增量：从水位 fedlex_sr_last_modified 起的变更
langs=de,fr,it      语言口径（默认三语全收；SR 层有 rm/en 时照图收）
fmts=html           格式口径（默认 html；可换/加 pdf-a 等，见 §4）
max_works=N         单日实际深抓的作品数上限（护栏参数）
max_entries=N       SR 单次运行深抓的条目数上限（护栏参数）
sr=anchor|all       SR 版本口径：anchor=每条目最新适用版（默认）；all=全部时点版本
```

## 4. 数据落到哪

**三张领域表 + documents 表 + 每作品一个文件夹**。瑞士语料有两类跨文档的持久实体，判据落在表上：AS 的**公布事件**（一件作品的三语文件是一组，且 1998 年前的事件只有元数据没有文件——事件本身是数据）与 SR 的**编纂条目**（一部法跨多个时点版本）。

| 表 | 记什么 | 主键 |
|---|---|---|
| `as_works` | AS 公布事件台账：作品地址、SR 分类号、年/期/序号、公布日/制定日/生效起止、类型与机构（词表原值 + 德语标签）、三语标题、源站变更时间戳 | work_uri（作品地址） |
| `sr_entries` | SR 条目台账：条目地址、SR 分类号（可跨时代复用，如 1874 与 1999 宪法同为 101——所以主键是地址不是号）、basicAct（指回 AS 原始公布）、生效起止、效力状态码、最新版本指针 | entry_uri |
| `sr_versions` | 版本谱系：一时点一行的生效窗口（dateApplicability / dateEndApplicability）与源站变更时间戳、是否最新适用版 | (entry_uri, version_date) |
| `documents` | 一份文件一行（见下），`entity_ref` 挂靠 as_works / sr_entries | doc_id |

**多语言口径**（本源的关键设计）：**每个语言变体 = 一行 documents**。一件 2026 年的 AS 作品三语全收时是三行——各哈希自己的文件地址得各自的 doc_id，`language` 列有效（deu/fra/ita，SR 层另有 rms/eng），`title` 用该语言的原生标题，三行经 `entity_ref` 挂同一台账行。理由：三语是三份不同正文的文件（标题都不同），"一个文档号对应哪份正文"必须可答；研究端可按语言筛选，主语言选择是研究决策不是采集事实（源模型三语平权、无主语言标记）。

documents 主要字段（以 2026-09-04 公布的 `eli/oc/2026/449` 法语行实值为例）：

| 列 | 值 |
|---|---|
| `doc_id` | `CHE_20260904_{hash8(source_url)}` |
| `title` | Ordonnance du DDPS sur le personnel militaire (OPersMil)（该语言原生标题） |
| `publication_date` | 2026-09-04（公布日） |
| `issuing_authority` | Secrétariat général DDPS（机构词表德语标签的该语言对应值） |
| `source_url` | `https://www.fedlex.admin.ch/filestore/fedlex.data.admin.ch/eli/oc/2026/449/fr/html/fedlex-data-admin-ch-eli-oc-2026-449-fr-html.html` |
| `raw_format` / `language` | `html` / `fra` |
| `doc_type` | 类型词表映射的受控值；原生词（如 Ordonnance d'un département）永存 meta，未见过的类型一律 OTHER |
| `entity_ref` | `as_works:https://fedlex.data.admin.ch/eli/oc/2026/449` |
| `meta` | work_uri、identifier（RO 2026 449）、memorial_name（RO）、title_short、sr_class、seq、issue（139）、date_document（2026-08-27）、date_entry_in_force（2027-01-01）、date_no_longer_in_force、pages |

SR 版本文档行同构：`entity_ref=sr_entries:{条目地址}`、`publication_date` = 该版本的生效日（dateApplicability——该文本形态开始有效的日期，与 AS 行的"公布日"语义不同，查询时须知）、meta 另带 sr_number、version_date、version_end。

**为什么默认抓 html**（格式口径）：html manifestation 是平台的原生结构化形态——正文在 `div id="lawcontent"` 容器，标题层级/表格/条文边界保留为标记，去标签即得干净文本（实测 `eli/oc/2026/449` fr：42KB html → 1.7 万字符正文，2026-09-11）。PDF/A 版同样存在且为数字原生（非扫描），但抽取需额外依赖且结构压平。`fmts=pdf-a` 随时可加（放宽 = 新任务自动补抓，零返工）。

**文件布局**（一项政策一个文件夹，源文件名零转写）：

```
01_raw/fedlex/
├── as/2026/449/                          ← 分片层 = 卷/年（远古卷照源路径，如 as/I/45_45_47/）
│   ├── fedlex-data-admin-ch-eli-oc-2026-449-de-html.html
│   ├── fedlex-data-admin-ch-eli-oc-2026-449-fr-html.html
│   └── fedlex-data-admin-ch-eli-oc-2026-449-it-html.html
└── sr/741.01/1959_679_705_685/           ← SR 分类号 + 引入号串（防 SR 号复用撞名）
    └── fedlex-data-admin-ch-eli-cc-1959-679_705_685-20260701-de-html.html
```

## 5. 完整案例走查

**AS 侧：2026-09-04 的一个公布日**（每步为 2026-09-09 源站实测值，账本复核方式见末行）：

1. **日窗口查询**返回 2 件作品（`eli/oc/2026/449` 与 `eli/oc/2026/450`），各带 3 语表达与 4 种格式直链，共 24 行结果；
2. `eli/oc/2026/449` 的台账行：《DDPS 军事人员条例》（V Mil Pers / OPersMil / OPers mil），部门条例（Departementsverordnung），主管机构 Generalsekretariat VBS，制定日 2026-08-27、公布日 2026-09-04、生效日 2027-01-01，SR 分类号 172.220.111.310.2，AS 2026 年第 139 期第 449 号；
3. 三语 html 各落盘一份（de/fr/it），documents 三行，`entity_ref` 同挂 `as_works:…/eli/oc/2026/449`——法语行标题 "Ordonnance du DDPS sur le personnel militaire (OPersMil)"，德语行 "Verordnung des VBS über das militärische Personal (V Mil Pers)"，同一公布事件的两种语言视图。

**SR 侧：《道路交通法》（SVG，SR 741.01，1958 年法）**：

1. 条目 `eli/cc/1959/679_705_685`：1958-12-19 制定、1959-10-01 进入 SR、效力状态 In Kraft（现行）；basicAct 指回 `eli/oc/1959/679_705_685`（1959 年一次整合引入三部的公布件）；
2. 版本谱系 **151 个时点版本**（1959 年整合起点 → 历次修订各一时点 → 最新版 2026-07-01 起生效、无失效日 = 现行整合版）；
3. 锚点口径取 2026-07-01 版的三语文件（pdf-a 各 82–84 页；html 同样可得），documents 三行挂 `sr_entries:…/eli/cc/1959/679_705_685`，publication_date = 2026-07-01（该版生效日）。

**账本内计数**：待首次真实运行后补记（运行命令与三方对账结果记录在源文件 §6 对应运行的说明中）。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country che --source fedlex as_window=2024-01-03:2024-01-05 --dry-run

# AS 小窗口真实抓取（三语 html）
python cli.py collect --country che --source fedlex as_window=2024-01-03:2024-01-05 --delay 3:6

# AS 每日增量（从上次游标追到昨天）
python cli.py collect --country che --source fedlex as_sync=1 --delay 3:6

# SR 单条目试抓（护栏参数示例：《道路交通法》）
python cli.py collect --country che --source fedlex sr_walk=1 max_entries=5 --delay 3:6

# SR 增量（从上次变更水位起）
python cli.py collect --country che --source fedlex sr_sync=1 --delay 3:6

# 状态 / 快照 / 修复
python cli.py status --country che --source fedlex
python cli.py export --country che
python cli.py requeue --country che
```

## 7. 更新与增量

- **AS 日期游标 `fedlex_as_last_date`**：`che_as_day` 扫完自己那一天才推进（中途崩溃不跳日）；无公布日（周末等）也是完整消费、照推。`as_sync=1` 从游标次日追到**昨天**——当日数据已在图里（2026-09-09 当日已见 4 件，实测），但当日尚未收官、晚些时候还可能追加，故终点放昨天、次日自然补齐。
- **SR 增量水位 `fedlex_sr_last_modified`**：时点版本的源站变更时间戳（毫秒精度）是 SR 层一切变化的发现轴——新版本出现、既有版本修订都表现为时间戳更新（实测 24 小时窗口内 4 例，2026-09-09）。`sr_sync=1` 从水位起过滤变更、按条目重开（携带时间戳作更新信号，已完成的条目只有信号变新才重走）。
- **SR 全量回填 `sr_walk=1`**：与增量入口重叠无害——去重靠任务身份与完成跳过（同一任务不重执行），重叠成本只是枚举请求。
- **重开语义**：AS 日窗口重跑 = 幂等（同任务完成即跳过）；要强制重走一段历史，开新窗口即可（任务身份 = 日期）。SR 条目重开由变更信号驱动；`sr=anchor` 改 `sr=all` 是口径参数变化 = 新任务身份自动补抓全史版本，零返工。
- 1998-09-01 前的历史窗口照常可开：as_works 台账照收（事件序列完整），`che_file` 不生成（源站无文件，如实为缺、不虚记）。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **1998-09-01 前无正文文件** | 电子汇编起点；此前 41,000+ 件只有元数据（台账照收）。扫描件在联邦档案馆 bar.admin.ch，接入属另立来源 |
| 查询端点限流 | 连发触发瞬时断连（无状态码），分钟级自愈（§2）——`--delay 3:6` 推荐节奏；框架重试穿过偶发断连 |
| **猜测文件地址的陷阱** | 不存在的 filestore 地址返回 HTTP 206 + HTML 错误页（不是 404）——一切下载地址以图内 `isExemplifiedBy` 为准 + 响应魔数校验，绝不自行拼 URL |
| 条目级现行地址无文件 | SR 现行文本 = 最新适用时点版本（§1.2 要点 1）；对条目地址本身发下载请求会空手而归 |
| 《联邦公报》（fga） | 议会文献层（162,252 件），属决策过程数据，未采——需要时另立来源 |
| 条约全文 | SR 层有条约条目（元数据与版本谱系照收）；条约全文库未开 |
| SR 号跨时代复用 | SR 分类号不是唯一键（1874 与 1999 宪法同为 101）；条目主键用地址，文件夹名加引入号串防撞 |
| SR 全史版本正文 | 默认锚点口径；`sr=all` 可开（大部头如 SVG = 151 版 × 3 语，回填量大，按需） |
| Word（docx）与 XML 格式 | 未默认抓（html 已是结构化形态；xml 为同一内容的另一序列化）。`fmts=` 参数可加 |
| 罗曼什语 / 英语 | AS 层不存在（实测计数 0）；SR 层部分版本有——解析按图收，不预设语言集合 |

## 9. 端点速查表

**查询端点**：`GET https://fedlex.data.admin.ch/sparqlendpoint?query={URL 编码的 SPARQL}`（`Accept: application/sparql-results+json`；本表查询原文与真实响应样本均已随源存档，可重放复核）：

| 用途 | 查询要点（Jolux 谓词） |
|---|---|
| AS 日窗口 | `?w a jolux:Act ; jolux:publicationDate "{日期}"^^xsd:date ; jolux:legalResourceFamilyType …/resource-family/oc ; jolux:isRealizedBy ?e` + 表达/文件 OPTIONAL（一次拿全，实测 2 件日 = 24 行 / 36.8KB / 1.7s） |
| SR 条目分页 | `?e a jolux:ConsolidationAbstract` + `LIMIT 500 OFFSET n`（17,299 条 ≈ 35 页；`LIMIT 50000` 实测不截断） |
| SR 单条目 | 条目谓词 + `?v a jolux:Consolidation ; jolux:isMemberOf {条目}` + 最新适用版本 `?v2 jolux:isRealizedBy ?expr . ?expr jolux:isEmbodiedBy ?m . ?m jolux:isExemplifiedBy ?url` |
| SR 变更流 | `?v a jolux:Consolidation ; dct:modified ?mod . FILTER(?mod > "{水位}"^^xsd:dateTime) ORDER BY ?mod` |
| 词表标签 | 类型/机构/效力词表资源带 `skos:prefLabel`（多语），可内联进查询或单独解 |
| 计数 | `SELECT (COUNT(DISTINCT ?w) AS ?n)`（全量计数 3.5s，2026-09-09 实测） |

**文件下载**：`https://www.fedlex.admin.ch/filestore/{图内 isExemplifiedBy 的路径}`——路径规律为 `{eli 路径}/{语言}/{格式}/{eli 路径斜杠换横线的文件名}.{格式扩展名}`（如 `fedlex.data.admin.ch/eli/oc/2026/449/fr/html/fedlex-data-admin-ch-eli-oc-2026-449-fr-html.html`）；**规律仅供识别，不做构造**（§8 陷阱）。

**源里还有但暂未用的**：公布过程资源（pudo，每件作品的公布流程元数据）；SR 分类词表的层级树（broader/broaderTransitive——主题分类研究入口）；作品→SR 条目的正向关联（classifiedByTaxonomyEntry 已随台账收，条目级 basicAct 反向亦收）；`dct:modified`（AS 作品级变更时间戳，随台账收、未用作 AS 重开信号——公布事件不变性使然）。

---

*更新日期：2026-09-12；数据快照：2026-09-09（源站实测）；数据背书运行：待首次实跑后补记。*
