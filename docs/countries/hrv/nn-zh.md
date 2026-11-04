# 克罗地亚官方公报平台 nn 数据源说明

> **读者定位**：外部开源用户第一——假定读者只会用命令行、对本项目一无所知。克罗地亚语词汇首现给出中文释义。
> 本文配套总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

**Narodne novine**（国民官报，下称 NN）是克罗地亚共和国的官方公报（Službeni list Republike Hrvatske，"共和国官方法定公报"）：法律、政府条例及各类法规在其上刊出后方才生效。出版方是 **Narodne novine d.d.**（dioničko društvo，股份公司）——一家国家为多数股东的出版企业（1952 年成立，总部萨格勒布），官报出版义务的宪法基础是克罗地亚宪法第 90 条第 1、2 款。这是本项目内第三种官报治理形态样本：官报不由国家机关自办，而由国有公司出版运营（对比：爱沙尼亚司法部自办、瑞士联邦体制多渠道）。

机器入口是官方检索平台 **NN Tražilica**（tražilica = 检索器，`narodne-novine.nn.hr`，2026-11-01 实测）。平台免费、无注册、无 API key、无反爬墙；内容自 **1990 年**起逐年完整数字化（1990 年是独立前的社会主义克罗地亚末年；更早的南斯拉夫联邦时代不在此平台）。截至 2026-11-01 的全量量级估计：**约 96,000 条刊出条目 / 约 5,500 期**（由 14 个抽样年度清单外推；精确值 = 每年一次清单请求）。

平台把内容分三个系列（dio，"部分"）：

| 系列 | 内容 | 本文是否采集 |
|---|---|---|
| **Službeni dio**（官报正文） | 法律、条例、决定等法规与官方文件 | ✅ 采集（法院与司法委员会条目除外，见 §8） |
| Međunarodni dio（国际条约部分） | 国际条约（narodne novine – Međunarodni ugovori） | ❌ 未采集（端点已勘明，见 §8） |
| Oglasni dio（广告部分） | 破产公告、招标、司法公告等 | ❌ 不采集（站点 robots.txt 禁止抓取该系列） |

正文载体分两代（2026-11-01 实测）：**1990–2022 年**条目页 HTML 内嵌全文（老年代为平台侧已识别的印刷版文本）；**2023 年起**条目页改以数字原生 PDF 承载正文（HTML 页面保留元数据、正文在出版后滞后补录）——两代都是数字文本，全库无扫描件，不需要本地 OCR。

## 2. 访问准备

- **无需 API key**，无需注册，无需会话（登录 cookie 与请求无关）。
- **无反爬墙**：默认 `python-requests` 的 User-Agent 直接可用（2026-11-01 实测）；服务器为 Microsoft-IIS/ASP.NET。
- **礼貌速率**：框架传输层的全局限速闸门即可覆盖探查与常规采集；大跨度历史回填（全量约 11 万请求）建议分年份分批、批间长间隔——参照本项目智利先例（约 35 万请求后触发累计型 IP 封锁）。
- **robots.txt 合规**：官报正文系列整体放行；广告系列（`/clanci/oglasi/`）与广告检索（`kategorija=3`）被禁止——本源不触碰；另有少数单条 URL 被站方下架（robots 逐条列禁），采集时按路径精确匹配跳过。
- 地址体系为 **ELI**（European Legislation Identifier，欧洲立法标识符）：`/eli/sluzbeni/{年}/{期号}/{条目全局号}`，例如 `/eli/sluzbeni/2026/124/1481`。

## 3. 抓什么：任务类型清单

| 任务类型 | 请求 | 产出 |
|---|---|---|
| `nn_index` | `GET /get_index_file.aspx?year={年份}&type=csv`（官方名 "Popis svih propisa"，年度全部法规清单） | 解析 Tab 分隔清单（约 1,200–4,300 行/年），每行派生一个 `nn_doc` 种子；范围过滤在此层执行 |
| `nn_doc` | `GET /eli/sluzbeni/{年}/{期}/{全局号}`（301 跳转到条目 HTML 页） | 元数据块 + 正文（若在）：登记文档、正文 HTML 原字节落盘为主文件；**正文未录**（仅 2023+ 近期条目）：派生 `nn_pdf` 种子，HTML 页存为附属文件 |
| `nn_pdf` | `GET /eli/sluzbeni/{年}/{期}/{全局号}/pdf`（条目级 PDF，2023+ 才存在） | 登记文档（主文件 = PDF），同条目的 HTML 页路径记入 `meta.files` |

年度清单 CSV 的 8 列：`Izdanje`（期号，如 `NN 124/2026`）、`Broj dokumenta`（条目全局号，**跨年连续**）、`Naziv dokumenta`（标题）、`Vrsta dokumenta`（文档类型，如 `uredba`）、`Podvrsta dokumenta`（子类型，类型为 `ostalo` 时才有值）、`Cjeloviti dokument/izmjene/dopune/ukinut`（关系标记：完整文本/修改/补充/废止/更正）、`Donositelj dokumenta`（发布机关）、`Poveznica`（ELI 直链）。

## 4. 数据落到哪

- **零领域表**：一个刊出条目 = `documents` 表一行，无跨文档持久实体（法规间修订/废止关系以 `relation` 原生字段随行记录，不建图）。
- `documents.meta` 溢出列保存国家特色字段：`issue` / `issue_no`（期号）、`year`、`global_ordinal`（全局号）、`native_type` / `subtype`（原生类型/子类型，原文永存）、`relation`（关系标记原文）、`nn_part`（所属系列）、`printed_page`（印刷版页码，新年代才有）、`eli`（ELI 路径）、`body_carrier`（正文载体 `html`/`pdf`）、`csv_title`（清单标题，与页面标题留双源对照）；PDF 载体条目另记 `files`（HTML 附属文件路径）。
- `doc_type` 受控映射（原生词永存 `native_type`）：`zakon`（法律）/`ustav`（宪法）→ STATUTE；`uredba`（政府条例）/`pravilnik`（部委规章）/`naredba`（命令）→ REGULATION；其余一律 OTHER。
- 文件布局（data_root 下 `{ISO3}_policy/` 内）：

```
01_raw/nn/
├── 1990/1_1.html          ← {年}/{期}_{全局号}.html（1990–2022 主文件：正文 HTML）
├── 2026/124_1481.html     ← 2023+ 正文未录时：HTML 页存根（meta.files）
└── 2026/124_1481.pdf      ← 同条目的 PDF（主文件，raw_format=pdf）
```

## 5. 完整案例走查

以 2026 年第 124 期（2026-10-30 出版）第 1481 号条目《Uredba o visini minimalne plaće za 2027. godinu》（2027 年最低工资额条例）为例——出版当日抓取，正文尚未录入 HTML，按 PDF 载体路径走完全程：

1. `nn_index year=2026` 下载年度清单，第 1481 行给出：期号 `NN 124/2026`、标题、类型 `uredba`、关系标记 `cjeloviti akt`（完整文本）、发布机关 `Ministarstvo rada, mirovinskog sustava, obitelji i socijalne politike`（劳动、退休制度、家庭与社会政策部）、ELI 直链。
2. `nn_doc` 抓条目页：元数据块给出公布日 `30.10.2026.`、印刷页码 1、ELI 路径；正文容器内是 PDF 视图（`pdf-view`）而非正文——判定正文未录，派生 `nn_pdf`。
3. `nn_pdf` 下载条目 PDF（57,779 字节，2 页，数字原生带文字层）为主文件，登记 `documents` 行：`doc_id = HRV_20261030_34c878e8`（日期 = 公布日）、`raw_format = pdf`、`meta.files = 01_raw/nn/2026/124_1481.html`（HTML 存根随行可查）。

对照老世代案例：1990 年第 1 期第 1 号《Odluka o donošenju Prostornog plana Nacionalnog parka »Krka«》（克尔卡国家公园空间规划决定，1990-01-16 出版）——`nn_doc` 一次请求即得元数据与全文（HTML 内嵌，57,932 字节页面），主文件即该 HTML 页，`raw_format = html`，`doc_id = HRV_19900116_83cf13b5`。两条记录的字段口径完全一致，仅 `body_carrier` 与 `raw_format` 不同。

（以上数字可在账本中复查：`python cli.py status --country hrv --source nn`。）

## 6. 怎么跑

```bash
# 首次采集：指定年份（可带期内序号窗口）
python cli.py collect --country hrv --source nn year=2026 issues=122:124
python cli.py collect --country hrv --source nn year=1990

# 多年区间
python cli.py collect --country hrv --source nn years=1990:1999

# 增量同步（当前年清单重走，已抓条目自动跳过）
python cli.py collect --country hrv --source nn sync=1

# 注意：sync=1 覆盖全年清单（约 1,400+ 请求）；只想刷新最新几期时加期内窗口
python cli.py collect --country hrv --source nn sync=1 issues=120:124

# 范围口径：policy（默认，排除法院条目）| all（全收）
python cli.py collect --country hrv --source nn year=2026 scope=all

# 演练（只列计划不抓取）
python cli.py collect --country hrv --source nn year=2026 --dry-run

# 状态查询 / 修复
python cli.py status --country hrv --source nn
python cli.py requeue --country hrv --task <task_id>
```

参数：`year=` 与 `years=A:B` 与 `sync=1` 三选一（缺省报错并打印用法）；`issues=A:B` 可选（期内序号窗口，过滤后零条目会响亮报错——窗口配置错应当场暴露）。

## 7. 更新与增量

本源按**年度清单**编址，不是日期分区，因此没有日期游标；增量走**清单重走模式**：`sync=1` 以当前时间戳为刷新标识重新下载当年清单并逐行派生任务——已完成的条目任务按确定性身份跳过（成本 = 每次一个清单请求），清单里新增的条目（新刊期）自然补抓。清单行出现即条目已刊出，无需"到昨天为止"的保守窗口。

一条内容规则值得知道：2023+ 条目的 HTML 正文是出版后**滞后补录**的。首次抓取时正文未录的条目以 PDF 为主文件、正文即告完整；之后 HTML 正文即使补录也不再回访（PDF 是官方排版的权威载体）。两种载体下条目正文都完整，滞后只影响载体选择、不影响内容完整性。

## 8. 已知边界与缺口

- **法院条目不采集**（默认口径 `scope=policy`）：发布机关为法院或司法委员会（机关名整词含 `sud`/`sudbeno`）的条目在清单层过滤，约占各年 6–11%。代价如实记录：宪法法院"废止某法规"的裁定事件不进语料（被废止法规自身的刊出条目在语料内；法规间修订/废止关系另有清单原生字段随行保存）。`scope=all` 可放开。
- **发布机关为 `-`（清单未填）的行**无法按机关判别，照常采集（约 300 条/年，多为授勋等总统行为）。
- **国际条约系列（Međunarodni dio）未采集**：其枚举通道已勘明（`/ajax/getEditionMaxNumber.aspx?category=2&year=` 给各年最大期号 + `search.aspx?kategorija=2` 逐期列表 + 同款条目页），扩展成本约为一个枚举任务类型。
- **条目附件未采集**：部分条目（空间规划附图类）另有附件 PDF（`/clanci/sluzbeni/dodatni/{id}.pdf` 形态），本源只收条目主文件。
- **整期合订 PDF 未采集**：2023+ 各期有整期 PDF（`/eli/sluzbeni/{年}/{期}/pdf`），条目级 PDF 已覆盖正文需求，合订本留作未来扩展。
- 2026 年内 `raw_format` 混载（html/pdf 并存）属设计内形态：按 `body_carrier` 字段区分，下游按 `raw_format` 分流处理。
- 老年代（约 1990–2000 年代初）正文为平台侧 OCR 文本，个别字符可能有识别误差——这是源数据的固有状态，随源保存。

## 9. 端点速查表

**在用**：

| 端点 | 用途 |
|---|---|
| `GET /get_index_file.aspx?year={Y}&type=csv`（`type=xlsx` 可换格式） | 年度全部法规清单（主枚举） |
| `GET /eli/sluzbeni/{Y}/{N}/{G}` | 条目页（元数据 + 正文/正文状态） |
| `GET /eli/sluzbeni/{Y}/{N}/{G}/pdf` | 条目级 PDF（2023+，正文未录时的主文件） |

**在站未用**（备查）：

| 端点/资源 | 一句话价值 |
|---|---|
| `/ajax/getEditionMaxNumber.aspx?category={1\|2}&year={Y}` | 各年最大期号（国际条约系列枚举上界） |
| `/search.aspx?kategorija={1\|2}&godina={Y}&broj={N}` | 逐期条目列表（国际条约系列的唯一枚举通道；正文系列用清单 CSV 更省） |
| `sitemap_{系列}_{年}_{块}.xml` | 全站 URL 索引（对账基准：sluzbeni 1990–2026、medunarodni 1996–2026、oglasni 1992–2026） |
| `/ajax/get.aspx?m={月}&g={年}` | 广告系列按月期号 JSON（本源不用） |
| `/files/kazalo_pdf/kazalo_{pojmovno\|kronolosko}/{Y}.pdf` | 平台自印的概念/编年索引 PDF（1997–2025） |

---

*更新日期：2026-11-01；数据快照：2026-11-01；数据由 2026-11-01 试运行窗口（2026 年第 122–124 期 + 1990 年第 1–2 期）背书。*
