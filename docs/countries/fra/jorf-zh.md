# 法国（FRA）数据源说明——jorf（官方公报 JORF）

> 数据快照日期：2026-08-28。文中条目计数与字节数均为当日实测的真实值（可重放复核）；§5 库内计数为 2026-08-28 首次试跑实值。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。法国全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：JORF 是什么、装了谁的产出

**JORF**（*Journal officiel de la République française*，《法兰西共和国官方公报》）是法国**中央层级一切规范文件的唯一法定公布媒介**——法律与法规只有在此公布才对第三人发生效力，地位相当于美国的"Federal Register 刊登 + 法律颁布通告"合一体。运营方是 **DILA**（Direction de l'information légale et administrative，法律与行政信息局），对外门户是 Légifrance（legifrance.gouv.fr）。

理解这个源的关键，是先分清"两个系统的产出"与"一个系统的过程"：

| 系统 | 产出（在 JORF） | 过程（不在 JORF） |
|---|---|---|
| **立法系统** | LOI（法律，议会通过、总统颁布后刊出）、ORDONNANCE（条例，政府行使授权立法）、INFORMATIONS_PARLEMENTAIRES（议会信息） | 法案、修正案、辩论、表决——这些在国民议会/参议院自己的系统里（senat.fr / assemblee-nationale.fr），本源不含 |
| **行政系统** | DECRET（法令：总统令/总理令/部长令）、ARRETE（部委令）、AVIS（公告）、DECISION（机构决定） | 规章的执行细则汇编在代码版库（LEGI） |
| 独立机构 | 宪法法院、CNIL、Arcom 等机构的 DECISION / AVIS | — |

一句话：**JORF 抓的是"成品规范"，不抓"过程"**。日常一期以行政产物为绝对主体——2026-08-26 那期（n°0198，81 条文本）的构成：ARRETE 36、AVIS 26、DECRET 12、INFORMATIONS_PARLEMENTAIRES 4、DECISION 2、ANNONCES 1，**LOI 为 0**——法律只在颁布日出现，一天 0–3 条是常态。研究"立法过程"需要另外抓议会数据；研究"政府实际产出了什么规范"，JORF 一张网全收。

**出版节奏**：**周二至周日**每日一期（每周 6 期）——周一无"法律与法令"版（2026 年 8 月四个周一实测全部仅存维护 diff 包），个别节日停刊（如 2025-12-25 圣诞当天连 diff 都没有）。每期有年度连续期号（`NUM_PARUTION`，如 2026 年第 0198 期）。

### 1.2 与欧盟法的关系（三层）

研究者用法国数据做政策分析时须知 EU 法的两条渗透渠道，与德国 BGBl 的结构完全同构：

1. **转化立法——在 JORF 内，正常逐条抓取。** 法国把 EU 指令转化为国内法用的是普通 loi / ordonnance / décret，与本国立法同通道刊出，标题常点名（如 `LOI n° 2023-171 du 9 mars 2023 portant diverses dispositions d'adaptation au droit de l'Union européenne...`，2026-08-28 实测在库）。它们是法国本国法，按普通条目处理。
2. **直接生效的 EU 条例——不在 JORF。** EU 条例（règlement (UE)）在《欧盟官方公报》发布后对法国直接生效，不经国内转化、不在 JORF 公布。需要 EU 条例原文须去 OJ EU，超出本源范围。
3. **无年度引用索引。** 德国 BGBl 有 Fundstellennachweis 索引卷，法国没有对应物；EU 维度的回溯线索散落在各文本标题与 LIENS 引用里，属研究侧后处理。

**一个容易混淆的概念澄清：ELI ≠ EU 标记。** ELI（European Legislation Identifier）是全欧洲统一的立法 URL 编号方案，法国给自己**所有**本国法（无论是否涉及 EU）都逐步编 ELI。一条文本有没有 ELI 与它是不是 EU 转化来的完全无关。识别 EU 转化文本靠标题（`directive (UE)`、`adaptation au droit de l'Union européenne` 等字样）与引用关系，不靠 ELI。

### 1.3 数据通道：DILA 开放数据目录（免 key、无浏览器）

Légifrance 网站本身有 Cloudflare 防护，对非浏览器客户端返回 403；但 DILA 把同一份数据以**开放数据**形式放在一个纯 HTTP 目录上，这就是本源的通道：

```
https://echanges.dila.gouv.fr/OPENDATA/JORF/
```

Apache 目录列表，免 key、无反爬、无会话。内容按日打包（tar.gz），并有一个全量快照：

| 文件 | 含义 |
|---|---|
| `JORF_{YYYYMMDD}-{HHMMSS}.tar.gz` | **每日增量包**，2025-07-13 起累积（404 个日期、754 个文件，2026-08-28 实测）。每天 0–2 个：**较早的包（约 00:25–03:09 生成）= 当天一期的完整内容**；较晚的包（约 20:30–22:15）= 全库当日维护 diff |
| `Freemium_jorf_global_20250713-140000.tar.gz` | **全量快照（stock）**，1.6 GB，覆盖 1990 年起的全部全文——历史回填用（见 §8） |

**早包 / 晚包的语义区分是本源最重要的机制**（2026-08-26/27、2025-12-22 三日期实测复核）：

- **早包 = 当天一期完整内容**：恰好 1 个期目录（conteneur）+ N 条文本（version 元数据 + struct 结构）+ 各文本的 article 正文，全部属于当日期号（81/81 条 NUM_PARUTION=0198）。这就是"出版事件"。
- **晚包 = 全库当日维护 diff**：当天被碰过的所有文件无论多老都重发一遍。2026-08-26 晚包 192 条文本中 113 条出版于 1993–2025 年，其中 96 条当天拿到了补发的 ELI 标识——这是 DILA 的**后台维护作业**（ELI 逐步回填、文献部门事后补关键词 mots-clés、新文本引用旧文本时给旧文本补反向链接、元数据纠错），**不是法律内容被修改**。
- **包是不可变的冻结文件**：文件名自带生成时刻，2025-07-13 生成的包至今 mtime 未变。晚包里的修改永远只存在于那个晚包里，不会渗透进任何早包。

由此推出本源的**数据口径**：抓早包得到的每条文本 = **出版日晨间的原样形态**（as-published）。出版后补的元数据（SGG 关键词、ELI、反向引用）不在早包里——实测早包 81 条文本：书目字段（ID/NOR/NATURE/NUM/期号/日期/标题/部委）**无一缺失**，SGG 关键词 0/81（官方设计：公报先原样出版、文献部门事后增补）、ELI 28/81（出版时部分分配，无固定规律）。这不是数据缺陷而是口径选择；需要"增补态"时走晚包 diff 或年度 stock（§8）。

**包内 XML 结构**（一天的真实计数）：

| 目录 | 内容 | 根元素 | 本源是否使用 |
|---|---|---|---|
| `jorf/global/texte/version/` | 文本元数据（题录/文号/日期/部委/关键词/引用）+ 通告/签证/签署栏 | `TEXTE_VERSION` | **是**（文档主文件） |
| `jorf/global/texte/struct/` | 文本结构（文章清单与次序） | `TEXTELR` | 是（每文本一份） |
| `jorf/global/article/` | 单篇文章正文（XHTML 内嵌于 `BLOC_TEXTUEL/CONTENU`），自带所属文本 id | `ARTICLE` | **是**（正文所在） |
| `jorf/global/conteneur/` | 期目录（层级树 + 全部条目引用） | `JO` | 解析做对账，不落盘 |
| `jorf/global/section_ta/`、`jorf/global/eli/` | 章节结构、ELI 映射 | — | 否（§8） |

姊妹目录 `JORFSIMPLE/`（同结构简化版）不使用。journal-officiel.gouv.fr 上的查询 API 只覆盖协会公告（JOAFE/BALO），不含本版，勿混淆。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 无（无 cookie、无 token；与 bgbl.de 那类需建会话的源不同） |
| 限额 | 无公开限额。2026-08-28 实测连续数十请求无拦截；框架统一限速（0.5–1 秒/请求）足够安全 |
| 反爬 | 无（Apache 目录直链，curl 默认 UA 即可访问） |
| 响应格式 | 目录索引是 HTML（ISO-8859-1，约 130 KB）；数据包是 tar.gz，包内 XML 为 UTF-8 |
| 许可 | **Licence Ouverte 2.0**（免费复用），再分发须署名：数据来源 DILA + 下载长 URL + 文件名与文件日期 |

另一条官方通道 **Légifrance API**（经 PISTE 平台，piste.gouv.fr 免费注册）数据更即时，但鉴权是 OAuth2 令牌交换（`oauth.piste.gouv.fr/api/oauth/token`），本框架传输层暂只支持单 key 注入，故未使用——开放数据目录已覆盖同等内容。

## 3. 抓什么：任务类型清单

每种任务 = 一次下载 + 一次解析。共 **2 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `jorf_index`（种子） | GET 目录索引页 | 解析文件名 → 只认**正午前生成**的包（期包实际落在 00:15–07:00，404/404 天两簇无交叠）→ 窗口内每个日期取其中最早者 → 每个日期生成一个 `jorf_issue`；窗口内无任何日期（周一/停刊日/越界）→ 合法空产出 |
| `jorf_issue` | GET 该日期包 tar.gz（典型 100–400 KB） | 内存解包：**只登记出版日 = 任务日的文本**（安全网：维护 diff 无当日文本 → 合法空产出，不污染窗口）；每条文本一个文档记录 + 落盘（version/struct/articles 三类文件）；推进游标 `jorf_last_date` |

任务链：`jorf_index → jorf_issue × 每个出版日`。**一请求 = 整期**（元数据+结构+正文全在一个包里），这是本源与逐条下载源的最大差异——两天窗口只需 3 个请求。

命令行参数（key=value 形式）：

```
window=FROM:TO    闭区间日期窗口，如 2026-08-26:2026-08-27（必填，或改用 sync=1）
sync=1            增量：起点 = 游标 jorf_last_date 的次日，终点 = 今天
```

**为什么必须先抓索引**：文件名里的时间戳（如 `JORF_20260826-002510`）逐日不同、无法从日期构造（实测去掉时间戳的猜测 URL 返回 404）；且停刊日完全没有文件。所以枚举的唯一可靠入口就是解析索引页本身。

## 4. 数据落到哪

**零领域表**（扁平文档型路径，同德国 BGBl）：JORF 条目即文档本体——公报刊出即定（修正以新文本出现，见 §7），无生命周期、无关联实体。一切研究字段进 `documents` 一张表：

| 列 | 内容 |
|---|---|
| `doc_id` | `FRA_{出版日YYYYMMDD}_{hash8(source_url)}` |
| `title` | 完整题名（TITREFULL，如 `Avis relatif aux prix de spécialités pharmaceutiques publiés en application de l'article L. 162-16-6 du code de la sécurité sociale`） |
| `publication_date` | 期出版日（DATE_PUBLI）；文本自身签署日另存 meta.date_texte |
| `issuing_authority` | 部委（MINISTERE），空时取机构（AUTORITE） |
| `source_url` | `https://www.legifrance.gouv.fr/jorf/id/{JORFTEXT id}`——DILA 数据库主键构造，规范可重建；也是 Légifrance 页面的"正门"URL |
| `raw_format` / `language` | `xml` / `fra` |
| `doc_type` | `OTHER`（软处理；法语原词 nature 进 meta，跨国类型学留给后续 ontology 阶段） |
| `entity_ref` | NULL（扁平国家） |
| `meta` | `nature`（LOI/DECRET/ARRETE/AVIS/ORDONNANCE/DECISION/…）、`num`（编号如 2026-816）、`nor`（文号如 PRMJ2432005D）、`num_parution`（期号）、`num_sequence`、`date_texte`（签署日，占位值 2999-01-01 原样保留）、`origine_publi`（JORF n°0198 du 26 août 2026）、`page_deb_publi` / `page_fin_publi`（已知源数据有脏值如 19970101，原样字符串）、`titre_court`、`cid`、`ancien_id`、`ministere` / `autorite`、`mcs`（SGG 关键词，分号连接——注意早包通常为空，见 §1.3）、`n_articles`、`files`（该文档文件夹的文件清单） |

文件落点（"一项政策一个文件夹"，年/期分片）：

```
{data_root}/FRA_policy/
├── state.db
├── failures/
└── 01_raw/jorf/
    └── 2026/N0198/                          ← 年 = 出版年；期 = 文本自身 NUM_PARUTION
        └── JORFTEXT000054747463/            ← 一条文本一个文件夹（数据库 id 命名）
            ├── version.xml                  ← 元数据 + 通告/签证/签署（文档主文件）
            ├── struct.xml                   ← 结构（文章清单与次序）
            └── articles/
                └── JORFARTI000054747464.xml ← 正文（保留源文件名零转写）
```

- version.xml 是文档主文件（唯一挂 doc_id 的文件，账本 local_path 指向它）；struct 与 articles 同落该文件夹，文件清单记入 meta.files。
- article 靠自身携带的所属文本 id（`CONTEXTE/TEXTE@cid`）归位，不依赖外部映射；实测一天 204 篇 article 全部可归位、81 条文本全部有正文。
- 防御性回退：老式期（增量包未见过，stock 里的 1990 年代数据有）可能没有期号——期层回退用 `D{YYYYMMDD}`。

## 5. 完整案例走查（2026-08-26 一期，2026-08-28 试跑库内实值）

一个真实出版日的全链数据（每步可重放）：

1. **索引**：目录页列出 `JORF_20260826-002510.tar.gz`（期包，143,937 字节）、`-135605`（午后重推）与 `-214758`（维护 diff，4,160,999 字节），窗口过滤后取期包。
2. **解包对账**：包内恰 1 个期目录 `JORF n°0198 du 26 août 2026`、81 条文本（version/struct 各 81、一一对应）、204 篇 article（零孤儿）、188 个 ELI 映射（只用 28 个属于当日期的做核对）。
3. **文本入账示例**（AVIS 类）：`JORFTEXT000054747463`，题名 `Avis relatif aux prix de spécialités pharmaceutiques...`，NOR `SFHS2621527V`，期号 0198，签署日占位 2999-01-01，部委 `Ministère de la santé, des familles...`；文件夹 `01_raw/jorf/2026/N0198/JORFTEXT000054747463/`，含 version.xml + struct.xml + 1 篇 article（`JORFARTI000054747464`，正文是药品价格表）。
4. **类型分布**（库内实值）：ARRETE 36 / AVIS 26 / DECRET 12 / INFORMATIONS_PARLEMENTAIRES 4 / DECISION 2 / ANNONCES 1。
5. **窗口合计**（2026-08-26:27 两期，库内实值）：**3 任务全 done、182 条文档、926 个文件**（182 version + 182 struct + 562 article）、游标 `jorf_last_date=2026-08-27`；`N0198/`（81 个政策文件夹）与 `N0199/`（101 个）两棵期树落地。重复运行同窗口零请求（任务确定性跳过）。
6. **三方对账**：源站期目录（conteneur）81 个条目 ≡ 包内 81 条文本 ≡ 库内 81 行文档——标题多重集逐一相同（含 10 条重名标题）；两日全部文档 local_path 齐备、`meta.n_articles` 合计 562 与落盘 article 数吻合。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country fra --source jorf window=2026-08-26:2026-08-27 --dry-run

# 小窗口真实抓取（上面 §5 的口径：3 请求、182 文档）
python cli.py collect --country fra --source jorf window=2026-08-26:2026-08-27

# 每日增量（从上次游标追到今天；当天早包尚未生成时该日自动留到下次）
python cli.py collect --country fra --source jorf sync=1

# 状态 / 快照 / 修复
python cli.py status --country fra --source jorf
python cli.py export --country fra
python cli.py requeue --country fra
```

## 7. 更新与增量

- **游标**：`jorf_last_date`。每个 `jorf_issue` 完成**自己那一天**才把游标推到该日——中途崩溃不会跳过未完成的日期；当天早包尚未生成（约巴黎时间 00:25 前）则该日无任务、游标不动，下次 sync 自愈。
- **抓的是不可变快照**：早包在生成时刻就冻结（§1.3），今天下载和一年后下载字节相同；重复运行同窗口安全（任务确定性去重，已抓直接跳过）。
- **文本刊出即定，无重开机制**：法国规矩是修正走新文本（新 id、新期），旧文本原文永不改；改的只是元数据层（ELI/关键词/反向引用），且只体现在晚包 diff 里——本源不设更新信号，同德国冻结档案的处理。
- 往更早日期回填会把游标往回带，下次 sync 多扫一段，幂等无害（与 usa/regulations 同判例）。
- 2025-07-13 之前的日期在增量目录里不存在，抓不到也不应去抓——历史走 stock（§8）。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **晚包（维护 diff）不抓** | 出版后补的 ELI、SGG 关键词（mots-clés）、反向引用不进库——口径是 as-published（§1.3）。需要"增补态"时走晚包 diff 或年度 stock 幂等刷新，属后续扩展 |
| **历史回填（1990–2025-07-12）** | 增量目录只从 2025-07-13 起。历史在 1.6 GB 全量 stock（官方每年至少重出一个，含旧 stock+期间全部维护），需专门的下载与解包策略，另行立项 |
| section_ta / eli 不落盘 | 章节结构树与 ELI 映射文件不抓。正文完整性不受影响（article 自包含）；ELI URL 若研究需要，可日后从 eli/ 文件补映射 |
| 停刊日与周一 | 周一无"法律与法令"版（只有维护 diff 包）、节日可能全无文件：这些日期不生成任务，属正常；索引侧靠"正午前生成"判别期包，解析侧另有"文本出版日 = 任务日"安全网兜底 |
| 同日二次推送 | 个别日期有正午前的重推包（全库一年仅 1 例 07:04 与 9 例午后文件）：取的是**最早**一期包，重推内容不追（其变动最终体现在维护 diff 里，见上条边界） |
| 源数据脏值 | 个别老文本 `PAGE_FIN_PUBLI` 存脏值（如 19970101）、签署日占位 2999-01-01——一律原样字符串入库，不做数值解释 |
| 游标可回退 | 乱序窗口会拉回游标，下次 sync 幂等重扫（无害，见 §7） |
| JORFSIMPLE | 同目录下的"简化版"姊妹数据集，与 JORF 平行同构，未使用 |
| Légifrance API | OAuth2 鉴权（PISTE 平台），传输层暂不支持令牌交换，未使用（§2）；内容与开放数据目录等价 |

## 9. 端点速查表

| 用途 | URL 模式 |
|---|---|
| 目录索引（枚举唯一入口） | `https://echanges.dila.gouv.fr/OPENDATA/JORF/`（HTML，ISO-8859-1） |
| 每日早包 | `https://echanges.dila.gouv.fr/OPENDATA/JORF/JORF_{YYYYMMDD}-{HHMMSS}.tar.gz`（时间戳以索引为准，不可构造） |
| 全量 stock | `https://echanges.dila.gouv.fr/OPENDATA/JORF/Freemium_jorf_global_{YYYYMMDD}-{HHMMSS}.tar.gz`（1.6 GB） |
| 文本正门 URL（source_url 基底） | `https://www.legifrance.gouv.fr/jorf/id/{JORFTEXT id}`（浏览器可开；采集不走此通道） |
| Légifrance API（未用） | token `https://oauth.piste.gouv.fr/api/oauth/token`（OAuth2 client_credentials）→ `https://api.piste.gouv.fr/dila/legifrance/...` |

**NATURE 词表**（meta.nature 观测值）：LOI / ORDONNANCE / DECRET / ARRETE / AVIS / DECISION / INFORMATIONS_PARLEMENTAIRES / ANNONCES（一天实测即此八种；stock 里另有老类别，解析不做白名单限制）。

---

*更新日期：2026-08-30（规范翻新，内容未动）；数据快照：2026-08-28；数据由 window=2026-08-26:2026-08-27 实跑窗口背书（3 请求、182 文档、926 文件，三方对账一致）。*
