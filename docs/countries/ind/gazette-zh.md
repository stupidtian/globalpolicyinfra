# Gazette of India（egazette）数据源说明（IND）

## 1. 源概览

Gazette of India 是印度联邦的法定公布媒介（《1897 年通用条款法》第 3(24) 条：Official Gazette 即 Gazette of India；第 22 条：规则未经其公布不生效），由住房与城市事务部出版署（Department of Publication）发行、国家信息中心（NIC）托管门户 [egazette.gov.in](https://egazette.gov.in)。一切联邦法律（Acts）、法令（Ordinances）、条例（Regulations）、部委规则与法定命令经其刊出——一次刊登 = 一条数据，as-made 原样快照。

- **覆盖年份**：门户目录下拉提供 1926–2026 全部年份；**2020 年起条目带全局编号（UGID）且 PDF 可直接下载**；2019 年及以前仅列元数据（标题/体量/日期），电子件无已发现的程序化交付通道（2026-10-16 实测）。
- **体量**（2026-10-16 实测抽样，声明文件体量合计）：号外版 Part II-Section 3 子节 (ii)（法定命令+通知）~10GB/年为体量之首；Section 1（法律）~131MB/年、Section 3 子节 (i)（部委规则 G.S.R.）~2.0GB/年、Part I-Section 1 ~1.0GB/年。联邦条目编号形如 `CG-DL-E-14102026-277148`（CG-地区-版式-日月年-全局流水号；DL=德里印厂=联邦，其余为邦，出本包范围）。
- **技术形态**：ASP.NET WebForms 会话制页面 + 静态 PDF 直存路径，无文档化 API，全程免 key、无验证码（2026-10-04..16 多轮实测）。

## 2. 访问准备

**无需 key**。三个必须知道的访问事实（均实测留证）：

1. **会话**：门户根 URL 302 进入 `/(S(会话号))/default.aspx` 的无 cookie 会话；其后每一深页请求必须携带**同一会话号**的 URL 前缀，且 **Referer 指向同会话的 default.aspx**——缺任一即被弹至 error.aspx（网页存档爬虫普遍中此招，非反爬墙）。会话号取首页渲染中出现次数最多的 `(S(…))`（资产路径重复当前会话号；页面另有一枚指向旧域的陈旧硬编码链接，取首个会取错）。
2. **TLS**：门户只下发叶证书、不发 Let's Encrypt 中间证书，且签发者在 YR1/YR2 间轮换（2026-10-16 实测）。Python 运行环境需设 `REQUESTS_CA_BUNDLE` 指向合并了 [Let's Encrypt 全部中间证书](https://letsencrypt.org/certificates/) 的 CA 包；浏览器与 Windows 原生 TLS 不受影响（自动补抓）。
3. **网络路径**：自部分网络（中国大陆，2026-10-04/15 实测）直连 443 端口 TCP 级不可达，经标准 `HTTPS_PROXY` 环境变量走代理即可，采集框架原生识别。

## 3. 抓什么：任务类型清单

| 任务类型 | 请求 | 每次产出 |
|---|---|---|
| `gz_home` | `GET /`（跟随 302 建会话） | 解析会话号；按命令行参数派生 `gz_recent` 与/或 `gz_dir_open` |
| `gz_recent` | `GET /(S(会话号))/RecentUploads.aspx?Category=1`（带 Referer） | 最近上传列表第 1 页（20 行）中联邦行的文件任务 |
| `gz_dir_open` | `GET /(S(会话号))/GazetteDirectory.aspx`（带 Referer） | 捕获回发表单状态（VIEWSTATE 等，走任务 signal 字段传递） |
| `gz_dir_cat` | `POST GazetteDirectory.aspx`（类别级联） | 重绘的 Part/Section 选项与新表单状态 |
| `gz_dir_search` | `POST GazetteDirectory.aspx`（类别+Part+年份检索） | 检索结果第 1 页中联邦行的文件任务；零行 = 合法空 |
| `gz_file` | `GET /WriteReadData/{年}/{流水号}.pdf`（免会话裸 GET） | 一份公报 PDF 落盘 + documents 行入账 |

命令行参数：`recent=1`（最近窗口）与/或 `dir=年:节码:类别[,…]`（目录回填；类别 `EO`=Extra Ordinary、`W`=Weekly；节码用门户原值，如 `1`=Part I-Section 1、`5`/`62`=Part II-Section 1 双码、`8`=Part II-Sec 3(i)）。两类参数可组合，至少给一个。

## 4. 数据落到哪

无领域表——公报条目即文档本体，扁平模型，`documents` 表承担全部账目：

- 固定列：`title`（行主题 Subject）、`publication_date`（行 PublishDate，ISO 化）、`doc_type`（OTHER；原生版式 E/W 在 meta）、`source_url`（规范 PDF 地址）、`language`（eng）、`issuing_authority`（出版署）。
- `meta` 溢出列：`ugid`、`region`、`native_type`（E/W）、`category`、`part_section`、`ministry`、`department`、`office`、`issue_date`、`file_size`、`source=egazette`。

目录布局（一项政策一文件夹原则的公报形态：按年分片，UGID 即实体夹）：

```
01_raw/gazette/2026/CG-DL-E-14102026-277148.pdf   ← 一份公报 PDF
```

## 5. 完整案例走查

一条真实入账行（2026-10-15 采集，账本可复查）：

```
doc_id            = IND_20261014_31a36f84
title             = Publication of notification in the official Gazette Extraordinary
                    Part II Section 3 Sub Section ii us 20 A of Railways Act 1989 …
                    (北方铁路特别铁路项目征地公告，标题全文在账)
publication_date  = 2026-10-14
doc_type          = OTHER          raw_format = pdf       language = eng
source_url        = https://egazette.gov.in/WriteReadData/2026/277148.pdf
local_path        = 01_raw/gazette/2026/CG-DL-E-14102026-277148.pdf
file_hash         = ee4a24ae…8022044 (sha256)      content_length = 1,072,715 B
produced_by       = gz_file_b1c7b484490f
meta              = ugid=CG-DL-E-14102026-277148, region=DL, native_type=E,
                    category=Extra Ordinary, part_section=Part II-Section 3-Sub-Section (ii),
                    ministry=Ministry of Railways, department=Northern Railway,
                    issue_date=2026-10-12, file_size=1.02 MB
```

链路：`gz_home` 建会话 → 目录检索（2026 年 Part II-Section 3-Sub-Section (ii)，号外版）命中该行 → `gz_file` 由 UGID 尾段流水号 277148 构造免会话地址下载 → 落盘 + 入账。

## 6. 怎么跑

```bash
# 首次/任意采集：最近窗口（最新 ~100 期的第 1 页，20 份）
python cli.py collect --country ind --source gazette recent=1 --delay 2:4

# 目录回填：按 年:节码:类别 检索（逗号分隔多组）
python cli.py collect --country ind --source gazette "dir=2025:5:EO,2025:62:EO,2025:8:EO" --delay 2:4

# 状态与修复
python cli.py status --country ind --source gazette
python cli.py requeue --country ind --source gazette   # 失败任务回队
```

TLS 与代理环境变量（§2）需在运行前设置。重跑幂等：会话链任务每轮新建（会话制权衡），文件任务按稳定身份跳过，已下载文件不会重抓（2026-10-15 四轮实测收敛）。

## 7. 更新与增量

- **增量入口 = 最近窗口**：门户"最近上传"保存最新 ~100 期（约 3 天）；当前接入其第 1 页（最新 20 期）——**每日或隔日运行一次 `recent=1` 即可无漏**；更早的补漏走目录检索 `dir=`。
- **回填入口 = 目录检索**：类别（号外/周报）× Part/Section × 年份（1926–2026）。注意**同节存在两枚代码（如 Part II-Sec 1 的 5 与 62），各持一年中不同月份的数据，须双收**，文件身份层自动去重。
- 无自动同步游标（kv 水位线未实现）；`recent=1` 的窗口语义（3 天）即增量保证。

## 8. 已知边界与缺口

- **2000–2019**：目录仅列元数据，无程序化下载通道（详见 §1）；2020 起全通。
- **翻页未接入**：最近窗口与目录检索结果各只取第 1 页（20/15 行）——目录检索翻页为回填前置件（回发机制与已接入的级联相同）。
- ** Sec 3(ii)（法定命令+行政通知，~10GB/年）默认不采集**；生效令多刊于此节，其日期信息由 India Code 元数据部分补偿。
- **周报（Weekly）目录索引残缺**：部分节仅单月数据（2026-10-16 实测），周报真实体量需与最近窗口交叉校准。
- **清洗未接入**：源未声明 clean 规则（PDF 全几何通道可用，待接）。
- 大文件超时：传输层默认 30 秒超时，周报整期 PDF 可达 8.6MB，慢网络下可能重试。
- 邦级公报（CG-非DL 行）在最近窗口中会被计数并跳过（出界）。

## 9. 端点速查表

**在用**：

| 端点 | 用途 |
|---|---|
| `GET /` → `/(S(会话号))/default.aspx` | 建会话 |
| `GET /(S)/RecentUploads.aspx?Category=1` | 最近上传窗口（Category 1=全部，2–5=分版式） |
| `GET/POST /(S)/GazetteDirectory.aspx` | 目录检索（类别×Part/Section×年份级联） |
| `GET /WriteReadData/{年}/{流水号}.pdf` | 公报 PDF 直存（免会话） |

**未用（研究价值一句话）**：

| 端点 | 价值 |
|---|---|
| `DefaultHindi.aspx` | 印地语门户（印地语公报采集入口） |
| `RecentUploads.aspx?Category=2..5` | 按版式分列的最近窗口（号外/周报分列增量） |
| `StateGazette.aspx` | 邦级公报入口（36 邦，出界可回补） |
| `GazetteDirectory.aspx` 年份 1926–2019 | 历史元数据（体量/主题/日期；电子件通道未解） |
| `ContentsOfGOINot.pdf` | 官方各 Part/Section 内容定义（分类权威） |
| `GazetteDirectory.aspx?Category` 下 Sec 2 | 法案一读与专委会报告（过程材料） |

---

*更新日期：2026-10-16；数据快照：2026-10-15；数据由 2026-10-15 四轮真实采集（40 任务 / 20 文档 / 20 PDF 魔数校验）背书。*
