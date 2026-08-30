# 德国（DEU）数据源说明——bgbl（联邦法律公报 Teil I）

> 文中覆盖范围与数量为官方数据源的稳定特征，案例均为真实数据实例（可从 `state.db` 复查）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。德国全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：BGBl 是什么

**Bundesgesetzblatt（联邦法律公报，简称 BGBl）** 是德国联邦法律的官方公布媒介——法律与法规只有在此公布（Verkündung）才生效。由 **Bundesanzeiger Verlag**（联邦公报出版社）运营，[www.bgbl.de](https://www.bgbl.de) 是 1949–2022 年纸质公报的**官方数字档案**：逐条目扫描 PDF，免费公开，无需注册。

公报分两部：

| 部 | 内容 | 档案覆盖 | 本源是否抓取 |
|---|---|---|---|
| **Teil I** | 联邦法律、法规、宪法法院判决主文、联邦总统令、联邦机构内部事项 | 1949–2022 | **是**（本源全部内容） |
| **Teil II** | 国际条约与协定、相关公布、关税类法规 | 1951–2022 | 否（已探明同构，见 §8） |

两个关键时间边界：**本档案是冻结档案，内容止于 2022**；**2023-01-01 起德国改用电子公报，位于 [recht.bund.de](https://www.recht.bund.de)**（不在本源范围）。

**与欧盟法的关系**（三层，2026-08-27 逐层实证）——用 Teil I 做"德国政策"分析时须知 EU 法的两条渗透渠道：

1. **转化立法（在 Teil I 内，正常逐条抓取）**：把 EU 指令（Richtlinie）转化为德国国内法的联邦法律/法规（标题常含 `Gesetz zur Umsetzung der Richtlinie (EU) …`）。它们是**德国本国法案**，按普通条目出现在 Teil I——标题点名 EU 法的条目 1994–2022 共约 454 / 12,282（约 3.7%，属下界：不少转化法不在标题点名 EU）；如 2020 年的 `Gesetz zur Umsetzung der Verhältnismäßigkeitsrichtlinie (Richtlinie (EU) 2018/958)…`。
2. **直接生效的 EU 条例（不在 Teil I 公布，每期只登提示）**：EU 条例（Verordnung (EU)）在《欧盟官方公报》（ABl. EU）发布后**对德国直接生效，不经国内转化、不在 BGBl 公布**。BGBl Teil I 每期末尾固定刊登一条提示 `Hinweis: Rechtsvorschriften der Europäischen Union`，列出近期直接生效的 EU 条例清单（PDF 原文自述只列 ABl. 目录中加粗的 Verordnungen）。本源按过滤规则不抓此提示行；**需要 EU 条例原文须去 ABl. EU，超出本源范围**。
3. **年度引用索引 Fundstellennachweis**：树顶层提供 A、B 两卷逐年 PDF。B 卷（实测 2020 版，1,180 页，联邦司法部编辑）是 **Teil II 国际协定的引用出处索引**；A 卷对应 Teil I 联邦法律。两卷均为汇编检索工具，本源不抓（见 §9）。**EU 法没有专门的 FNB 卷**——EU 维度的回溯线索就是第 2 点的逐期 Hinweis。

### 1.2 技术形态：单页应用 + 纯 HTTP 接口

bgbl.de 是 doctronic **xaver 平台**的 Dojo 单页应用（哈希路由），但网络层探查表明其背后有**完整的 HTTP 数据接口**：目录树枚举、深链内容、PDF 投递全是普通 GET，**零浏览器跑通**。常见的"这类站点必须浏览器自动化"判断往往源于只看过页面没看过网络层——本源是反例样板（韩国 law.go.kr 同理）。

目录树层级与稳定 id（`n=0` 为根，逐层展开；节点 id 跨会话稳定）：

```
根 (n=0)
├── Bundesgesetzblatt Teil I   (id=61929557)  ← 本源入口
│   ├── 2022 … 1949（每年一节点）
│   │   └── Nr. {期号} vom {DD.MM.YYYY}（如期节点 2020/Nr.1: id=61931801, did=1226091）
│   │       ├── Komplette Ausgabe（整期合集 PDF）      ← 不抓
│   │       ├── Inhaltsverzeichnis（目录页 PDF）       ← 不抓
│   │       ├── {条目标题}（真实政策条目，每条一个 PDF） ← 抓
│   │       └── Hinweis: …（官方指引）                  ← 不抓
├── Bundesgesetzblatt Teil II  (id=61980564)  ← 不抓
└── Fundstellennachweis A/B PDF（法源索引）            ← 不抓
```

**会话机制**（PDF 端点专用，2026-08-27 矩阵实验实证）：目录枚举与内容深链**无需会话**；PDF 投递要求会话 cookie + 本会话的 csrf 令牌，缺一或错配均 403（令牌写进 URL 参数、Referer 头均不能替代）。会话由任务链自动建立（两个前置任务各一个请求），cookie 由框架传输层自动留存，使用方无感。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 零条目 |
| 会话 | 仅 PDF 端点需要（cookie + csrf 令牌）；任务链自动建立，无需人工介入（见 §3） |
| 限额 | 无公开限额；实测连续数十请求无拦截；框架统一限速足够安全 |
| 反爬 | 未发现（无验证码、无 UA 检查迹象；PDF 端点仅要求会话一致性） |
| 响应格式 | 目录树与会话参数为 JSON；内容深链为 JSON 信封（HTML 表格包在 `innerhtml` 字段里）；PDF 为二进制 |
| 请求头 | 会话参数请求需 `X-Requested-With: XMLHttpRequest`；UA 用普通浏览器串 |

## 3. 抓什么：任务类型清单（5 种）

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `bgbl_session`（种子） | `start.xav`（触发 Set-Cookie，cookie 留在传输层） | 后继 `bgbl_csrf` |
| `bgbl_csrf` | `start.xav?nocomm=final`（会话参数 JSON） | 解析出 csrf 令牌 → 后继 `bgbl_toc`（root），令牌经任务参数下传 |
| `bgbl_toc` | 目录树一层（`level: root\|part\|year` 三级过路） | root 找 Teil 节点 → part 找年份节点 → year 为每期生成 `bgbl_issue` |
| `bgbl_issue` | 期节点深链（**一次请求 = 整期目录表**） | 解析条目行（标题/日期/页码/PDF 文件名）→ 过滤后每真实条目生成 `bgbl_pdf` |
| `bgbl_pdf` | PDF 投递端点（302 跟随后得二进制） | PDF 落盘 + `documents` 入账（一文件一档） |

任务链：`bgbl_session → bgbl_csrf → bgbl_toc(root) → bgbl_toc(Teil I) → bgbl_toc(year) → bgbl_issue × N 期 → bgbl_pdf × M 条目`。

命令行参数（key=value）：

```
part=1              仅 Teil I（传 2 报错：Teil II 不在本源范围）
year=2020           必填，4 位年，1949–2022
issues=1-2          期号："all"（缺省）/ 区间 1-2 / 列表 1,3
```

**过滤规则**（三排除，树节点标签与目录表行文本双重判定）：`Komplette Ausgabe`（整期合集，与逐条目内容重复）、`Inhaltsverzeichnis`（目录页本身）、`Hinweis: *`（指向 Bundesanzeiger / EU 公报的官方指引，非政策文本）。

## 4. 数据落到哪

**零领域表、零 kv**（扁平文档型）：BGBl 条目即文档本体——无生命周期（公报刊出即不变，纠错 Berichtigung 另立条目另立 PDF）、无关联实体。一切研究字段进 `documents` 一张表：

| 列 | 内容 |
|---|---|
| `doc_id` | `DEU_{期日期YYYYMMDD}_{hash8(source_url)}`，期日期 = Verkündung 日 |
| `title` | 条目德语原题（如 `Verordnung zur Änderung der Bundesbankpersonal-Verordnung`） |
| `publication_date` | 期日期（公布日）；条目自身签署日另存 `meta.entry_date` |
| `source_url` | 规范形式 `media.xav/{路径}?medianame={编码全路径}`（剥一次性会话参数，可重建） |
| `raw_format` / `language` | `pdf` / `deu` |
| `doc_type` | `OTHER`（软处理；标题首词存 `meta.title_head`，类型学留给后续阶段） |
| `entity_ref` | NULL（扁平国家示范） |
| `meta` | `part`、`year`、`issue_nr`、`issue_label`、`issue_date`、`page_range`、`entry_date`、`entry_order`、`page_start`、`pdf_name`、`title_head`、`did`（条目节点 id） |

文件落点（条目材料为单 PDF，期是天然分片层；源文件名零转写，与源站核对无歧义）：

```
{data_root}/DEU_policy/
├── state.db
├── failures/
└── 01_raw/bgbl/
    └── I/2020/Nr_01/
        ├── bgbl120s0002.pdf
        └── bgbl120s0003.pdf
```

## 5. 完整案例走查（2020 年 Teil I Nr.1–2，库内实值）

1. **建链**：`bgbl_toc` 走 root → Teil I(id=61929557) → 2020，第三层返回 **67 期**（ Nr. 67 vom 30.12.2020 至 Nr. 1 vom 07.01.2020）。
2. **期目录**：`bgbl_issue(2020, Nr.1)`（did=1226091）返回目录表，表头 `Nr. 1 vom 07.01.2020, Seite 1 – 24`；6 行中 4 行被过滤（整期合集 / 目录页 / 2× Hinweis），余 **2 个真实条目**：
   - 序号 3：签署日 `08.12.2019`，**Verordnung zur Änderung der Verordnung über die Zuständigkeit des Bundesamtes für Infrastruktur…**，起始页 2，`bgbl120s0002.pdf`（20,635 字节）→ `DEU_20200107_5cad18ed`；
   - 序号 4：签署日 `02.01.2020`，**…(ESanMV)**，起始页 3，`bgbl120s0003.pdf`（104,855 字节）→ `DEU_20200107_e9908161`。
   - 两条目的签署日均早于公布日 07.01.2020——`publication_date` 取期日期、签署日进 `meta.entry_date` 的口径由此而来。
3. **下载入账**：`bgbl_pdf` 取回字节 → `01_raw/bgbl/I/2020/Nr_01/bgbl120s0002.pdf`，documents 一行。
4. **窗口合计**（Nr.1 + Nr.2，期日期 10.01.2020，页码 25–64）：13 任务全 done、6 份 PDF、6 行 documents；Nr.2 四条目为 `bgbl120s0026/0027/0039/0063.pdf`（23,134 / 94,955 / 131,991 / 32,905 字节）。

## 6. 怎么跑

```bash
# 演练（不入队执行，看计划）
python cli.py collect --country deu --source bgbl part=1 year=2020 issues=1-2 --dry-run

# 小窗口试跑（上节案例的实际命令）
python cli.py collect --country deu --source bgbl part=1 year=2020 issues=1-2

# 全年
python cli.py collect --country deu --source bgbl part=1 year=2020

# 状态 / 快照 / 修复
python cli.py status --country deu --source bgbl
python cli.py export --country deu
python cli.py requeue --country deu
```

## 7. 更新与增量

- **冻结档案无增量**：内容止于 2022，站点不再变更 → 本源无同步游标、无重开规则、kv 不使用。
- **重跑语义（与会话机制耦合，重要）**：csrf 令牌与传输会话绑定、会话生命周期 = 一次 collect 运行，因此任务链携带每次运行唯一的 `nonce`——**重复运行同窗口会整链重执行**（枚举 + 下载都重跑；documents 按 doc_id 合并、文件覆盖写），**结果是幂等的，字节是重传的**。"已完成任务直接跳过"对会话绑定源不可得；冻结档案一次性回填场景可接受。
- 内容深链响应含 `modified` 时间戳，预留为未来更新信号，本源不用。

## 8. 已知边界与缺口

| 项 | 说明 |
|---|---|
| **Teil II 不抓** | 已探明与 Teil I 完全同构（树/期/条目层级一致），覆盖 2022–1951；2020 年 24 期、Nr.1 含 12 条目（条约/协定为主）。开抓改动量：`bgbl_toc` 改走 Teil II 节点（id=61980564）、路径前缀 `Bundesgesetzblatt Teil II` |
| **2023 年及以后** | 电子公报移至 recht.bund.de，属另一源，本源天然不含 |
| 整期合集与目录页 | `Komplette Ausgabe` / `Inhaltsverzeichnis` 不抓（内容与逐条目重复）；需要整期镜像时可用命名规律 `bgbl{部}{年}{期:03d}.pdf` 回补 |
| `Hinweis:` 行 | 官方指引而非政策文本，排除（含 EU 直接生效条例的逐期提示，见 §1.1） |
| 文件名年代差异 | 1994 目录页 PDF 用 `i` 前缀（`bgbl194i0001.pdf`），2020 用 `s`——实现从链接取值、不做字符串构造，天然免疫 |
| **PDF 字节变体** | 同一文件两次下载字节可不同（实测 `bgbl120s0002.pdf` 两副本 20,634B 与 20,635B，xref 偏移不同、md5 不同，内容均完整有效）——源站投递非字节稳定。身份与幂等走 doc_id 不受影响；`file_hash` 仅为落盘时的校验和，**不作跨下载一致性依据** |
| 会话空闲过期 | 服务端会话闲置数小时后失效（403）；任务链每次运行重建会话，天然免疫 |
| 覆盖下限 | Teil I 自 1949（BGBl 创刊）；1994 前后结构已抽查同构，未逐年验证——回填如遇异形逐个排查 |
| 大文件投递 | 单条目 PDF 一般 <1MB 无碍；站点偶发长连接断流，重跑即续 |

## 9. 端点速查表

均位于 `https://www.bgbl.de/xaver/bgbl/` 下：

| 用途 | 端点 |
|---|---|
| 目录树一层 | `ajax.xav?q=toclevel&n={node_id}`（根=0；Teil I=61929557；Teil II=61980564） |
| 期目录表 / 条目内容 | `text.xav?SID=&tocf=&tf=&qmf=&hlf=&start=//*[@node_id='{did}']&tocide=0&bk=` |
| 建会话 | `start.xav`（Set-Cookie: JSESSIONID + bgblxaver） |
| 会话令牌 | `start.xav?nocomm=final&SID=&startbk=bgbl&bk=bgbl&start=`（需 XHR 头；JSON，取 `csrftoken`） |
| PDF 投递 | `media.xav/{medianame 斜杠换下划线}?SID=&bk=bgbl&medianame={编码 medianame}&_csrf={令牌}` → 302 → `/xaver/bgbl/media/{会话token}/{文件}_{媒体id}.pdf` |
| medianame 构造 | `bgbl/Bundesgesetzblatt Teil {I\|II}/{year}/{issue_label}/{pdf_name}`（issue_label 用目录树原文，如 `Nr. 1 vom 07.01.2020`） |

**源里还有但暂未用的**：Fundstellennachweis A/B（法源引用索引，逐年 PDF——A 卷联邦法律、B 卷国际协定）；站内全文搜索（研究价值低，按条目抓全量更完整）。

---

*更新日期：2026-08-30；数据快照：2026-08-30；数据由 part=1 year=2020 issues=1-2 实跑窗口背书（13 任务零失败、6 份 PDF 三方核对一致）。*
