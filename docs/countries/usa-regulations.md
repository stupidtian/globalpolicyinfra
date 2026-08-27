# 美国（USA）数据源说明——regulations（行政系统规制）

> 文中覆盖范围与数量为官方数据源的稳定特征，案例均为真实数据实例。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。美国全部源总览见 [usa.md](./usa.md)。

## 1. 源概览

### 1.1 制度背景：一条联邦规制的完整一生

理解这个源要先理解制度。美国联邦规制的制定受《行政程序法》（APA, 1946）和一系列总统行政令约束，核心角色三方：**行政部门**（起草并发布规则的白宫各部与独立机构）、**白宫预算办**（OMB）下属的**信息与规制事务办公室**（OIRA，代表总统把关）、**公众**（评论期参与）。制度沿革：1981 年里根签署 EO 12291 创立总统审查与规制计划制度（1983 年发布第一份完整规制计划），1993 年克林顿的 EO 12866 确立沿用至今的现行框架。

一个规制项目典型地经历七个阶段。**每个阶段谁在做什么、留下什么信息、我们能不能拿到**，逐段说明：

**阶段 0：进入规制计划（每年春秋各一次快照）。** 各部门把"我准备立什么规"报给 OIRA，汇总为**统一议程**（Unified Agenda，每年两期；秋季那期附带**规制计划**——各部门的规制优先事项陈述）。每个规制项目从这一刻起获得终身编号 **RIN**。每条议程记录包含：标题、摘要、牵头机构、优先级类别（经济重大/其他重大/常规）、当前阶段（预规制/提案/终稿/已完成/长期搁置）、**计划时间表**（如"NPRM 目标 2026 年 11 月"，月度粒度的计划值）、法律依据、拟修改的 CFR 条款。议程本身没有"审查意见"概念——它是 OMB 汇编的官方计划书，部门自述的摘要就是全部说明。电子版 1995 年秋起。

**阶段 1：白宫审查（草案刊登前）。** 部门起草完规则草案（提案稿或终稿），**刊登 FR 之前必须送 OIRA 审查**。注意节奏：半年一次的是**议程出版**，审查则是流水线——任何部门任何一天都可以送审，2025 年全年完成 449 次审查（2005 年 610 次），平均每个工作日 1–2 条新审查，任何时刻都有百余条规则在白宫排队。每次审查留下：RIN、是哪一稿、接收日期、完成日期、**结论**（Consistent without Change / Consistent with Change / Withdrawn 等）、是否经济重大。审查记录 1981 年起完整。**审查意见的公开性分三层**：逐条修改意见不公开（只能 FOIA 申请）；退回信（OIRA 认为草案不合格时退回重议的正式信函）公开但罕见（2001 年起共几十封 PDF）；外部团体就某规则约见 OIRA 的**游说会议日志**公开（XML 数据 2024 年起，更早只有网页）。

**阶段 2：FR 刊登提案（Proposed Rule）。** 过审的草案在《联邦公报》（Federal Register，每日出版的官方公报）刊登。一份 FR 文档包含：文档号（终身唯一）、标题、类型、发布日期、**评论截止日**、RIN、docket 编号、拟修改的 CFR、摘要与全文。正文即部门的"申报理由书"：立法理由、成本收益分析摘要、逐条条款。

**阶段 3：公众评论期（通常 30–60 天）+ 部门回应。** 任何人在 regulations.gov 的 docket 下提交评论（文字+附件），部门可开听证会。评论全文公开、按 docket 汇聚——这是流程中最大的"意见库"，**需要单独的 API key，本源暂不抓**（路已铺好：FR 详情每文档带 docket 与跳转 URL）。部门对评论的回应没有单独文件——写在终稿导言的"Response to Comments"部分逐点答复，抓到终稿全文即抓到回应。

**阶段 4：白宫二审（终稿）。** 终稿草案再送 OIRA 审一次，留下第二条审查记录。所以一个 RIN 的审查记录通常 ≥2 条（提案一次、终稿一次，有中间稿的更多）。

**阶段 5：FR 刊登终稿（Final Rule）+ 生效。** 终稿刊登时带**生效日期**（effective_on，通常刊登后 30–60 天），生效后并入《联邦法规典》（CFR）——汇编层不在本源范围。

**阶段 6：后续演变。** 有错另发**纠错文档**（Correction，与原文档互相链接，原件不改）；提案可被撤回（FR 刊登 withdrawal）；也有项目悄悄死掉（议程里标 Withdrawn 或长期不再出现——判断"死了还是完成了"要靠多期议程快照对比，这正是 ua_entries 表的用途）。

两点制度性提醒（数据设计已据此安排）：

- **议程不是全生命周期的保证覆盖**：规则可能很晚才首次进入议程（第 5 节案例一的 RIN 直到终稿阶段才首次现身议程，此前中间稿已出版），也确有从未进入议程的规则。研究"全部规制"应以 OIRA 审查记录（1981 年起无洞）为底线数据，议程是计划维度的补充。全历史议程累计约 4.7 万个 RIN，其中约 2.6 万个曾送 OIRA 审查——两个集合互有出入（大量议程项目从未送审，也有规则送审了却未见于存档议程）。
- 不是所有规制文件都走全流程：总统文件（行政令、公告等）不经评论期，Notice 类很多也无 RIN；真正走完七阶段的是 Rule/Proposed Rule 类。

### 1.2 本源抓什么

按上述制度，本源抓取七个环节中的六个（评论期除外），对应三份数据：

```
阶段0 计划       阶段1 审查(提案稿)    阶段2 出版提案     阶段3 评论期      阶段4 审查(终稿)    阶段5 出版终稿+生效   阶段6 演变
统一议程    ──→  OIRA 白宫审查    ──→  FR Proposed   ──→  regulations ──→  OIRA 白宫审查   ──→  FR Final Rule    ──→  纠错/撤回
（每半年一期）   （日期+结论）         Rule              .gov docket       （日期+结论）        （effective_on）      （本次抓取）
                                                       （本次不抓）
```

三份数据、三个入口，**全部无需 API key**：

| 数据 | 覆盖 | 量级 |
|---|---|---|
| 统一议程（Unified Agenda，秋季期附带规制计划 Regulatory Plan） | 1995 年秋至今，每半年一期，共 **60 期** | 最新期 3,954 个规制项目（RIN），全历史累计十几万项目 |
| OIRA 审查记录（EO 12866 审查） | **1981 年起**按日历年 45 个文件 + 当日在审/近 30 天等 3 个滚动文件 | 每年约 400–600 次审查（2025 年 449 次）；当前时刻 153 条在审 |
| Federal Register 文档 | **1994-01-03 起**全量 | 每月约 2,300–2,800 份 |

**贯穿全流程的主键是 RIN**（Regulation Identifier Number，如 `0331-AA10`）：计划、审查、出版三边都带它，一个规制项目从计划到终稿用同一个编号串起来。辅助线是 docket 编号（FR 文档侧），因为 Notice 类文档常缺 RIN。

三线汇合已用真实规则验证（见第 5 节案例）。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**。Federal Register 与 reginfo.gov 都开放访问，`.env` 无需新增条目 |
| 限额 | 两个站均无公开限额数字，连续请求无拦截；框架统一限速（0.5–1 秒/请求）足够安全 |
| 反爬 | 均无。reginfo.gov 的网页搜索有 CSRF 表单，但 XML 直链（我们只用这个）畅通 |
| 响应格式 | FR 是 JSON；reginfo 是 XML（议程单期最大 17.6MB，审查文件约 400KB） |

## 3. 抓什么：任务类型清单

每种任务 = 一次下载 + 一次解析。共 **5 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `fr_list_page` | FR 文档清单页（`per_page=1000`，按发布日期窗口过滤） | 文档台账行（每文档一条）+ 每个文档的详情任务（deep=all 时）+ 下一页任务 |
| `fr_detail` | 单文档详情 | 台账补全（RIN/docket/生效日/评论截止/纠错链…）+ 建文档文件夹 + 正文下载任务 |
| `fr_text_dl` | 正文文件直链 | txt/xml 正文落盘 + documents 入账（一格式一档） |
| `ua_edition` | 一期统一议程 XML | rulemakings 项目行（跨期合并）+ ua_entries 期次快照 + 原始 XML 存档入账 |
| `oira_file` | 一个审查 XML（某年份，或"当日在审"滚动文件） | oira_reviews 审查行 + 原始 XML 存档入账 |

命令行参数（key=value 形式）：

```
window=FROM:TO          FR 链：发布日期在区间内的文档（如 2026-08-17:2026-08-19）
deep=none|all           FR 链：清单时是否顺带抓详情+正文（默认 none 只登记）
formats=txt,xml         正文格式（默认 txt,xml；pdf 不抓）
max_pages=N             清单链只翻 N 页（测试护栏）
cases=文档号[,..]       指定深抓的文档（无论窗口）
agenda=all|期次列表      议程链：如 all 或 202510,202504（默认不启动）
oira=all|年份列表        审查链：如 all 或 2025,2024；all 含当日在审文件
sync=1                  FR 增量：窗口起点用 kv 游标 fr_last_pub_date，终点=今天
```

FR 与 bills 的一个关键差异：**FR 文档一经发布基本不变**（有错会另发一份纠错文档互相链接），所以 FR 侧不需要"更新信号重开"机制，增量就是"发布日期 > 上次游标"往下追。

## 4. 数据落到哪

**五张领域表 + documents 表 + 两类文件落点**：

| 位置 | 记什么 |
|---|---|
| `rulemakings` 表 | **规制项目主表**，一个 RIN 一行（地位同 bills）：标题、牵头机构、优先级类别、当前阶段、是否规制计划条目、摘要、计划时间表（JSON）、法律依据、CFR 目标、首见/末见期次 |
| `ua_entries` 表 | RIN × 期次快照：同一项目每半年一行（阶段/计划条目/优先级/时间表），跨期对比就是项目的阶段演化史 |
| `oira_reviews` 表 | 一次审查一行：RIN、审查的是哪一稿（提案/终稿）、接收日期、完成日期、**结论**（Consistent with Change 等）、是否经济重大 |
| `fr_documents` 表 | FR 文档台账：文档号（主键）、类型/子类型、发布日期、**生效日期**、**评论截止日**、RIN（主关联）与全部 RIN（JSON）、docket、机构（JSON）、总统令编号、引文页码、纠错链接、各格式 URL、文件夹路径 |
| `source_snapshots` 表 | 议程/审查原始 XML 的存档记账：哪个源、哪一期、文件路径、条目数 |
| `documents` 表 | 正文文件：一格式一档，`entity_ref` 指回文档（如 `fr_documents:2026-00178`） |

文件落点（两类）：

```
01_raw/
├── policies/fr/{年}/{文档号}/          ← 一个 FR 文档一个文件夹（按年分片防膨胀）
│   ├── detail.json                    ← 详情镜像（人核对用）
│   └── text/{raw.txt, full.xml}      ← 正文两种格式
└── regulations/
    ├── agenda/{期次}.xml              ← 60 期议程原始快照（重解析不必重下，全历史数百 MB）
    └── oira/{年份}.xml                ← 46+ 个审查原始快照
```

议程/审查快照不是"一项政策的材料"，不进 policies/，路径入 `source_snapshots` 账。

## 5. 完整案例走查（两个真实规则，库内实值）

### 案例一：NEPA 实施条例撤销（RIN 0331-AA10）——迟进议程的快速规则，四环节全齐

一个 RIN 从计划到成文的全程（真实数据实例，四个环节全部入账）：

| 环节 | 记录 |
|---|---|
| 议程 | 2025 春季期首次现身（**直接以 Final Rule Stage 首次发布**——快速规则进议程可以很晚，此前中间稿已出版）；2025 秋季期标记 Completed Actions |
| OIRA 审查① | 2025-02-16 接收 → 2025-02-19 完成（中间稿，3 天，Consistent with Change） |
| FR 出版① | 2025-02-25 文档 `2025-03014`"Interim final rule; request for comments"（90 FR 10610），评论截止 2025-03-27，生效 2025-04-11 |
| 纠错 ×2 | 2025-03-05 `C1-2025-03014`（`correction_of` 列自动归一为 `2025-03014`）+ 2025-03-19 `2025-04640`（内容修正） |
| OIRA 审查② | 2025-08-11 接收 → 2025-12-02 完成（终稿，结论 **Consistent with Change**） |
| FR 出版② | 2026-01-08 文档 `2026-00178`"Final rule"（91 FR 618），**当日生效** |

审查完成（12-02）到见报（01-08）严丝合缝；四份 FR 文档 docket 同为 `CEQ-2025-0002`。库内形态：rulemakings 1 行 + ua_entries 2 行 + oira_reviews 2 行 + fr_documents 4 行 + 8 份正文文件（txt/xml 各四）分落各自年度文件夹。

### 案例二：USDA 宗教组织平等参与规则（RIN 0503-AA90）——"计划内"标准路径

2025 秋季议程条目（3,954 条之一）：

- 阶段 Proposed Rule Stage；RIN_STATUS "**First Time Published in The Unified Agenda**"（首次进议程）
- 计划时间表：NPRM 目标 2026 年 11 月（`11/00/2026`，月度粒度的计划值）
- 优先级 Other Significant；拟修改 7 CFR Part 16；法律依据 5 U.S.C. 301 等

它代表大多数规则的节奏：先进议程 → 按计划时间表推进 → 每次草案过 OIRA → 分阶段见报。项目完成后会**退出后续议程**——所以判断"死了还是完成了"必须靠多期快照对比（ua_entries 表的用途）和末见期次的状态（Completed/Withdrawn/长期搁置）。

两个案例合起来说明：RIN 匹配线在计划、审查、出版三边都成立；但议程的进入时点不可依赖（可晚进、可缺席），以 OIRA 审查记录为底线、议程为计划维度补充的取数策略由此而来（见 1.1 节提醒）。

## 6. 怎么跑

```bash
# 演练（不抓任何东西，看会入队什么任务）
python cli.py collect --country usa --source regulations \
    window=2026-08-17:2026-08-19 deep=all --dry-run

# FR 小窗口全深抓（3 天窗口约 240 文档、约 730 请求）
python cli.py collect --country usa --source regulations \
    window=2026-08-17:2026-08-19 deep=all

# 只登记不深抓（建全量索引：一个月仅 3 个请求）
python cli.py collect --country usa --source regulations window=2026-07-01:2026-07-31

# 生命周期全历史（107 个请求、约 30 万行入账、原始存档约 1GB）
python cli.py collect --country usa --source regulations agenda=all oira=all

# 每日增量（FR 从上次游标追到今天 + 当年在审名单刷新）
python cli.py collect --country usa --source regulations sync=1 oira=all

# 状态 / 快照 / 修复
python cli.py status --country usa --source regulations
python cli.py export --country usa
python cli.py requeue --country usa
```

## 7. 更新与增量

- **FR 链**：无重开机制（文档不可变）。任何**完整扫完**的窗口（含普通窗口跑）都会把 kv 游标 `fr_last_pub_date` 推到窗口末端——FR 按日期分区，扫完即完整（与按届枚举的 bills 不同）。`sync=1` 的窗口=游标→今天（无游标时要求先跑一次初始窗口）。重复运行同窗口安全：任务 ID 确定性去重，已抓的直接跳过；往更早日期回填会把游标往回带，下次 sync 多扫一段，幂等无害。
- **议程**：每半年出新期 = 新期次参数 = 新任务，自然增量；老期文件不变，抓一次即历史存档。
- **审查**：历史年份文件不变；**当年文件持续增长**（YTD 每日新增），文件头带 `RUNDATE` 作更新信号——重跑时信号变新自动重开重抓。当日在审名单（`EO_RULES_UNDER_REVIEW.xml`）每日变化，同理。
- **纠错**：纠错文档自身是正常 FR 文档，被纠错文档的 `corrections` 字段在详情里互链；无需回访已抓文档。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **评论与听证记录** | regulations.gov 的 docket（公众评论全文、听证材料），需 api.data.gov key（免费，默认 1,000 请求/时）。数据路已通：FR 详情每文档带 `regulations_dot_gov_url` + docket 编号。列为后续扩展 |
| **白宫审查的逐条意见** | OIRA 对草案文本的具体修改意见**不公开**，只能 FOIA 申请。公开的只有：审查记录（日期+结论，本次抓）、退回信 PDF（罕见，2001 年起共几十封，reginfo 网页）、游说会议日志（XML 仅 2024 起，更早只有网页） |
| **1995 年秋前的议程** | reginfo 电子版始于 1995-10；更早的规制计划只在 FR 纸面档案里。有趣的是 OIRA 审查记录反而完整覆盖 1981 年起 |
| 议程进入时点 | 见案例一：规则可到终稿阶段才首次进议程（此前出版物已存在）；以 OIRA 审查记录为底线数据可补出身 |
| 一文档多 RIN | 一份出版物可打包处理多个项目（约 400 份抽样中 2 份，如 `2026-17366` 同时撤销 3 个 RIN）。处理：首个 RIN 存 `rin` 主关联列，全部存 `rins` JSON 列 |
| RIN 缺失 | Notice 类文档常无 RIN；这些文档只能靠 docket 归组，不进 rulemakings 项目视图 |
| 大文件 | 议程单期 XML 最大 17.6MB，走现有传输无体积守卫（当前无碍，暴露问题记偏差） |
| status 视角 | `status` 只显示当前 `--source` 的领域表（框架既有行为），看全表用 sqlite 直查或 `export` |

## 9. 端点速查表

| 用途 | URL 模式 |
|---|---|
| FR 文档清单 | `federalregister.gov/api/v1/documents.json?conditions[publication_date][gte]=…&[lte]=…&per_page=1000&page=N&fields[]=…` |
| FR 文档详情 | `federalregister.gov/api/v1/documents/{document_number}.json` |
| FR 按 RIN 过滤 | 清单端点加 `conditions[regulation_id_number]=…`（官方支持） |
| FR 正文直链 | 详情返回的 `raw_text_url`（txt）/ `full_text_xml_url`（xml）/ `pdf_url`（govinfo） |
| 统一议程某期 | `reginfo.gov/public/do/XMLViewFileAction?f=REGINFO_RIN_DATA_{YYYYMM}.xml`（199510 起，10=秋季 04=春季） |
| OIRA 审查某年 | 同上 `?f=EO_RULE_COMPLETED_{YYYY}.xml`（1981 起） |
| OIRA 滚动文件 | 同上 `?f=EO_RULES_UNDER_REVIEW.xml` / `EO_RULE_COMPLETED_30_DAYS.xml` / `EO_RULE_COMPLETED_YTD.xml`（每日更新） |

**FR 类型词表**（`type` 列）：Rule / Proposed Rule / Notice / Presidential Document / Correction；总统文件另有 `subtype`（Proclamation / Determination / Memorandum 等，总统令编号在 `executive_order_number`）。

---

*更新日期：2026-08-27*
