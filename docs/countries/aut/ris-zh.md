# 奥地利（AUT）RIS 联邦法律公报数据源说明

> 源代号 `ris`。对象是奥地利的联邦法律公报（Bundesgesetzblatt，缩写 BGBl，联邦政府的官方公报刊物，法律与条例经其刊登后方才公布生效）与两个年代的公报电子层。数据全部来自 RIS 的开放数据 API。

## 1. 源概览

- **机构与法律地位**：RIS（Rechtsinformationssystem des Bundes，联邦法律信息系统）由联邦总理府（Bundeskanzleramt，BKA）运营，是奥地利联邦法律的官方公布与检索系统。BGBl 分三部分：Teil I（法律与条约）、Teil II（条例）、Teil III（国际条约）。本包采集的正文文件是官方发布的 XML 全文。
- **两个电子层**（同一年代接缝，互不重叠）：
  - **BgblAuth**（电子认证层，2004 年至今）：每条含结构化元数据（编号、公布日、类型、分部、提交机关）与四种格式的文件链接（XML / HTML / RTF / 官方签名 PDF）；
  - **BgblPdf**（扫描层，1945–2003 年）：原件扫描 PDF 之外同样提供机器可读全文 XML（光学识别文本）；元数据含公报编号、公布日、类型、分部与起止页。
- **规模**（实测）：2025 全年 684 条（107 Gesetz / 218 Kundmachung / 314 Verordnung / 45 Sonstige，2026-09-13 逐类核对闭合）；2003 年 6 月 60 条、1970 年 6 月 30 条、1955 年 6 月 42 条、1945 年 6 月 23 条（2026-09-14 实测）。2004 年 6 月 89 条。
- **访问形态**：纯 HTTP API，查询返回 JSON，正文文件为 XML；正文不内联在查询响应里，一条目一文件。

## 2. 访问准备

- **无需 API key**：`https://data.bka.gv.at/ris/api/v2.6/` 免 key、免注册、免会话，GET 与 POST 表单同效（本包全部用 GET）。
- **无反爬的两条路径**：API 查询（`data.bka.gv.at`）与文件下载（`ogd.ris.bka.gv.at/Dokumente/…`）。注意：RIS 网页站与文件主机上的 HTML 页面（如 ELI 引用页）处于防护系统之后（2026-09-13 实测 503），本包不访问任何 HTML 页面。
- **无严格限额**：实测 8 个请求 3.8 秒连发全部 200（2026-09-13）；仍建议 `--delay 1:3` 礼貌限速。

## 3. 抓什么：任务类型清单

| 任务类型 | 请求 | 产出 |
|---|---|---|
| `bgbl_window` | GET `/ris/api/v2.6/Bundesrecht`，参数：`Applikation`（按年选 BgblAuth / BgblPdf）+ 起止日期（BgblAuth 用 `Kundmachung.Von`/`Kundmachung.Bis`，BgblPdf 用 `Kundgemacht.Von`/`Kundgemacht.Bis`，格式 `yyyy-MM-dd`）+ `DokumenteProSeite=OneHundred` + `Seitennummer` + 按公布日升序排序 | 该窗口的公报条目元数据（登记台账行），并为每个条目生成一个 `bgbl_file` 后继任务；结果多于一页时生成下一页任务 |
| `bgbl_file` | GET `https://ogd.ris.bka.gv.at/Dokumente/{Applikation}/{ID}/{ID}.xml`（条目的 XML 全文文件） | 该条目的正文文件落盘，挂到台账行上 |

每条公报 = 一个条目 = 一份文档。查询响应里每条目自带完整元数据与文件 URL（无需自行拼接猜测）。

## 4. 数据落到哪

- **零领域表**：公报条目即文档本体，`documents` 表承担全部台账（一条一行）：`publication_date` = 公布日（公报的 Ausgabedatum / Kundmachungsdatum），`issuing_authority` = 提交/发布机关（Organ），`doc_type` 由原生类型映射（见下），`language = deu`；国家特有字段全在 `meta` 列（原生编号 Bgblnummer、分部 Teil、原生类型词、短标题、ELI 引用、扫描层的公报出处与起止页等）。
- **类型映射**（原生词永存于 meta，映射只用于跨国对照）：Gesetz→STATUTE（议会通过的法律）、Verordnung→REGULATION（条例）、Kundmachung→OTHER（公告，如国际条约的刊登）、Sonstiges→OTHER（其他，如联邦与州按 Art. 15a B-VG 签订的协定）。
- **文件夹布局**（`01_raw` 顶层 = 源名 `ris`，一条目一文件夹）：

```
{data_root}/AUT_policy/
├── state.db
└── 01_raw/ris/
    ├── 2026/BGBLA_2026_II_7/BGBLA_2026_II_7.xml     ← BgblAuth 层
    └── 2000/2000_2_3/2000_2_3.xml                   ← BgblPdf 层
```

## 5. 完整案例走查

以两个真实条目把数据从头走到尾（全部数字取自 2026-09-14 的采集台账，可逐项复查）：

**电子层条目 `BGBLA_2026_II_7`**（2026 年 1 月窗口采集）：

- 台账行：`doc_id = AUT_20260108_45ab4d1e`，标题为该条条例的长题（财政部令，题长 130 余字符），`publication_date = 2026-01-08`（公布日），`doc_type = REGULATION`（原生类型 Verordnung），`issuing_authority = BMEIA`（欧洲与国际事务部），`language = deu`；
- `meta` 列：原生编号 `BGBl. II Nr. 7/2026`、分部 `Teil2`、原生类型词 `Verordnung`、短标题、ELI 引用（`https://www.ris.bka.gv.at/eli/bgbl/II/2026/7/20260108`）、旧文档号 `BGBLA_2026_II_7`；
- 文件：`01_raw/ris/2026/BGBLA_2026_II_7/BGBLA_2026_II_7.xml`（41,898 字节，risdok 全文 XML）；
- 磁盘文件 sha256 ≡ 台账 `file_hash` ≡ 源站当前字节（2026-09-14 三方逐字节核对一致）。

**扫描层条目 `2003_312_2`**（2003 年 6 月窗口采集）：

- 台账行：`doc_id = AUT_20030630_39731e5c`，`publication_date = 2003-06-30`，`doc_type = REGULATION`（原生类型 Verordnung，最高利率上限条例 2003），`issuing_authority = BKA`；
- `meta` 列：`bgblnummer = 312/2003`、`jahrgang = 2003`、`teil = Teil2`、起止页 `1699–1700`；
- 文件：`01_raw/ris/2003/2003_312_2/2003_312_2.xml`（2,012 字节，光学识别全文——该条目的清单响应只列了扫描 PDF，XML 是按规范路径构造取得的，见 §8）。

窗口级对账（多重集口径，2026-09-14）：2026-01（43 条）与 2003-06（60 条）两窗口的 API 条目集 ≡ 台账行集 ≡ 磁盘文件集，逐一相等，零缺失。

## 6. 怎么跑

```bash
# 首次/指定窗口采集（三粒度入口，任选其一）
python cli.py collect --country aut --source ris date=2026-01-05      # 按日
python cli.py collect --country aut --source ris month=2026-01        # 按月（推荐分片）
python cli.py collect --country aut --source ris year=2025            # 按年（内部按月分片）
python cli.py collect --country aut --source ris month=2003-06        # 扫描层（2000–2003 自动走 BgblPdf）

# 增量同步（游标之后到昨天，按月分片）
python cli.py collect --country aut --source ris sync=1 --delay 1:3

# 试运行（只列计划不抓取）/ 状态 / 导出
python cli.py collect --country aut --source ris month=2026-01 --dry-run
python cli.py status --country aut --source ris
python cli.py export --country aut
```

年代自动选择：窗口起点年份 ≥ 2004 走 BgblAuth，≤ 2003 走 BgblPdf；同一次运行内按月分片时逐窗判断。

## 7. 更新与增量

- **游标**：键 `ris_last_publication_date`，值 = 最近一个**被完整扫完的窗口**的结束日（ISO 格式）。一个窗口的全部页（含空窗）扫完即视为消费到该日；空窗（该时段无公报，如周末/节日）同样推进。
- **同步**：`sync=1` 从游标次日到**昨天**按月分片（当天公报可能尚未生成，与"当日无刊"不可区分，故同步永远不索取今天）。
- **重访**：公报条目刊登即定，不再重访；显式给出 `date=`/`month=`/`year=` 可随时重扫任意时段（台账按条目身份去重，重复抓取自动跳过）。

## 8. 已知边界与缺口

- **生效日无结构化字段**：公报元数据只有公布日；生效日期写在条文里（"… tritt am … in Kraft"），公报层如实记缺。同一 API 的 History 端点（条文级变更）带结构化生效/失效日期，纳入版本序列时可补齐。
- **1945 年以前未采集**：帝国层（Reichs-/Staatsgesetzblatt 1848–1940，BgblAlt 应用）端点可用，但其清单响应不提供文件链接，形状不同，未纳入。
- **周末/节日空窗是正常状态**：窗口查询返回 0 条（HTTP 200），不是故障。
- **防护理边界**：RIS 网页站与 ELI 引用页（HTML）在防护系统之后；本包只走 API 与 XML 文件两条路径。若文件路径将来也被防护，采集会成批失败并升级，届时需人工评估。
- **XML 为排版型标记**：正文 XML（risdok 格式）按排版组织（段落/标题等），非语义化法律标记；全文完整，适合文本清洗，条款级结构需清洗阶段自行推导。
- **扫描层的两处形状差异**（2026-09-14 实测）：① 单文件条目的文件链接数组会收缩为单个对象（非数组）；② 部分条目的清单只列扫描 PDF 而不列 XML，但 XML 文件本身存在于规范路径上（构造 URL 实测 200 且为完整光学识别全文）——采集器对这类条目按规范路径构造 XML 地址，不必依赖清单。

## 9. 端点速查表

在用：

| 端点 | 用途 |
|---|---|
| `GET https://data.bka.gv.at/ris/api/v2.6/Bundesrecht?Applikation=BgblAuth&…` | 2004–今公报条目检索（JSON） |
| `GET https://data.bka.gv.at/ris/api/v2.6/Bundesrecht?Applikation=BgblPdf&…` | 1945–2003 公报条目检索（JSON） |
| `GET https://ogd.ris.bka.gv.at/Dokumente/{Applikation}/{ID}/{ID}.xml` | 条目正文 XML 全文 |

已勘明未用（研究价值备注）：

| 端点/应用 | 一句话 |
|---|---|
| `Bundesrecht?Applikation=Bundesnormen` | 现行联邦法整合库，一法规一实体，版本序列候选 |
| `GET /ris/api/v2.6/History?Anwendung=Bundesnormen&…` | 条文级变更流水（十日窗约 1,056 条，含结构化生效/失效日期与修订关系字段） |
| `Bundesrecht?Applikation=BgblAlt` | 1848–1940 帝国层公报（28,547 条，清单不带文件链接） |
| `Judikatur` / `Landesrecht` | 判例库 / 州立法检索（均不在本包范围） |
| API 文档与官方示例 | `https://data.bka.gv.at/ris/api/v2.6/Help` 及根页的 Examples.zip（各应用的参数名以示例页表单字段为准） |

---

*更新日期：2026-09-14；数据快照：2026-09-14（回填至当日，此后由 sync 增量接续）；数据由 2000–2026 全量真实采集背书（22,526 条，台账与磁盘文件 2026-09-14 逐年三方对账逐一相等）。*