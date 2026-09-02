# 美国（USA）指引层说明——财政部（Treasury）

> 上游总览见 [guidance-zh.md](./guidance-zh.md)（制度背景、范围口径、doc_type 打标规则、任务形态）。本文只讲财政部的三个渠道：站点结构取证、解析细节、已知坑、命令。
> 文中运行数字为真实小样实测（2026-08-31）。

财政部（United States Department of the Treasury）的机构直发政策文件主要出自三个内设机构：国内收入局（Internal Revenue Service，IRS）、海外资产控制办公室（Office of Foreign Assets Control，OFAC）、货币监理署（Office of the Comptroller of the Currency，OCC）。OFAC 的制裁指定与通用许可走《联邦公报》（Federal Register，FR）——由 regulations 源覆盖，不归本层。

## 1. IRS：《国内收入公报》周刊

**站点结构（2026-08-31 取证）**：`irs.gov/irb` 索引页服务端渲染，列出最近约 10 期；每期 URL 形如 `/irb/{年}-{周}_irb`，整期 PDF 在 `irs.gov/pub/irs-irbs/irb{YY}-{WW}.pdf`（该目录也可直接浏览，作历史索引）。

**期次页标记**——这是本渠道最关键的取证发现：
- 目录是**双层结构**：外层条目 `<a href="#idN" class="text-overflow xmlbc-link">标题</a>`，紧跟的嵌套条目 `<a href="#NOT-2026-48">Notice 2026-48</a>` 带官方标识符和**语义锚点**；
- 正文区以 `<a name="语义锚点">` 分隔各文档，可按锚点切片；
- 一个坑：中间稿（Interim）与财政部决定（Treasury Decision，TD）的编号体系不同——TD 是**流水号**（如 T.D. 10026），其余是**年份式**（Notice 2026-48）。解析正则必须两式兼容。

**解析产出**：每份文档一行（原生标识符即主键，doc_type 按标识符映射：TD→REGULATION，Notice/Rul./Proc.→GUIDANCE，Announcement→OTHER）；正文切片写入行内 `text_extracted` 列 + 单文档碎片文件 `docs/{原生号}.html`；整期 PDF 另存为官方原件。

```bash
# 抓当年最近各期（每期约 5-10 份文件 + 1 个整期 PDF）
python cli.py collect --country usa --source guidance agency=irs max_docs=2
# 按期号窗口
python cli.py collect --country usa --source guidance agency=irs window=2026-30:2026-35
```

已知瑕疵：部分文档的外层目录条目是容器标题（"Part III"），行内标题会落到容器名——原生标识符是主键身份，检索不受影响。

## 2. OFAC：制裁口径问答库

**站点结构（2026-08-31 取证）**：`ofac.treasury.gov/sitemap.xml` 单文件、约 4,277 个 URL，其中 **991 条**是 `/faqs/{号}` 问答页——整库可经站点地图（sitemap）枚举，无需碰动态搜索界面。问答页正文**服务端渲染**（在 `region-content` 区块的 `ofac-faq-item` 视图字段里；页面的 `<main>` 区块是纯导航，别从那里解析）。页面本身无日期，站点地图的 `<lastmod>` 透传为 `revised_date`。

```bash
python cli.py collect --country usa --source guidance agency=ofac max_docs=20   # 小样
python cli.py collect --country usa --source guidance agency=ofac              # 全库 991 条
```

实测小样：15 行，主题域（如 "Entities Owned by Blocked Persons (50% Rule)"）、修订日期、1.1k–3k 字符正文全部入账。

## 3. OCC：银行监管公告

**站点结构（2026-08-31 取证）**：`occ.gov/sitemap.xml` 是**根级直列型**（单文件内联约 1.5 万 URL，公告、新闻稿、PDF 混排）。过滤 `/news-issuances/bulletins/{年}/bulletin-{年}-{号}.html` 即公告库。公告页为全文超文本标记语言（HTML），标题在 `<title>`（去掉尾部的 "| OCC"），日期标记不统一（"Date Issued: August 24, 2026" / `datetime` 属性等多种形态，解析器多模式宽松匹配）。

一个坑：站点地图里混有**伪站点地图 URL**（如 `topics-sitemap.html`——返回 HTML 页）——子站点地图判定必须要求 `.xml` 结尾（含 `?page=` 变体），且对非站点地图响应按预期空跳过。

```bash
python cli.py collect --country usa --source guidance agency=occ max_docs=12
```

实测小样：12 行，真实标题与日期（如 "Bank Supervision: Interagency Guidance on Lending…"，2026-07-13）、2k–5k 字符正文。

---

*更新日期：2026-09-01；数据快照：2026-08-31（探查实测 + 小样运行）；文中"实测"数字即真实运行计数（全量窗口的跑法见文中命令）。*
