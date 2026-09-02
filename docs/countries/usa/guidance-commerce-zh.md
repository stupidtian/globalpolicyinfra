# 美国（USA）指引层说明——商务部（Commerce）

> 上游总览见 [guidance-zh.md](./guidance-zh.md)。本文讲商务部三个渠道：工业与安全局（Bureau of Industry and Security, BIS）、国家气象局（National Weather Service, NWS）、国家标准与技术研究院（National Institute of Standards and Technology, NIST）。
> 文中运行数字为真实实测（2026-08-31，NIST 渠道为 2026-09-01）。

商务部（United States Department of Commerce）的出口管制规则修订与实体清单增删走《联邦公报》（regulations 源已覆盖）；本层抓的是官网直发件。

## 1. BIS（工业与安全局）：出口管制解释性指引

**站点结构（2026-08-31 取证）**：BIS 官网（bis.doc.gov）已重建为动态应用（Next.js），`sitemap.xml` 返回的是超文本标记语言（HTML）页面——**不可用**。但指引 PDF 挂在少数**服务端渲染的清单页**下（如 `/licensing/country-guidance` 挂 "Guidance on Advanced Computing Items" 及其问答）。每个清单页一个任务：全部 PDF 直链入账。

坑：清单页混有网站管理类文件（SORN 隐私通告、信息质量指南）——按文件名跳过清单处理。

```bash
python cli.py collect --country usa --source guidance agency=bis
```

实测：2 个清单页、4 行、2 份 PDF 落盘。

## 2. NWS（国家气象局）：指令体系

**站点结构（2026-08-31 取证）**：`weather.gov/directives/` 是编号指令树——索引页列约 11 个系列（`/directives/010` 等），系列页在 `<div class="cms-content">` 区块内以无序列表直挂指令 PDF：`<li><a href="/media/directives/010_pdfs/pd01001curr.pdf">NDS 10-1 标题…</a></li>`。锚文本即标题；**撤销的指令在标题里带 "rescinded" 标记**（红色 span），解析为 `status='withdrawn'`——指引层目前唯一有真实生命周期状态列的渠道。原生号优先取标题的 "NDS 10-1" 模式，无则退回文件名。

```bash
python cli.py collect --country usa --source guidance agency=nws series=010   # 单系列
python cli.py collect --country usa --source guidance agency=nws              # 全部 11 个系列
```

实测：系列 010 一个系列 321 份指令全量入账——241 份现行 + 56 份已撤销，PDF 全部落盘。**注意单系列即可达数百份，全系列首次运行量级为数千请求。**

## 3. NIST（国家标准与技术研究院）：快照式书目渠道

**取证过程（2026-08-31 首探，2026-09-01 修正定案）**：官网浏览页不完整——SP（Special Publication，特别出版物）系列实际 600+ 份只露出 37 份、FIPS（Federal Information Processing Standard，联邦信息处理标准）页为 0；官方接口域（ctp.nist.gov）不可达。转探官方 GitHub 仓库 `usnistgov/NIST-Tech-Pubs`，两点修正此前判断：

1. 该仓库**默认分支 `nist-pages` 是站点源码**，`xml/` 目录下只有 2020 年的归档全量（`allrecords_march312020.xml`，53MB，已过期）与期刊 XML——"逐条 XML 语料"的早期印象来自旧分支 `master` 时代的目录结构，当前不成立。
2. 真正的全量在 **GitHub Releases（发布通道）**：每月一个发布（标签形如 `July2026`），挂三个资产——`allrecords-MODS.xml`（约 84MB，MODS 即 Metadata Object Description Schema，美国国会图书馆的元数据模式）、`allrecords.xml`（约 174MB，MARCXML 机读编目格式）、`readme.txt`。由 NIST 研究图书馆的 Alma 编目系统导出、专职元数据馆员质检后发布，覆盖 NIST/NBS（国家标准局，NIST 前身）全部技术系列出版物的书目元数据。**取 MODS 版**（字段语义直读，体积减半）。

**记录结构（抽样实测）**：`<modsCollection>` 包含约 13,000 条 `<mods>` 记录（84MB ÷ 每条约 6.4KB）。每条的字段映射：

| MODS 字段 | 入库列 |
|---|---|
| `titleInfo/title`（含 `nonSort` 冠词） | `title` |
| `identifier[@type='doi']`（如 `10.6028/NIST.IR.6027`） | `native_id`、`url`、`file_url`（经 DOI 解析跳全文） |
| `relatedItem[@type='series']/titleInfo` | `native_type`（系列短码，如 "NIST SP"） |
| `originInfo/dateIssued`（优先非 marc 精确版 "1997-06."） | `issued_date` |
| `subject/topic` 首个主题词 | `product_area` |
| `recordInfo/recordIdentifier`（Alma 编目号） | 无 DOI 时的 `native_id` 兜底 |

**native_id 规则（纯函数）**：DOI 后缀按句点改空格——`NIST.SP.800-53r5` → `NIST SP 800-53r5`、`NBS.CS.62-59` → `NBS CS 62-59`。这是官方可引用编号的机械规范化，不猜语义。无 DOI 记录退回"系列名 + 卷号"，再无则用编目号前缀 `rec-`。

**系列普查（三个 1MB 分段抽样 751 条）**：全部 DOI 均为 NIST 官方段 `10.6028`（无外部期刊 DOI，即本语料不含期刊论文）；系列含 NIST IR/SP/TN/GCR/AMS/HB/NCSTAR 与 NBS 时代 CS/CSM/TN/LCIRC/MP/MONO/BH/CIRC 等 15 类以上。

**doc_type 规则（沿用 R1"仅源生标注"）**：仅 FIPS → `STANDARD`（系列全称本身即"联邦信息处理**标准**"，且按法律要求联邦机构强制采用）；其余全部 `OTHER`——NIST 官方对 SP 的定义是"报告与指引混合系列"、IR 是"研究报告"，系列无法逐篇证明文件属性，不猜。系列短码原样保留在 `native_type`，后续筛选不受影响。

**任务形态（与统一议程 XML 同为快照模式）**：

- `nist_latest`：调 GitHub 接口取最新发布标签，生成带具体标签的下载任务；
- `nist_release_dl`：一个任务内完成 下载 → 归档（`01_raw/guidance/commerce/nist/catalog/{标签}.xml`，逐字保存）→ 本地解析 → 逐行入库 + `source_snapshots` 登记。

**增量语义**：任务标识含发布标签——同标签重跑任务去重为无操作；每月新标签生成新任务，行按 `(agency, native_id)` 更新式覆盖（书目修订自然合入）。无需另设水位。

坑：① DOI 字段带尾随空格，须 strip；② 系列标题是变体串（"NISTIR; NIST IR; NIST interagency report; …"），不能用其做键——一律以 DOI 后缀为准；③ 少量记录无系列卷号（分段抽样中约 0.5%），走编目号兜底；④ 84MB 单响应在内存中解析，用 iterparse 且仅在记录边界 clear——教训见 regulations 说明（过早 clear 会丢子元素）。

```bash
python cli.py collect --country usa --source guidance agency=nist            # 最新发布
python cli.py collect --country usa --source guidance agency=nist release=July2026   # 指定发布
```

实测（2026-09-01，July2026 发布）：快照 84,260,460 字节逐字归档；解析 20,355 条记录，按主键（机构+原生号）合并重复标识后入库 **19,947 行**——其中 FIPS→STANDARD 338 行、其余 OTHER 19,609 行；系列前列：NIST IR 4,568、NBS IR 3,376、NBS RPT 1,808、**NIST SP 1,645**、NBS TN 1,311（NIST/NBS 两代合计覆盖 1900s 至 2026-07）。全程 2 个请求（1 次标签查询 + 1 次下载）。

---

*更新日期：2026-09-01；数据快照：BIS/NWS 为 2026-08-31（探查实测），NIST 为 2026-09-01（发布 July2026，全量入库）。*
