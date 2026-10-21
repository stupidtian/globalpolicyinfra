# 沙特阿拉伯官方公报（SAU）——uqn 源说明

> **读者定位**：外部开源用户——假定读者只会用命令行、对本项目一无所知。内部施工复用同一份。
> 乌姆古拉（أم القرى，Umm al-Qura，沙特阿拉伯官方公报）官网 uqn.gov.sa 的采集说明。

## 1. 源概览

沙特阿拉伯的官方公布媒介是**جريدة أم القرى（乌姆古拉公报，Umm al-Qura）**：1924 年创刊的官方公报，由新闻部（وزارة الإعلام，Ministry of Media）出版，法律法规、国王敕令、部长会议决定均在公报刊出后生效。官网 `https://www.uqn.gov.sa` 由公报编辑部运营，提供：

- **条目级页面**（2026-01-23 起的新版网站）：官方部分条目逐条可访问，URL 形如 `https://www.uqn.gov.sa/decisions-and-regulations/4001992`，全文（阿拉伯语）直接内联在页面里，无需下载文件；
- **期册 PDF**（全年代）：每期公报的整册 PDF，新版网站按公历日期编址（如 2026-10-02 期约 5.0 MB）；
- **站点地图（sitemap）**：按月组织的 XML 索引，覆盖 2012-03 至今。

覆盖范围与量级（2026-10-10 实测）：官方部分（قرارات وأنظمة，"决定与法规"）2026 年 1–8 月共 267 条，约合每月 33–50 条；官方公告（إعلانات，advertisements）同期 125 条。公报每期约 4–5 MB PDF，每周约 1–2 期。2012–2025 年的老年代只有期册 PDF 可用（老版网页无内联正文），条目级采集自 2026 年起。

站内官方部分的分类树（每条目归属其一，是文书类型的权威来源）：royal-decrees（مرسوم ملكي，皇家敕令）、royal-orders（أمر ملكي，皇家命令）、council-of-ministers-decisions（部长会议决定）、ministerial-decisions（部门决定）、rules-and-regulations（أنظمة ولوائح，法规条例）、agreements（协议）、memorandums-of-understanding（谅解备忘录）、the-experts-authority-at-the-council-of-ministers（部长会议专家局）、the-royal-court（王室）、authorities（机构）。

## 2. 访问准备

- **无需 API key**，无需注册，无登录墙，无会话要求。
- 无已知反爬；站点 robots.txt（2026-10-10 查）对全体代理禁三类路径：`/*page=`、`/*redirect=`、`/ajax/`——本采集不使用这三类（枚举走 sitemap，不翻列表页）。
- 官方部分条目页每次响应约 0.8 MB（页面含大量模板代码），采集时建议保持默认限速节奏。
- 个别网络环境到该站 TLS 握手需禁用证书吊销检查（Windows curl 的 `--ssl-no-revoke`）；Python requests 无此问题。
- 沙特现行法规的另一权威库是部长会议专家局（هيئة الخبراء بمجلس الوزراء，Bureau of Experts）的 `laws.boe.gov.sa`——本采集未接入（网络可达性受限，另行立项）。

## 3. 抓什么：任务类型清单

| 任务类型 | 请求 | 产出 |
|---|---|---|
| `uqn_sitemap_month` | GET `https://www.uqn.gov.sa/sitemaps/{年}/{月}/sitemap_0.xml`（月不补零，如 `2026/9`） | 解析出该月全部官方部分条目 URL（含 `decisions-and-regulations/{id}` 与带分类前缀的变体，归一化为数字 id），每个条目生成一个 `uqn_item` 任务；scope 含 advertisements 时同样处理 |
| `uqn_item` | GET `https://www.uqn.gov.sa/decisions-and-regulations/{id}`（公告为 `/advertisements/{id}`） | 解析页面内嵌的结构化数据（JSON-LD 的 NewsArticle：标题、刊出日期；BreadcrumbList：分类），登记一份文档，页面 HTML 原字节落盘；并为其刊出日期播种一个 `uqn_issue` 任务 |
| `uqn_issue` | GET `https://www.uqn.gov.sa/digital?date={公历日}` | 从页面提取当期 PDF 分段链接；**页面内嵌的 PDF 文件名日期与请求日期不符 = 该日无刊**（网站对无刊日期静默回退到最近一期，必须核对）；匹配则每个分段播种一个 `uqn_issue_part` |
| `uqn_issue_part` | GET `https://www.uqn.gov.sa/cdn/?url=uploads/pdf/{Y}/{M}/{D}/ummalqura_pdf-{YYYYMMDD}-{N}.pdf` | 下载一期公报的第 N 段 PDF（一期可分多段，段号不保证从 1 开始，以期册页所列为准），登记为文档并落盘 |

两个站点事实决定了上面的设计：

1. **月度 sitemap 的"冻结块"现象**：2026-01 以前的月份文件与 2026 年部分月份文件内容是同一份全库快照（跨月重复），并非当月内容；因此枚举按"各月 sitemap 取并集"设计，重复条目由任务去重吸收。
2. **`/digital?date=` 的回退行为**：请求无刊日期，页面返回的是最近一期（HTTP 200，不报错）——所以以 PDF 文件名内嵌日期（`ummalqura_pdf-20261002-1.pdf` 中的 `20261002`）与请求日期核对，不符即该日无刊。

## 4. 数据落到哪

- **零领域表**：公报型源，公报刊出即定，每条目即文档本体，`documents` 表就是全部账本（与西班牙 BOE、法国 JORF 同款）。
- `documents` 关键字段：`title` = 页面 JSON-LD 的原生标题（阿拉伯语）；`publication_date` = 刊出日（公历，ISO 格式）；`doc_type` = 由面包屑分类映射的受控词表（DECREE / ORDER / REGULATION / OTHER）；`language` = `ara`；`source_url` = 条目规范 URL。
- 国家特色字段进 `meta`：
  - `uqn_id` — 站内数字 id（如 4001992）；
  - `kind` — `decisions`（官方部分）或 `advertisements`（公告）；期册分段为 `issue_part`；
  - `section` / `section_native` — 面包屑分类（英文 slug 与阿拉伯语原词）；
  - `native_number` — 从标题提取的文书号（如部长决定"رقم (70)"中的 70），提取失败留空；
  - `native_date_hijri` — 从标题提取的伊斯兰历签署日（如 `28/03/1448`），**原样保存不换算**；
  - `part` — 期册分段号。
- 文件布局（一项政策一个文件夹，年月分片）：

```
01_raw/uqn/{年}/D{YYYYMMDD}/{id}/item.html                          ← 条目页原字节（该文档主文件）
01_raw/uqn/{年}/D{YYYYMMDD}/issue/ummalqura_pdf-{YYYYMMDD}-{N}.pdf  ← 期册第 N 段 PDF（每段一份文档）
```

- `doc_id` 形如 `SAU_20261002_1a2b3c4d`（国家码_刊出日_来源 URL 哈希前 8 位），由框架统一计算。

## 5. 完整案例走查

以 2026-10-02 刊的一条部门决定走完全程（所有数字可从 state.db 复查）：

1. **枚举**：`uqn_sitemap_month`（2026-10）的 sitemap 给出条目 URL `https://www.uqn.gov.sa/decisions-and-regulations/4001992`；
2. **条目入账**：`uqn_item` 抓取页面（796,951 字节），从页面内嵌 JSON-LD 解析出标题«الموافقة على دليل تراخيص الاستيراد»（批准进口许可指南）与刊出时间 2026-10-02T15:00:00+03:00，从面包屑解析分类 قرارات وزارية（slug `ministerial-decisions`）→ `doc_type = ORDER`。documents 行：`doc_id = SAU_20261002_76428301`，`language = ara`，`source_url` 即上址，`meta = {"kind":"decisions","section":"ministerial-decisions","section_native":"قرارات وزارية","uqn_id":"4001992"}`；页面原字节落 `01_raw/uqn/2026/D20261002/4001992/item.html`（file_hash 前 16 位 `5c7bca26c22c943a`）；
3. **期册链**：该条目刊出日期播种 `uqn_issue`（date=2026-10-02）→ 期册页核对 PDF 文件名日期匹配 → 播种 `uqn_issue_part`（part=1）→ PDF（5,032,884 字节，sha256 与源站逐字节一致）落 `01_raw/uqn/2026/D20261002/issue/ummalqura_pdf-20261002-1.pdf`，登记为 `doc_id = SAU_20261002_ff223dc6`、`meta = {"kind":"issue_part","issue_date":"2026-10-02","part":"1"}`；
4. **原生元数据旁证**（同库另例）：皇家敕令 `SAU_20260911_*`（uqn_id 4001800）的 meta 带出 `native_number = "م/89"`、`native_date_hijri = "18/03/1448"`、`section_native = "مراسيم ملكية"`——文书号与伊斯兰历签署日从原生标题正则提出，公历刊出日单独存列，两历不换算。

2026-09:2026-10 窗口终态（2026-10-11 实测）：57 份文档（条目 51 + 期册 PDF 段 6），六个期册日期均为周五（09-04/09-11/09-18/09-25/10-02/10-09），doc_type 分布 REGULATION 19 / DECREE 18 / OTHER 11 / ORDER 9；磁盘 51 html + 6 pdf 与账本一一对应；7 条 sitemap 声称但站点 404 的条目按永久失败入账（证据存 failures/）。

## 6. 怎么跑

```bash
# 首次采集：闭区间月份窗（格式 YYYY-MM:YYYY-MM）
python cli.py collect --country sau --source uqn window=2026-09:2026-10

# 增量同步：从游标次月到当前月（当前月永远重走，新刊条目自动入账）
python cli.py collect --country sau --source uqn sync=1

# 连官方公告（إعلانات）一起收（默认只收官方部分）
python cli.py collect --country sau --source uqn window=2026-09:2026-10 sections=decisions,advertisements

# 全量重扫某窗（忽略已入账状态强制重走名录；条目级幂等，重复条目自动跳过）
python cli.py collect --country sau --source uqn window=2026-09:2026-10 refresh=1

# 只列计划不抓取
python cli.py collect --country sau --source uqn window=2026-09:2026-10 --dry-run

# 状态与导出
python cli.py status --country sau --source uqn
python cli.py export --country sau
```

## 7. 更新与增量

- 游标键 `uqn_last_month`（kv 表）：已确认完整消费到的月份（YYYY-MM）。`sync=1` 从游标次月播到当前月；**当月不推进游标**（月内随刊更新），每次 sync 都会重走当月——重走只多花 sitemap 请求，已入账条目按任务身份跳过。
- 条目一旦入账即终局（公报条目不修订；页面若被源站更正，可用 `refresh=1` 重扫该月拾取）。
- 期册任务由条目任务的刊出日期派生，无独立游标。

## 8. 已知边界与缺口

- **2012–2025 年老年代未采集**：老版网页条目无内联正文，全文只在期册 PDF（约 750 期 × 4 MB ≈ 3 GB）；期册页编址（`/details?p={id}`）与 PDF 直链（`wp-content/uploads/2022/10/العدد-{期号}.pdf`，阿拉伯文件名）已勘明，接入属回填工程另行立项。
- **1924–2011 年不在本站**：早期公报由国家档案与记录中心（المركز الوطني للوثائق والمحفوظات）管辖。
- 官方公告（إعلانات）默认不收（`sections=` 参数放开）；新闻（`/news/...`）一律不收。
- 某期若官方部分与公告全空（理论上不应发生），其期册 PDF 会因无条目日期而漏播——以首页"/digital?date="近几期链接人工核对为兜底。
- 期册 PDF 文件名的阿拉伯语与分段号变化（观测到一期仅含"第 2 段"的形状，2026-10-09 期）——一切以期册页所列为准，不做文件名猜测。
- 双历并存：条目标题/正文中的伊斯兰历（هـ）日期是**签署日**，JSON-LD 的公历日期是**刊出日**，两者相差常达数周；本采集分别保存、不做换算。

## 9. 端点速查表

在用：

| 端点 | 用途 |
|---|---|
| `GET /sitemaps/{Y}/{M}/sitemap_0.xml` | 月度条目枚举（月不补零） |
| `GET /decisions-and-regulations/{id}` | 官方部分条目页（全文内联） |
| `GET /advertisements/{id}` | 官方公告条目页 |
| `GET /digital?date=YYYY-MM-DD` | 期册页（内嵌当期 PDF 分段链接；无刊日回退最近一期） |
| `GET /cdn/?url=uploads/pdf/{Y}/{M}/{D}/ummalqura_pdf-{YYYYMMDD}-{N}.pdf` | 期册 PDF 分段下载（路径月日补零；URL 上的 ts 参数可省略） |

已勘明暂未用：

| 端点 | 说明 |
|---|---|
| `GET /sitemap_0.xml` | sitemap 总索引（2012-03 起；作者/分类两份附加索引） |
| `GET /details?p={id}` | 老年代页面（新闻/条目/期册混合，无内联正文；期册页含 `wp-content/uploads/2022/10/العدد-{期号}.pdf` 直链） |
| `GET /decisions/{category}` | 分类列表页（内容经 `/ajax/` 加载，robots 对全体代理禁抓，不使用） |
| `GET /rss` | 名为 RSS 实为 HTML 新闻页，不是数据通道 |
| `GET /pdf-download/{id}` | 期册下载路由（/cdn/ 直链已够用） |

---

*更新日期：2026-10-11；数据快照：2026-10-11；数据由 window=2026-09:2026-10 首次采集运行（57 份文档，2026-09-04 至 2026-10-09）背书。*
