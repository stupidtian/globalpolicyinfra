# 挪威（NOR）数据源说明——lovtidende（挪威法规公报 Norsk lovtidende）

> 数据快照日期：2026-09-03。文中条目计数、字节数与状态码均为当日对源站直连实测的真实值（可重放复核）；账本计数已在首次真实运行后补记（§5 末行）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。挪威全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：Norsk lovtidende 是什么、装了谁的产出

**Norsk lovtidende**（挪威法规公报）是挪威**全国性规范的法定公布媒介**——法律（lov）与中央法规（forskrift，部委依法律授权制定的委任立法）只有在此公布才对第三人具有效力。公报由 **Lovdata 基金会**（Stiftelsen Lovdata，私营基金会）受**司法与应急部**（Justis- og beredskapsdepartementet）委托出版，门户 lovdata.no。

公报分两部（avdeling），内容边界分明：

| 部 | 名称 | 内容 | 本源是否采集 |
|---|---|---|---|
| **Del I** | 全国性规范 | 法律（lov）、中央法规（sentral forskrift）、施行与授权决定、税收决定等公布 | **是（法律 + 中央法规两类文档，见 §8）** |
| Del II | 地方性规范 | 县级/市级法规（regionale og lokale forskrifter） | 否（另一公布体系，无整包数据） |

**出版节奏**：电子公报每个工作日发布（`lovtidend-avd1-2026.tar.bz2` 当年包每日晨间约 01:30 UTC 重建，2026-09-03 实测当日 01:31 已刷新）。**电子公布自 2001 年起为官方公布形式**（Lovdata 官方文章明示；此前为印刷版，印刷版 2016 年后停刊、2017-01-01 起纯电子）。一个日历年典型量为 **1,200–2,300 条**（2001–2025 逐年实测：最低 2011 年 1,172 条、最高 2021 年 2,289 条）。

**不在本源里的东西**：议会立法过程（Storting 议会系统，另立数据源；但法律条目自带的议会过程说明串会无损收进 meta，§4）、现行有效版本的法规汇编（另有两份"现行法律/现行中央法规"整包，版本序列素材，§9）、地方性法规（Del II）、判例（法院判决）。

### 1.2 数据通道：Lovdata 官方开放数据整包（免 key、无会话、无浏览器）

Lovdata 在其 API 站点提供**官方开放数据整包下载**，登记于挪威国家开放数据目录 data.norge.no（数据集 "Norsk Lovtidend, Avdeling I"，**NLOD 2.0** 许可——挪威开放政府数据许可，允许商用与非商用再利用，须署名）。本源用其中两个端点：

**① 整包清单**（发现入口，不硬编码任何文件名）：

```
GET https://api.lovdata.no/v1/publicData/list
```

返回 JSON 数组，每项含 `filename` / `description` / `sizeBytes` / `lastModified`（2026-09-03 实测 4 项）。其中与公报相关的两包：

| 文件名 | 内容 | 大小 | lastModified（实测） |
|---|---|---|---|
| `lovtidend-avd1-2001-2025.tar.bz2` | Del I **2001–2025 完整档案**，38,182 个 XML | 69,298,008 字节 | 2026-08-27T01:30Z（低频重建） |
| `lovtidend-avd1-2026.tar.bz2` | **当年（2026）包**，截至当日 961 个 XML | 1,383,606 字节 | 2026-09-03T01:31Z（每日重建） |

**② 整包下载**：

```
GET https://api.lovdata.no/v1/publicData/get/{filename}
```

包内布局 `lti/{年}/{前缀}-{YYYYMMDD}-{序号}.xml`，前缀 `nl` = 法律、`sf` = 中央法规；**一公报条目一 XML 文件**，2001 年与 2026 年形状同构（2026-09-03 全库核查：39,143 文件无一例外）。文件是良构的 XHTML（可用标准 XML 解析器读取）：头部一段键值元数据 + 正文全文，**原样字节即文档本体**。

条目文件名的一个口径要点：**文件名日期 = 制定日**（文号日期），序号是年内的类型流水号（`nl-20260123-001` ↔ 文号 `LOV-2026-01-23-1`）。公报公布日常**晚于**制定日 1–11 天（2026 年包 961 条实测：685 条公布日 ≠ 制定日），研究时间序列应以公布日（kunngjort 字段）为主锚，§4。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 无（无 cookie、无 token） |
| 请求头 | 无特殊要求（JSON 端点直接 GET） |
| 限额 | HTTP 响应头 `X-RateLimit-Limit: 200`（按分钟窗口，官方 swagger 明示；超限答 429）。本源每次运行 1–3 个请求，远低于限额 |
| 反爬 | 无（API 站点直连即可） |
| 许可 | **NLOD 2.0**（国家开放数据目录登记）：允许商用与非商用再利用，**须署名**——引用格式 *"Kilde: Stiftelsen Lovdata"* 并附 api.lovdata.no / lovdata.no 链接 |

**一个重要的合规边界**：Lovdata 的**网页站**（www.lovdata.no，含公报登记册与文档页）robots.txt 对普通爬虫**全站禁抓**（2026-09-03 实测：`User-agent: *` → `Disallow: /`）。本源的一切采集都走上述 API 整包通道，不抓任何网页；API 站点 robots 同样全禁，但该站是有官方文档、有限速管理、分发 URL 登记进国家开放数据目录并挂 NLOD 2.0 许可的**文档化 API**——按其公开端点取数是发布方明示的预期用法。

## 3. 抓什么：任务类型清单

每种任务 = 一次下载 + 一次解析。共 **2 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `lt_list`（种子） | GET 整包清单 ① | 对清单里每个 `lovtidend-avd1-*` 包生成一个 `lt_pack` 后继任务，携带包的"身份戳"（大小@修改时间）进任务参数；`gjeldende-*`（现行汇编）两包忽略 |
| `lt_pack` | GET 整包下载 ②（档案包与当年包各一个任务） | 解压扫描包内全部条目 → 每条一个文档记录 + 一个文件落盘（成员字节原样）。包内 0 条目 → 记合法空产出（年初首条发布前可能出现） |

任务链：`lt_list × 1 → lt_pack × 每包 1 个`。**一个包的全部条目在一个任务内一次入账**（当年包 ~1,000 条/任务；档案包 38,182 条/任务——一次大事务换取每次全量只下载一遍，是本源的主动设计选择）。

命令行参数（key=value 形式）：

```
sync=1              必填。生成 lt_list 种子；身份含"运行日"——同日重跑零请求，次日自然重查
packages=all        all（默认）| year（只处理当年包）| archive（只处理档案包）
bucket=2026-09-03   可选。覆盖"运行日"标识，用于强制重查清单
```

## 4. 数据落到哪

**零领域表**（扁平文档型路径，同德国/法国/西班牙公报）：公报条目刊出即定、一条一文档，全库文号零重复（2026-09-03 对 39,143 条实测：`LOV-`/`FOR-` 文号全库唯一），没有跨文档的持久实体；条目间的修订关系（谁改了谁）是**字段**不是实体，随源照收进 meta——建图留给分析阶段。一切研究字段进 `documents` 一张表：

| 列 | 内容 |
|---|---|
| `doc_id` | `NOR_{公布日YYYYMMDD}_{hash8(source_url)}` |
| `title` | 公报全称（如 `Lov om endringer i helsepersonelloven og pasientjournalloven mv. (taushetsplikt og tilgjengeliggjøring av pasientopplysninger)`） |
| `publication_date` | **公报公布日**（kunngjort 字段的日期部分）——研究时间轴的主日期 |
| `issuing_authority` | 发布部门（ministry，多项时分号连接，如 `Helse- og omsorgsdepartementet`） |
| `source_url` | `https://lovdata.no/dokument/{文档ID}`（如 `…/dokument/LTI/lov/2026-01-23-1`）——Lovdata 文档正门 URL，规范可重建；采集不走此 URL，它只作身份与溯源 |
| `raw_format` / `language` | `xml` / `nor`（挪威语宏语言码——条目html lang 属性 83% 为笼统的 "no"、16% "nb"（书面语布克莫尔）、少量 "nn"（尼诺斯克），逐一判别属猜测，故用宏码；原属性值永存 meta） |
| `doc_type` | 文号前缀映射（下表）；挪威语原词永存 meta |
| `entity_ref` | NULL（扁平国家） |
| `meta` | 见下 |

**doc_type 映射**（原生优先：文号与文档 ID 中的类型段永存 meta，映射只是一层受控别名；跨国可比的统一类型学不在采集层做）：

| 类型段（文档 ID 内） | 文号前缀 | doc_type |
|---|---|---|
| `lov` | `LOV-` | STATUTE（法律） |
| `forskrift` | `FOR-` | SECONDARY_LEGISLATION（委任立法，与美国/英国口径对齐） |
| 其余 | — | OTHER（25 年实测未出现，防御位） |

**meta 字段**（原生字段无损收，全字符串）：`legacyID`（官方文号 `LOV-2026-01-23-1`——全库唯一）、`dokid`（Lovdata 文档 ID `LTI/lov/2026-01-23-1`）、`refid`（引用 ID `lov/2026-01-23-1`）、**`kunngjort`（公布时间戳原样，新年代带时分、2008 年前纯日期）**、**`adoption_date`（制定日，自文号解析的 ISO 日期）**、**`dateInForce` + `in_force_date`（施行日：纯日期两存；自由文本——如 `Kongen bestemmer`（由国王谕定，即施行日另行公告）——原样存 `dateInForce`、无 ISO 化值）**、`journalNumber`（登记号，年份可与文号年不同）、`publishedIn`（印刷版期号 `I 2001 hefte 1`，2001–2016 印刷时代条目有）、`changesToDocuments`（修订关系：被本文档修改的法规引用 ID 列表，分号连接）、`basedOn`（法律依据 hjemmel，中央法规常见）、`legalArea`（法律领域层级串）、`subunit`（部门内设机构）、`titleShort`（短题）、`miscInformation`（背景说明——法律条目含议会过程串，见下）、`appliesTo`（适用地域，如 `Norge`，27,680 条）、`eeaReferences`（**EU/EEA 引用**，如 `EØS-avtalen vedlegg XI nr. 5e (forordning (EU) 2016/679)`，90 条，2020 年起出现）、`lastupdated`、`numberOfPages`、`note`（低频字段）、`htmlLang`、`package_file` / `member_path`（来源包与包内路径）、`files`（文件清单）、`typeConflict`（仅 6 条文号错位条目携带，见 §8）。

**三个日期原生分开**是本源对时间序列研究的核心价值：制定日（文号日期段）/ 公布日（kunngjort，主锚）/ 施行日（dateInForce）——各入各列，互不推算。

文件落点（一项政策一个文件夹，年 = 包内原生年分片）：

```
{data_root}/NOR_policy/
├── state.db
├── failures/
└── 01_raw/lovtidende/
    └── 2026/                                 ← 包内年目录（= 制定年）
        └── LOV-2026-01-23-1/                 ← 一条公报条目一个文件夹（官方文号命名）
            └── doc.xml                       ← 包内成员字节原样（文档主文件）
```

## 5. 完整案例走查（2026 年真实条目，源站直连实值）

1. **清单**：`GET /v1/publicData/list` → 200，4 项。公报两包：档案包（69,298,008 字节 @ 2026-08-27T01:30Z）+ 当年包（1,383,606 字节 @ 2026-09-03T01:31Z）→ 生成两个 `lt_pack`。
2. **一条法律**（`lti/2026/nl-20260123-001.xml`，61,914 字节）：文号 `LOV-2026-01-23-1`（制定 2026-01-23）；公报公布 2026-01-23 11:40；施行 `Kongen bestemmer`（待国王谕定，施行日栏空缺是源站原生状态）；部门 Helse- og omsorgsdepartementet；修订关系 7 条（lov/1999-07-02-61 等）；法律领域 9 个；议会过程串 `Prop. 154 L (2024–2025), Innst. 71 L (2025–2026), Lovvedtak 20 (2025–2026). Stortingets første og andre gangs behandling hhv. 6. og 13. januar 2026`——提案、委员会报告、两轮审议日期齐全。doc_type = STATUTE。
3. **一条中央法规**（`lti/2026/sf-20260901-1715.xml`，5,295 字节）：文号 `FOR-2026-09-01-1715`（制定 = 公布同日 2026-09-01 14:25）；施行 2026-09-01（ISO 日期）；部门 Justis- og beredskapsdepartementet、内设 Innandringsavdelingen；法律依据 lov/2008-05-15-35/§26；修订 forskrift/2009-10-15-1286。doc_type = SECONDARY_LEGISLATION。
4. **老年代形状**（`lti/2001/nl-20010105-001.xml`，19,268 字节）：文号 `LOV-2001-01-05-1`（制定 2001-01-05）、公报公布 **2001-01-31**（纯日期形状、晚制定 26 天——公布日晚于制定日的极端例）、施行 `Kongen bestemmer`、印刷版期号 `I 2001 hefte 1`、登记号 2000-1016（跨年登记）。
5. **入账落盘**：`01_raw/lovtidende/2026/LOV-2026-01-23-1/doc.xml`；documents 一行（doc_id 以公布日与正门 URL 计算）；meta 含上述全部原生字段。
6. **全量运行**（2026-09-03，`sync=1` 两包全跑，3 任务 3 请求）：**39,143 文档 / 39,143 文件**一次入账零失败——公布日跨 2001-01-31 至 2026-09-02，类型分布 STATUTE 3,089 + SECONDARY_LEGISLATION 36,054（与包内文件名前缀分布精确一致），施行日 ISO 形状 31,753 条 / 自由文本（"Kongen bestemmer" 等）7,386 条 / 缺失 4 条。三方对账：源站包成员 39,143 ≡ 磁盘 39,143 ≡ 账本 39,143；逐年计数 26/26 精确一致（2001–2026）；账本 file_hash 与磁盘 sha256 **全库**多重集逐一相同；随机抽样 12 份磁盘字节 ≡ 源站包成员字节；doc_id 全部可由公式复算且唯一。同日重复运行零请求。EU/EEA 痕迹在账：标题含 EØS 的 616 条（法律 34 / 法规 582，2001 年起逐年不断），`eeaReferences` 原生引用字段 90 条（2020 年起）。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country nor --source lovtidende sync=1 --dry-run

# 首次全量（清单发现两包 → 档案包 2001–2025 + 当年包全部入账，约 71MB 下载）
python cli.py collect --country nor --source lovtidende sync=1

# 小窗口（只处理当年包，~1,000 条）
python cli.py collect --country nor --source lovtidende sync=1 packages=year

# 每日增量（清单 1 请求；包未变则零下载，包重建则该包重扫幂等入账）
python cli.py collect --country nor --source lovtidende sync=1

# 强制重查清单（覆盖"运行日"标识）
python cli.py collect --country nor --source lovtidende sync=1 bucket=2026-09-03b

# 状态 / 快照 / 修复
python cli.py status --country nor --source lovtidende
python cli.py export --country nor
python cli.py requeue --country nor
```

## 7. 更新与增量

- **包身份戳**：`{sizeBytes}@{lastModified}`（取自清单响应）随任务参数携带——任务身份含戳。**包不变 → 任务已存在且完成 → 跳过零下载**；包重建（戳变）→ 同名包以新身份重扫，文档按 doc_id 幂等合并（已存在行不变，新条目补入）。这是"参数化重开"模式：清单端点是新鲜度的唯一裁判。
- **当年包日更**：每日晨间重建 → 戳日日不同 → 当年包任务每天重扫一次（1.4MB 下载 + ~1,000 行幂等合并，秒级）。档案包低频重建（实测 2026-08-27 一次）→ 重扫一次全档案。
- **同日幂等**：`sync=1` 的种子身份含运行日——同一天重复运行清单任务直接跳过（零请求）；次日自然重查。需要当日强制重查用 `bucket=` 参数。
- **年代并档滚动**（每年初）：清单改返 `lovtidend-avd1-2001-{旧年}` + `lovtidend-avd1-{新年}` → 新文件名 = 新任务身份 → 旧年从档案包重扫一遍（doc_id 不变、幂等）+ 新当年包接管增量——自动完成，无需人工。
- **抓的是快照**：公报条目刊出即定，重复运行安全。若 Lovdata 事后修正某条目的元数据，重扫会更新磁盘文件，但账本行不自动回填（框架按"新文档注册"处理已存在行）——修正属罕见情形，走修复通道处理。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **1982–2000 条目不在整包内** | 网页登记册另有 17,915 条（lov+forskrift）早于 2001 的条目，但网页通道全站禁抓（§2）——本源从 2001 年电子官方公布起收，更早年代记缺（处置建议见任务报告） |
| **vedtak 类公布不收** | 公报 Del I 还刊登施行决定、授权决定、税收决定等公布类型，但官方 XML 数据集与登记册文档库只含法律与中央法规两类（2026-09-03 全库实测）——记缺 |
| **Del II 不收** | 地方性法规（县级/市级 forskrift）另一公布体系，无整包数据 |
| **EU/EEA 原文不在源内** | 经 EEA 协定并入挪威法律的 EU 法案原文（挪威语译文）刊登在单独的 **EØS-tillegget**（EEA 公报附录），不属公报 Del I、无整包数据；转化产物本身（实施 EEA 相关 EU 指令的挪威法律/法规）是普通公报条目、**全部在内**——标题含 EØS 的 616 条、原生 `eeaReferences` 字段 90 条（§5），"哪些条目源自 EU"的系统性判定属分析层工作 |
| **6 条文号错位条目** | 2014–2022 年间 6 条条目的官方文号字样与文件名前缀/标题相反（如 `LOV-2014-04-04-634` 实为 forskrift、`FOR-2022-10-21-85` 实为 lov）——源数据自身的标注错位；类型按前缀+标题判定，冲突记 meta.typeConflict（全库扫描 2026-09-03） |
| **议会过程不成表** | 法律条目 meta.miscInformation 自带议会过程原始串（提案号/委员会报告/审议日期），零成本无损收；结构化的议会动作数据需另立议会源 |
| **现行法汇编不收** | 清单里另有 `gjeldende-lover` / `gjeldende-sentrale-forskrifter` 两包（现行有效版本，2026-09-03 实测 5.8MB / 21.3MB）——版本序列研究的直接素材，本源不碰，将来另立源 |
| **印刷时代无电子全文** | 2001 年前条目无 XML；印刷版扫描件（1877–2016，1,524 册）由第三方站点 norgeslover.no 收集，不在本源范围 |
| **施行日自由文本** | 7,384/39,143 条施行栏为 `Kongen bestemmer` 类自由文本（施行日另行公告）——原样收，不推算 |
| **公布时间两种形状** | 2008 年前纯日期、之后带时分——统一取日期部分入列，原样串永存 meta |

## 9. 端点速查表

**在用**：

| 用途 | URL 模式 |
|---|---|
| 整包清单（发现唯一入口） | `GET https://api.lovdata.no/v1/publicData/list` |
| 整包下载 | `GET https://api.lovdata.no/v1/publicData/get/{filename}`（支持 .zip / .tar.bz2） |
| 文档正门 URL（source_url 基底） | `https://lovdata.no/dokument/{dokid}`（如 `…/dokument/LTI/lov/2026-01-23-1`；浏览器可开，采集不走此通道） |

**已确认存在、本源未用**（各自一句话研究价值）：

| 端点/数据包 | 价值 |
|---|---|
| `gjeldende-lover.tar.bz2` / `gjeldende-sentrale-forskrifter.tar.bz2`（清单内直接下载） | **现行有效版本整包**——版本序列研究的直接素材（"同一部法的当前状态"） |
| `api.lovdata.no` 其余端点（documentIndex / documentHistory / listBase / search / download 等，见 swagger） | 单文档元数据/变更日志/时点版本——**需付费 API 账户**，开源复现不依赖 |
| data.norge.no 数据集登记页 `c0c6a87c-f597-3735-965f-650be23426a0` | 许可与元数据权威（注意：其登记的旧下载 URL 已失效，活跃权威是 list 端点） |
| www.lovdata.no/register/lovtidend（网页登记册） | 覆盖 1982 年起的条目目录——**robots 全站禁抓**，仅作人工核对，不作采集通道 |
| norgeslover.no 印刷版扫描档案（1877–2016） | 印刷时代全文的第三方扫描件——回填议题参考 |

---

*更新日期：2026-09-03；数据快照：2026-09-03；数据由 sync=1 全量实跑背书（3 任务零失败 / 39,143 文档 39,143 文件 / 逐年 26/26 与全库哈希对账一致 / 幂等重跑零请求，计数见 §5）。*
