# 新西兰官方公报(New Zealand Gazette)数据源说明

> 源代号 `gazette`。覆盖 2000 年 1 月 1 日至今新西兰官方公报的全部通知,含政府类(次级立法、土地公告、部委通知、总督文告等)与商业类(破产、清算、社团登记等)全部类型。2026-10-14 完成全量回填:2000-01-01 至 2026-10-11 共 207,289 条,与聚合接口逐年计数全等。

## 1. 源概览

新西兰官方公报(New Zealand Gazette,毛利语名 Te Kāhiti o Aotearoa)创刊于 1841 年,由内政部(Department of Internal Affairs,DIA)公报办公室出版,是政府法定通知的官方刊登刊物——许多法律明确以"刊登于公报之日"起算生效。公报网站本身(gazette.govt.nz)有商业反爬虫防护且其检索与 PDF 路径在 robots 协议中明令禁止抓取,因此本源不走公报网站,而走公报办公室授权给 **DigitalNZ** 的开放接口——DigitalNZ 是新西兰国家图书馆运营的全国数字藏品聚合平台,公报的元数据与全文在其中以"New Zealand Gazette"集合开放,元数据采用知识共享 CC-BY 3.0 新西兰许可,正文为新西兰政府版权。

关键数字(2026-10-14 全量回填对账):账本 207,289 条,逐年与聚合接口全等——2000 年 9,271 条、2005 年 8,624 条、2009 年 10,389 条(历史峰值)、2015 年 7,415 条、2019 年 5,155 条(平台换代过渡谷值)、2024 年 6,362 条、2025 年 7,325 条;公报工作日出版,周六日与假日无刊。聚合收录与公报网站检索做过窗口对账:2026-10-05 至 10-09 两个渠道都是 160 条,逐日计数(28/23/43/41/25)完全一致。

正文以纯文本(`fulltext` 字段)随记录下发;公报网站上对应通知的 PDF 排版件不在本源范围(robots 协议禁止,且纯文本已含正文全部内容)。

## 2. 访问准备

- **无需密钥**:DigitalNZ 的检索接口匿名可用。接口地址 `https://api.digitalnz.org/v3/records.json`。
- 无需会话、无需浏览器;反爬方面该接口无已知拦截。匿名访问的速率上限未公开——全量回填(约 4.3 万次请求)在每请求间隔 1.5–4 秒下未遇任何限速,建议保持此节奏。
- 若日后需要更高配额,可在 digitalnz.org 免费注册 API 密钥,在 `.env` 中配一行 `DIGITALNZ_API_KEY=…`(当前代码未使用密钥,注册与否不影响运行)。

## 3. 抓什么:任务类型清单

| 任务类型 | 请求 | 产出 |
|---|---|---|
| `gazette_day` | GET `records.json`:当日过滤 + `per_page=100` + 集合 facet(`facets=collection&facets_per_page=50`) | ≤100 条:该日每条通知一个文档记录 + 一个 JSON 文件,当日收口;>100 条:从 facet 桶读出当日各类型计数,派生类型切片任务;0 条(周末/假日)记合法空日 |
| `gazette_slice` | GET `records.json`:当日过滤 + `and[collection]=类型名` + 按页翻页 | 一个类型切片的完整子集(单页天然完整;超过 100 条的切片实测翻页稳定,短页收口),并核对切片计数与 facet 计数一致 |

为什么大日要切片:聚合接口对**未过滤的按日查询**翻页不可靠(2026-10-12 实测:一个 350 条的日子翻 4 页带回 77 条跨页重复,间隔几分钟再翻同样的页看到的是不同子集,`sort` 参数被无视),而**带类型过滤的切片查询翻页稳定**(最大的切片 121 条,100+21 两页零重复)。facet 桶之和精确等于当日总数(两种日数实测),因此"每类型一切片"能精确还原全天。少数日子(2019 年平台换代过渡期)的记录没有任何类型归属——这类日子若 ≤100 条仍走单请求直取(单响应即全天),超过 100 条的至今未出现过(如出现会响亮报错待处理)。

## 4. 数据落到哪

- 零领域表:公报是"一次刊登 = 一条数据"的公报型源,`documents` 表就是全部台账。
- 每条通知的文档记录:
  - `doc_id` = `NZL_{发布日YYYYMMDD}_{source_url哈希前8位}`,其中 source_url 取通知在公报网站的规范地址 `https://gazette.govt.nz/notice/id/{通知号}`(如 `2026-sl5906`),不含任何会话参数;
  - `publication_date` = 通知发布日(记录的 `date` 字段,UTC 零点的 ISO 串取日期部分;个别记录该字段为空时以检索分区日为准并在 meta 里保留标记);
  - `doc_type`:通知编号中段(如 `2026-sl5906` 的 `sl`)——`sl`(次级立法)映射为 `SECONDARY_LEGISLATION`,其余类型一律 `OTHER`(2012 年立法法时代的授权立法编号无类型段,如 `2019-197`);原生类型编号与类型名都保留在 meta;
  - `issuing_authority` = 记录的 `publisher`(公报办公室全称);
  - `meta`:通知号(`notice_number`)、DigitalNZ 记录号(`digitalnz_id`)、类型编号与类型名、全文长度(`fulltext_chars`)、标签(`subject`)、替换/被替换关系(`replaces`/`is_replaced_by`,源标注 Unknown 时不存)。
- 文件:`01_raw/gazette/{年}/{月}/{通知号}.json`——该通知在 DigitalNZ 的完整记录逐字段无损保存(UTF-8、键排序、确定性序列化)。`fulltext` 字段即通知全文。

## 5. 完整案例走查

以 2026-10-09 公报通知 **2026-sl5906**《Planning Act (Approval of Standard Application Form for Designating Authorities No 1) Notice 2026》为例(2026-10-12 入账,各数可在 state.db 复查):

- 检索日窗口 `2026-10-09` 返回 25 条,本条在其中;DigitalNZ 记录号 65066081;
- 文档行:`doc_id` = `NZL_20261009_be38c092`(哈希段取自 source_url `https://gazette.govt.nz/notice/id/2026-sl5906`),`publication_date` = 2026-10-09,`doc_type` = `SECONDARY_LEGISLATION`(编号段 `sl`),`issuing_authority` = "New Zealand Gazette Office, Government Information Services, Department of Internal Affairs";
- 文件:`01_raw/gazette/2026/10/2026-sl5906.json`,4,061 字节,内含该记录全部字段与 1,191 字符全文(Planning Act 2026 授权批准标准申请表的部长通知,含"1. Title and Commencement""2. Approval of Standard Form"两节与签署行);入账任务 `gazette_day_b28d7a558e51`;
- 全库:2000-01-01 至 2026-10-11 共 207,289 份,磁盘文件数、台账行数与聚合接口逐年计数三方相等,抽查文件哈希 25/25 一致(2026-10-14 全量对账)。

## 6. 怎么跑

```bash
# 全量回填(已完成;历史窗口重跑会自动跳过已入账日子):
python cli.py collect --country nzl --source gazette window=2000-01-01:2026-10-11 --delay 1:2

# 每日增量(建议每天一次;终点自动留两天收录缓冲,已收录日子自动跳过):
python cli.py collect --country nzl --source gazette sync=1 --delay 1:2

# 只列计划不抓取:
python cli.py collect --country nzl --source gazette window=2026-10-05:2026-10-09 --dry-run

# 状态查询与快照导出:
python cli.py status --country nzl --source gazette
python cli.py export --country nzl
```

## 7. 更新与增量

- 游标键 `gazette_last_date`(kv 表):已确认完整消费到的最后一天(当前 2026-10-11)。窗口内每天的任务跑完(含合法空日)即推进;大日的类型切片在日任务派生时登记,切片健康由任务账与逐年计数审计保障,不影响游标。
- `sync=1`:从游标次日到 **UTC 前天**。留两天缓冲是因为 DigitalNZ 的收录延迟未公布——过早收口会把"还没收录"误判成"无刊",游标越过后该日通知就永久漏了。
- 重开机制:任务完成后不会自动重访。若怀疑某段窗口收录不全,用 `window=… signal=1` 重扫(同类任务带更新的 signal 会重开重抓,文件与台账按 doc_id 幂等覆盖);`repair_days=日期1,日期2` 可对指定天按完整类型词表补切片(新名字的切片自动入账)。
- 每年审计建议:对任意年份比较"账本计数 vs 聚合接口按年计数",两者全等即该年完整——全量回填的 27 个年份已全部通过(2026-10-14)。

## 8. 已知边界与缺口

- **2000 年以前无机器通道**:集合 1999 年计数为 0(实测);1841–1999 年的公报在国家图书馆与档案馆有纸本/扫描件,暂不在范围。
- **少量无结构化日期的记录**:集合中存在个别 `date` 字段为空的记录(约 7 条,集合总数与逐年计数之和的差额),按日检索不会命中它们;量级可忽略。
- **2019 年平台换代过渡期**:部分日子的记录无类型归属(facet 为空),这类日子只能单请求直取(≤100 条,至今全部如此);个别记录使用无类型段编号(如 `2019-197`,2012 年立法法时代的授权立法)。
- **同日翻页限制**:未过滤的按日查询翻页不可靠(服务端行为),本源以 facet 切片绕开;带类型过滤的切片翻页稳定。
- **全文以 DigitalNZ 抽取的纯文本为准**:公报 PDF 排版件不抓取(robots 协议禁止);极早期通知若聚合时未提取全文,记录仍入账但 `fulltext` 为空(meta 记 `fulltext_chars=0`)。
- 毛利语通知:Māori 语言文书与英语文书在同一集合混排,语言字段源端多为空,本源不做语言判定。

## 9. 端点速查表

在用端点:

| 端点 | 用途 |
|---|---|
| `GET /v3/records.json?and[primary_collection]=New Zealand Gazette&and[date]=YYYY-MM-DD&per_page=100&facets=collection&facets_per_page=50` | 按日枚举(≤100 直取;>100 读 facet 派切片) |
| `GET /v3/records.json?…&and[collection]=类型名&page=N` | 一个类型切片(翻页稳定,短页收口) |

源里还有、暂未使用的:

| 资源 | 一句话研究价值 |
|---|---|
| `GET /v3/records/{id}.json` | 单记录全字段详情,排查单条时有用 |
| DigitalNZ 全库检索(不加集合过滤) | 公报之外的政府藏品(历史公报 1860s、部门出版物)——扩源时再探 |
| 公报网站 `/issues` 存档(2000–2017 整期 PDF) | 整期版面研究价值;robots 禁抓,需官方另行授权通道 |
| 议会法律顾问办公室法规 API(`api.legislation.govt.nz`) | 见总览 `legislation` 源(在建) |

---

*更新日期:2026-10-14;数据快照:2026-10-14;数据由 window=2000-01-01:2026-10-11 全量回填背书(207,289 份,逐年对账全等)。*
