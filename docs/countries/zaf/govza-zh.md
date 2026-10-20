# 南非政府门户文档库（govza，ZAF）数据源说明

> 源代号 `govza` = 南非政府网站 www.gov.za 的文档门户（Documents 检索 + 详情页 + PDF 直链）。

## 1. 源概览

南非政府门户由政府传播与信息系统（Government Communication and Information System，缩写 GCIS）运营，其 `/document` 检索页是官方政策文档的统一索引：政府公报（Government Gazette）的各类公告（行内自带公报号如 `G. 51889`、规章公报号如 `RG 11783`、公告号如 `GeN 2930`）、法案（Acts，行内自带 `Act 47 of 2024` 式编号）、议案（Bills / Draft bills）、宪法及修正案、绿皮书与白皮书等。公报的法定出版者是政府印刷局（Government Printing Works，缩写 GPW），约 2012/13 年起公报电子版与印刷版同等法律效力；gov.za 是官方发布渠道之一，其文档记录均指向公报原文 PDF。

关键数字（2026-10-10 实测）：检索页每页 30 行、服务端日期过滤；收录深度约自 1994/95 年起（白皮书等），**公报类公告约自 1999/2000 年起**；2025 年初约每天 3 条（周三 2025-01-08 无刊），2000 年初约每天 0.7 条；正文以内挂 PDF 交付（`/sites/default/files/gcis_document/{年月}/{文件}.pdf`），2002/2005/2025 三个年代样本均有真实文本层（非扫描件）。

## 2. 访问准备

- **无需 key**：全程匿名 GET，无会话、无 cookie、无限额公示。
- `robots.txt` 放行 `/document` 与文档页（仅禁 `/search/`、后台路径；2026-10-10 核对）。
- 反爬：未见拦截；响应偏慢（列表页 2–3 秒），用 `--delay 2:4` 起步。大批量回填遵循"小批量、长间隔"，防止累计型封锁。
- `sitemap.xml` 是 3 万条封顶的单表（2026-10-10 抓取核对），不能当全量清单用——本源枚举只走日期过滤检索页。

## 3. 抓什么：任务类型清单

| 任务类型 | 请求 | 产出 |
|---|---|---|
| `govza_list` | `GET /document?field_gcisdoc_document_date[min]=日&[…max]=日[&page=N]` —— 一天一任务（首页） | 每行一条 `govza_detail` 种子（行内自带链接、标题、文档日、类型、公报号）；满页 30 行时追加同型翻页种子；空窗（页面上是 `No Results`）为合法空产出且推进日游标 |
| `govza_detail` | `GET https://www.gov.za{文档路径}`（如 `/documents/notices/…`） | 文档行（标题/日期/类型/公报号全部来自列表行——详情页不重复携带这些字段）+ 详情页 canonical 链接身份核验 + 抽取 PDF 链接；有 PDF → 派 `govza_file`；无 PDF（早期白皮书类）→ 详情页 HTML 本身即主文件 |
| `govza_file` | `GET` 详情页给出的 PDF 直链 | `doc.pdf` 落盘挂账（必须 `%PDF` 魔数起头）；404 按永久失败处理（门户链接了文件而文件缺失 = 真实链接腐坏，引擎归档到 `failures/`） |
| `govza_clean` | 本地读（不走网络） | 格式嗅探分流：PDF → 扫描底线（<20 字符文本即判扫描件，永久失败出界）→ 本地几何通道抽文本；HTML → 白名单容器 `div.field--name-body` 抽文本 |

行解析要点（真实形状，2026-10-10 固化）：行内有两个 `<time>`——标题格里是"Comment by"评论截止日，**日期格才是文档日**；类型格链接有两种形状（`/taxonomy/term/{id}` 与 `/documents-categories/{slug}`，后者是试跑中归档的真实失败样本修正的），两者归一到同一原生类型名。

## 4. 数据落到哪

- **零领域表**：公报型扁平路径，`documents` 表即全部台账（一文档一条公告/一部法案，一行一个出台事件）。
- **meta 溢出列**收：`href`（门户路径）、`native_type`（门户原生类型词，如 Notices / Acts）、`term_id`（类型分类号，仅有该形状时）、`gazette_numbers`（公报号，多值逗号隔）、`regulation_gazette_numbers`（规章公报号）、`notice_codes`（公告号 GeN/GoN/BN）、`act_refs`（法案编号如 `Act 47 of 2024`）、`comment_by_date`（评论截止日）、`pdf_urls`（详情页全部 PDF 链接）。
- **文档类型映射**（保守，只映射不加猜）：Acts / Constitution / Constitutional amendments → `STATUTE`；Bills / Draft bills → `BILL`；**其余（含 Notices）一律 `OTHER`**——公告是否属法规是语义判断，留给分析端；原生词永存 `meta.native_type`。
- 文件夹布局（一项文档一个文件夹，slug 即门户 URL 尾段）：

```
01_raw/govza/2025/01/electronic-communications-act-application-amendment-individual-commercial-19/
└── doc.pdf            ← 129,096 B（2025-01-10 实收）
02_cleaned/6f/ZAF_20250110_48e56e56.txt   ← 框架派生路径
```

## 5. 完整案例走查

以 2025-01-10 窗口实收的一条 IASA 公告为例（每个数字都可在 state.db 复查）：

1. 列表行（2025-01-10，6 行之一）：标题 "Electronic Communications Act: Application for amendment of Individual Commercial Sound Broadcasting Service and Radio Frequency Spectrum Licences by Yired (Pty) Ltd t/a YFM: Comments invited"，公报号 **G. 51889**，公告号 **GeN 2930**，评论截止 2025-02-07。
2. `govza_detail` 命中 `/documents/notices/electronic-communications-act-application-amendment-individual-commercial-19`，canonical 核验一致，抽得 PDF 直链 `/sites/default/files/gcis_document/202501/51889gen2930.pdf`。
3. `govza_file` 落盘 `01_raw/govza/2025/01/electronic-communications-act-application-amendment-individual-commercial-19/doc.pdf`，**129,096 字节**，挂 `doc_id = ZAF_20250110_48e56e56`（`{ISO3}_{YYYYMMDD}_{hash8(source_url)}`）。
4. documents 行：`publication_date = 2025-01-10`、`doc_type = OTHER`（原生词 Notices 存 meta）、`language = eng`。
5. `govza_clean` 几何通道抽得 **4,286 字符**纯文本（`02_cleaned/6f/ZAF_20250110_48e56e56.txt`），开头即公报原文报头 "STAATSKOERANT, 10 JANUARIE 2025 / GENERAL NOTICE / INDEPENDENT COMMUNICATIONS AUTHORITY…"，正文里的公报号与列表行一致（对账通过）。

该窗口（2025-01-06 至 2025-01-10）合计：15 份文档、15 份 PDF（103,592 ~ 2,469,930 字节）、清理 15 份（235 ~ 176,104 字符）；2025-01-08 为真实空窗（门户答 `No Results`）。

## 6. 怎么跑

```bash
# 首次 / 指定窗口采集（逐日种子，温和限速）
python cli.py collect --country zaf --source govza window=2025-01-06:2025-01-10 --delay 2:4

# 增量同步（游标次日 → 昨天）
python cli.py collect --country zaf --source govza sync=1

# 全门户镜像口径（含采购公告与年报；改口径 = 新任务身份自动补抓，零清库）
python cli.py collect --country zaf --source govza window=2025-01-06:2025-01-10 scope=all

# 试算（只打印种子，不请求不落账）
python cli.py collect --country zaf --source govza window=2025-01-06:2025-01-10 --dry-run

# 清理（本地读，已清理的文档自动跳过）
python cli.py clean --country zaf --source govza

# 状态 / 修复
python cli.py status --country zaf --source govza
python cli.py requeue --country zaf --id <task_id>
```

## 7. 更新与增量

- **游标**：kv 键 `govza_last_date` = 已确认消费到的文档日。一天的最后一块（不满 30 行的页，或 `No Results`）完成时推进；空窗也推进——周末与无刊日是完整消费，不是故障。
- **sync 口径**：从游标次日到**昨天**。当天内容可能晨间未上架，"尚未上架"与"当日无刊"同形，永不认领今天。
- **重开**：门户无更新信号字段，任务 done 即终局。同批任务重跑幂等（done 跳过、零重复传输）；补录/更正的老文档靠修复通道或 `scope` 放宽（参数化重开）。
- **游标回退是良性的**：手工重跑老窗口后 last-wins 可能把游标带回几天——随后的 sync 会重扫重叠区，重叠任务全部 done 跳过，零成本自愈（2026-10-10 试跑实测此路径）。
- 终局性：一份公报公告刊出即定，_portal 后续改动（改标题、补文件）属源站数据质量，不触发重抓。

## 8. 已知边界与缺口

- **公报类覆盖起点约 1999/2000 年**：更早年份门户只有白皮书等散档（1994-05 窗实测为空）。早期收录稀疏且不保证完整——GPW 才是公报的法定完整档案。
- **个别老记录日期错**：2000 年代回溯数字化批次（PDF 集中在 `/201409/` 上传）中有个别文档日错案（实测 1 例：列表日 2000-01-06，公报 PDF 自印 2002-09-06，G. 23798）。公报号随 meta 收录，可对账；清理阶段可据 PDF 报头复核。
- **清理产出的页眉/页脚伪影**：公报 PDF 的装饰性报头（STAATSKOERANT 刊头、部门名侧栏、AIDS helpline 页脚）在几何通道里会错序、双栏互串（如 "DEPARTMSETANATTOSFKOHEIGRHAENRT…"）或丢装饰字首字母（"oewermentskennisGewinGs"）；正文经抽验无此问题（2026-10-10，15 份全检：正文连续完整）。清理规则有版本号，将来可升级重清，无需重抓。
- **双语文档**：公报常为英语/南非语双语（如 "Global Minimum Tax Administration Act 47 of 2024 (English / Afrikaans)"），`language` 一律记 `eng`（门户主语言），双语的原文标题自带注记。
- **issuing_authority 空**：门户行与详情页都不带发布机关字段，记缺。
- **9 省公报、判例、议会过程**：不做（总览第 3 节）。

## 9. 端点速查表

**附录一：在用端点**

| 端点 | 用途 |
|---|---|
| `GET /document?field_gcisdoc_document_date[min]=…&[…max]=…&page=N` | 日期过滤检索页（枚举唯一通道，30 行/页） |
| `GET /documents/{类型}/{slug}` | 文档详情页（canonical + PDF 链接 + 无 PDF 档的正文） |
| `GET /sites/default/files/gcis_document/{YYYYMM}/{文件}.pdf` | 公报/法案原文 PDF |

**附录二：暂未用的信息面**

| 端点 / 信息 | 一句话研究价值 |
|---|---|
| `field_gcisdoc_doctype={term_id}` / `field_gcisdoc_subjects={term_id}` | 检索页的类型/主题过滤参数（91 个主题分类）；按主题圈定子库时可省请求，但会破坏逐日游标语义，故默认不用 |
| `/taxonomy/term/{id}` 与 `/documents-categories/{slug}` | 类型词表的两种链接形状，已用于行解析归一 |
| GPW `efiling.gpwonline.co.za` 与 gpwonline.co.za 公报库 | 法定出版者的自有档案；2026-10-10 本网络不可达（连接失败/404），开放后可作第二源 |
| SAFLII / OpenGazettes / lawlibrary.org.za | 第三方公报存档（对账用）；2026-10-10 分别 403 反爬 / 连接失败 / 未接 |
| gov.za `sitemap.xml` | 3 万条封顶单表，只可当抽样面，不可当全量清单 |

---
*更新日期：2026-10-10；数据快照：2026-10-10；数据由 2026-10-10 试跑窗口（2025-01-06 至 2025-01-10，15 份文档）背书。*
