# 德国（DEU）数据源说明——ebgbl（联邦法律公报电子版 2023 起）

> 文中覆盖范围与数量为官方数据源的稳定特征，案例均为真实数据实例（可从 `state.db` 复查）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。德国全部源总览见 [overview-zh.md](./overview-zh.md)。姊妹源：[bgbl-zh.md](./bgbl-zh.md)（1949–2022 纸质时代档案）。

## 1. 源概览

### 1.1 制度背景：从纸质档案到电子公报

自 **2023-01-01** 起，德国联邦法律的公布（Verkündung）转入**电子形式**，载体是联邦司法部运营的 [www.recht.bund.de](https://www.recht.bund.de) 下的电子《联邦法律公报》（elektronisches Bundesgesetzblatt，简称 eBGBl）——法律与法规只有在此公布才生效。2022 年及以前的纸质时代归姊妹源 `bgbl`（见总览）；本源覆盖 **2023 年起至今**。

与纸质时代的三个语义变化（数据设计据此安排）：

1. **一公布一号**：每件公布（Verkündung）独立编号，每年从 1 重新起算，**编号可带字母后缀**（如 2024 年存在 Nr. 101a、102a、165a、216a，2026 年 9 月已有 210a，2026-09-07 实测）——"一期含多条"的期概念不复存在；
2. **主文 + 可选附件**：一次公布 = 至少一个主文（Regelungstext）+ 零或多个附件（Anlage 1、2…），每件都是独立 PDF；
3. **出生即数字**：文件是数字原生的 PDF（非扫描），文本可直接抽取（实测 2024 年 Nr. 54 主文第 1 页可抽 2,447 字符干净法律文本）。

**格式口径**：PDF 是本源**唯一官方文件格式**（站方"数据提取"页明文 *"Das Dateiformat ist PDF"*；XML/HTML 全文不存在——`.xml` 直链为空页、ZIP 包内只有 PDF、条目页 HTML 只含元数据不含正文，2026-09-07 逐一实测）。机器可读的现行法 XML 属另一站点（gesetze-im-internet，见 §8）。

### 1.2 技术形态：零会话，官方明文支持程序化访问

站点明文支持自动化取数（"数据提取"服务页）：以 ELI 轮询检测新公布是**官方推荐**做法，主文/附件直链规则全部文档化。**无会话、无 cookie、无 csrf、无 API key**——全部端点纯 GET（与纸质档案源 bgbl.de 需要会话令牌形成对照）。

URL 体系三层（官方文档化）：

| 层 | 形状 | 用途 |
|---|---|---|
| 条目页 | `/bgbl/{1\|2}/{年}/{号}/VO.html` | 元数据 + 下载区（站点地图使用此式） |
| ELI 永久链 | `/eli/bund/BGBl-1/{年}/{号}` | 官方持久标识（欧洲立法标识符）；2024 年初拼写由 `BGBl_1` 改为 `BGBl-1`，旧式仍有效 |
| 文件直链 | `{ELI}/regelungstext.pdf?__blob=publicationFile`；`{ELI}/anlage1.pdf?__blob=publicationFile`…；`?view=zipdownload` 整包 | 主文 / 附件 / 打包 |

**枚举一个请求完成**：`robots.txt` 指向 `XMLSitemaps/Sitemap_Verkuendungen.xml`，2026-09-07 实测共 2,876 条（Teil I **1,504**：2023 年 415 / 2024 年 455 / 2025 年 383 / 2026 年 251 且仍在增长；Teil II 1,372，本源按 `part` 过滤掉）。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 零条目 |
| 会话 | **不需要**（对照 bgbl 源：无 cookie、无令牌） |
| 限额 | 无公开限额；robots.txt 声明 `Crawl-delay: 30`——小窗口用框架默认限速（0.5–1 秒）即可，**全量回填建议 `--delay 3:5`**（Teil I 全量约 3,000 请求，约 3.5 小时；`--delay` 是 `collect` 的运行时参数） |
| 反爬 | 未发现（无验证码、无 UA 检查迹象） |
| 响应格式 | 站点地图 XML；条目页 HTML；文件 PDF 二进制 |

## 3. 抓什么：任务类型清单（3 种）

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `ebgbl_sitemap`（种子） | 公布站点地图 XML（**一次请求 = 全量清单**） | 按 `part`/年份/期窗过滤 → 每件公布生成一个 `ebgbl_entry`；无匹配为合法空 |
| `ebgbl_entry` | 条目页 HTML | 解析元数据块（类型/编号/两日期/主管部委/主题/索引号）与下载区 → **每个文件**（主文 + 各附件）生成一个 `ebgbl_pdf` |
| `ebgbl_pdf` | 文件直链 | PDF 落盘 + `documents` 入账（一文件一档） |

任务链：`ebgbl_sitemap → N × ebgbl_entry → (主文+附件) × ebgbl_pdf`。

命令行参数（key=value）：

```
part=1            仅 Teil I（传 2 报错：Teil II 不在本源范围）
year=2023         必填，2023 起无上界（2022 及以前请用 --source bgbl）
nrs=1-3           期号窗：区间 1-3（纯数字，即 1、2、3，不含 3a）/ 列表 1,3,3a（逐个精确匹配，支持字母后缀）/ 缺省全年
```

与 bgbl 源的一个简化：**无需过滤规则**——站点地图的每个 URL 就是一件公布，不存在"整期合集/目录页/指引行"三类干扰行（bgbl 源需三排除）。

## 4. 数据落到哪

**零领域表、零 kv**（扁平文档型，与 bgbl 同型）：一切进 `documents`，**每个文件一行**——主文与各附件各一行，`meta.file_kind` 区分（`regelungstext` / `anlage1`…），`meta.nr` 与 `meta.eli` 串联同一件公布的全部文件。

| 列 | 内容 |
|---|---|
| `doc_id` | `DEU_{公布日YYYYMMDD}_{hash8(source_url)}`，公布日 = Veröffentlichungsdatum |
| `title` | 条目标题全称（条目页主标题）；附件行加后缀 ` – Anlage N` |
| `publication_date` | 公布日；签署日（Ausfertigungsdatum）另存 `meta.ausfertigungsdatum` |
| `source_url` | ELI 文件直链规范形式 `…/eli/bund/BGBl-1/{年}/{号}/{文件}.pdf?__blob=publicationFile`（剥页面链接中的 `&v=N` 版本参数，确定性可重建） |
| `doc_type` | 官方 `Typ` 字段软映射：Gesetz→`STATUTE`、Verordnung→`REGULATION`、其余→`OTHER`；原词整段存 `meta.typ` |
| `issuing_authority` | Federführung（主管部委），如 `Bundesministerium für Arbeit und Soziales` |
| `raw_format` / `language` | `pdf` / `deu` |
| `entity_ref` | NULL |
| `meta` | `part`、`year`、`nr`（含字母后缀原样）、`eli`、`typ`、`ausfertigungsdatum`、`federfuehrung`、`sachgebiete`、`fna`、`gesta`（仅 Gesetze 有）、`citation`、`file_kind` |

文件落点（与 bgbl 同一棵树——同一公报的两个时代；2023 起 `Nr_{号}` 文件夹承载单件公布）：

```
{data_root}/DEU_policy/
├── state.db
├── failures/
└── 01_raw/bgbl/
    ├── I/2020/Nr_01/bgbl120s0002.pdf        ← bgbl 源：期文件夹（多条目）
    └── I/2023/Nr_001/
        ├── regelungstext.pdf                 ← ebgbl 源：主文
        └── anlage1.pdf …                     ←（如有）附件同居
```

## 5. 完整案例走查（2023 年 Teil I Nr.1–3，实测值；库内值随窗口实跑回填）

1. **清单**：`ebgbl_sitemap` 一次取回全量，按 `part=1 year=2023 nrs=1-3` 过滤出三件公布。
2. **Nr.1**（条目页实测字段值）：标题 **Erste Verordnung zur Änderung der Baustellenverordnung**；Typ `Verordnung`；公布日 `04.01.2023`；签署日 `19.12.2022`；Federführung `Bundesministerium für Arbeit und Soziales`；FNA `805-3-5`；Sachgebiet `Arbeitsschutz`；引用 `BGBl. 2023 I Nr. 1 vom 04.01.2023`；下载区仅主文 `regelungstext.pdf`（无附件）。
   - 注意签署日（2022-12-19）早于跨年公布日（2023-01-04）——公布日为主日期、签署日入 meta 的口径与 bgbl 源一致。
3. **Nr.2 / Nr.3**（同页实测）：公布日均为 `06.01.2023`；标题分别为 *Verordnung zur Durchführung der Erstattung von Mitteln aus der Finanzdisziplin…* 与 *Verordnung zur Anpassung von Rechtsverordnungen an das Tierarzneimittelrecht*；Typ 均 `Verordnung`，均单文件；`GESTA` 字段不出现（该字段仅法律类有条，如 2024 年 Nr. 54）。
4. **窗口合计**（2026-09-07 实跑库内值）：7 任务全 done（清单 1 + 条目 3 + 下载 3）、3 份主文 PDF（278,907 / 280,138 / 304,174 字节）、3 行 documents——doc_id 实例 `DEU_20230104_86b3482a`（Nr.1）、`DEU_20230106_2b52935f` / `DEU_20230106_b8b90264`（Nr.2/3，同日公布）；`issuing_authority` 列首次启用（Nr.1 = Bundesministerium für Arbeit und Soziales）。

## 6. 怎么跑

```bash
# 演练（不入队执行，看计划）
python cli.py collect --country deu --source ebgbl part=1 year=2023 nrs=1-3 --dry-run

# 小窗口（上节案例）
python cli.py collect --country deu --source ebgbl part=1 year=2023 nrs=1-3

# 某一年全量（建议放慢限速，尊重站方 robots 声明）
python cli.py collect --country deu --source ebgbl part=1 year=2024 --delay 3:5

# 当年追新（活源：重跑即重拉清单，已完成条目自动跳过）
python cli.py collect --country deu --source ebgbl part=1 year=2026

# 状态 / 快照 / 修复
python cli.py status --country deu --source ebgbl
python cli.py export --country deu
python cli.py requeue --country deu
```

## 7. 更新与增量

- **活源、无游标**：清单任务的**重开信号 = 当天日期**——当天重复运行全跳过（幂等，实测零请求零重下载）；隔天运行自动重拉站点地图，新 URL = 新任务，已完成条目依旧跳过（无会话依赖，任务天然可跳过）。当年（进行中）定期运行即持续追新。
- 官方备选通知渠道：RSS 订阅与 Newsletter（不依赖，记录备查）。
- 已完结年份（2023–2025）内容稳定；条目一经公布不变（与 FR 类似的纠错另立条目语义）。

## 8. 已知边界与缺口

| 项 | 说明 |
|---|---|
| **Teil II 不抓** | 站点地图含其全量（1,372 条，2026-09-07 实测），结构同构；开抓只需放开 `part` 过滤，零探查成本 |
| **机器可读 XML 未开工** | 现行法整合文本的 XML 在 gesetze-im-internet（联邦司法部同族站点）——那是"现行整合文本"而非"公布时文本"，属另一源（见总览 §3） |
| 附件为可选 | 抽样 17 件均为单文件（仅主文）；含附件条目解析按条目页下载区实际链接自适应，不预估 |
| `GESTA` 字段 | 仅法律（Gesetz）类条目出现，法规（Verordnung）类无——按可选字段处理 |
| 字母后缀编号 | 年内编号如 `101a`（§1.1）；`nrs` 区间不含后缀编号，需要时用列表逐个列出 |
| 年份分界 | 2022 及以前属 `bgbl` 源（`--source bgbl`，覆盖 1949–2022）；传错年份各自报错并指向对方 |
| 当年进行中 | 当年编号持续增长（2026 年 9 月 251 件），追新见 §7 |

## 9. 端点速查表

均位于 `https://www.recht.bund.de/` 下：

| 用途 | 端点 |
|---|---|
| 公布清单 | `XMLSitemaps/Sitemap_Verkuendungen.xml`（robots.txt 指路；`/bgbl/{部}/{年}/{号}/VO.html` 形状的 URL 全集） |
| 条目页 | `/bgbl/{1\|2}/{年}/{号}/VO.html`（元数据块 = `role="listitem"` 的 strong/span 对） |
| ELI 永久链 | `/eli/bund/BGBl-1/{年}/{号}`（新式拼写；旧式 `BGBl_1` 仍重定向有效） |
| 主文 PDF | `{ELI}/regelungstext.pdf?__blob=publicationFile` |
| 附件 PDF | `{ELI}/anlage1.pdf?__blob=publicationFile`、`anlage2.pdf`…（官方命名规则） |
| 整包 ZIP | `{ELI}/?view=zipdownload`（本源不用，逐文件直取） |
| 限速声明 | `robots.txt`（`Crawl-delay: 30`；运行时用 `--delay` 调节） |

**源里还有但暂未用的**：RSS / Newsletter（新公布通知）；站内 Recherche 检索（按条目抓全量更完整）；`?view=zipdownload` 整包。

---

*更新日期：2026-09-07；数据快照：2026-09-07；数据由 2023 年 Nr.1–3 窗口实跑背书（7 任务零失败、3 份 PDF 全量入账，标题/日期/部委/字节数与站点逐项核对一致；幂等重跑与隔日信号重开均实测验证）。*
