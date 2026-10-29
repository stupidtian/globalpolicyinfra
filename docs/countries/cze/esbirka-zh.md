# 捷克(CZE)数据源说明——esbirka(e-Sbírka《法规汇编》Sbírka zákonů)

> 数据快照日期:2026-10-15。文中条目计数、字节数与字段值均为当日对源站与账本的实测真实值(样本已存档,可重放复核)。

## 1. 源概览

### 1.1 制度背景:Sbírka zákonů 是什么、装了谁的产出

**Sbírka zákonů**(《法规汇编》,捷克官方公布媒介,引用缩写 **Sb.**)是捷克共和国的法定官方公报:规范文件只有在此公布才对第三人具有效力。**e-Sbírka**(e-sbirka.gov.cz)是汇编的电子系统,由**内政部**(Ministerstvo vnitra)依 **222/2016 Sb. 《汇编与国际条约法》** 建设运营——该法 § 1(3) 明文"出版方为内政部",§ 1(2) 规定汇编以电子形态保存,§ 6 规定电子系统为公共管理信息系统、对公众免费开放;2024-01-01 起电子形态成为唯一官方形态(纸质终止)。

收录内容(§ 2):宪法性法律(ústavní zákon)、法律(zákon)、参议院法定措施、政府条例(nařízení vlády)、部委规章(vyhláška);实际刊出的还有**宪法法院判决**(Nález Ústavního soudu)、各部通知通告(Sdělení/Oznámení)、公报更正等——2026 年头四件里三件是宪法法院判决,它们与法律共用同一连续编号(如 `2/2026 Sb.`),**一并收录**(过滤会破坏时间序列;类型字段原生保留,研究端随时可筛)。

**语料范围**(2026-10-15 实测;2026-10-24 回填核验):`sb` 集合全库 1918–2026 共 31,183 条(捷克斯洛伐克时代法令在同一编号序列);**2000–2025 已全量入账(13,090/13,091,逐编号源级对账)**,逐件 XML 正文全年代可得(1918 起的原文包通道同样成立)。年度规模参考:1993 年 414、2010 年 442、2026 年至 10 月中 190 条(平均每月约 19 条)。

**编号规则**:每年 1 月 1 日起连续编号(`190/2026 Sb.` = 2026 年第 190 号);另有平行的通告序列 `n1/1960 Sb.` 形态(1960–2023 共 6,350 条,两种形态解析器都收);同一年的编号与日期一一对应(四个样本年实测零错位)。条文汇编按**分册**(částka)组织——一年若干册,每册收若干条,`1/2026 Sb.` 在 2026 年第 1 册。

**不在本源里的东西**:国际条约集(Sb. m. s.,另一编号序列,默认不收、参数可扩)、议会立法过程(e-Legislativa 模块)、Úřední list(1918–1948 时代第二公报)、商业镜像站(zakonyprolidi.cz 等)。

### 1.2 关键口径:抓"公布原文",不跟随现行整合版

门户对每部法规同时提供**公布原文**(首次公布的文本,永不变)与**时点整合版**(časové znění,随修订持续更新)。两者的机器地址以版本段区分:`/sb/{年}/{号}/0000-00-00` 是公布原文的**稳定哨兵地址**(`0000-00-00`),日期段(如 `2016-08-29`)是时点整合版,`3000-01-06` 是现行整合的哨兵。本源一律抓公布原文——地址永久稳定、重抓幂等;整合版与版本谱系留给未来扩展(见 § 8)。

**文件本体 = 信息化文本包内的 XML**(2026-10-15 口径修订:不抓 PDF)。门户对每部法规提供"信息化文本"(informativní znění)下载包:一个 ZIP,内含**同一正文的四种格式(PDF + XML + JSON + DOCX)**——XML 是完整片段树(片段号/层级/类型/xhtml 正文,有序),与法定 PDF 排版自同一文本源。用公布原文别名地址上的下载 id 取包,得到的是**无日期后缀的原文包**——**对全部年代版本忠实**(2026-10-15 下载级实测 1918/1963/2006/2016/2026 各代样本;2016/222 的包内 XML 不含修法后才有的 § 22a,即 2016 年公布原文);带日期后缀的包属于具体日期版本(当前态指针取到,本源不取,工单名带日期即响亮报错)。**覆盖结论:逐件正文通道覆盖 1918 年起的整个语料,任何年代都不需要 PDF。**

### 1.3 数据通道:门户开放接口(免 key、无会话、无浏览器)

门户是单页应用,但其背后的 REST 接口全部开放(2026-10-15 探明,共 291 个端点,本源用 8 个):枚举走 POST 的**按月编年登记册**(一请求返回一整年),条目详情走 GET,文件下载走**两步异步**(先取工单、再取字节)。另有每日全量开放数据转储(opendata.eselpoint.gov.cz,46 个数据集)与 ELI 链接数据端点——本源未用(见 § 9 附录二)。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**,`.env` 无需任何条目 |
| 会话 | 无(无 cookie、无 token,全部请求无状态直连) |
| 请求头 | 无特殊要求 |
| 限额 | 无公开限额。累计型拦截实证:连发触发 403 WAF 页(约 60 秒自愈)、高峰偶发"服务暂时不可用"维护页(HTTP 200 + HTML,源站自述暂时性)——两类均已按暂态处理(状态码 + 内容签名守卫),大批量建议 `--delay 1:2` 起步;2026-10-24 全量回填 6.5 万任务零永久失败实证 |
| 反爬 | 未发现针对出口的选择性拒答(与某些斯洛伐克站点不同);robots.txt 无限制声明 |
| 响应格式 | 全部 JSON(UTF-8);文件为 PDF |
| 年代边界 | 1918–1992 捷克斯洛伐克时代出界,命令行显式拦截报错 |

## 3. 抓什么:任务类型清单

每种任务 = 一次下载 + 一次解析。共 **6 种**:

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `cze_list`(种子,每年一件) | POST 按月编年登记册,体 `{"rok": 年份}` | 窗口内每条 `sb` 条目生成一个 `cze_info`;窗口未完则链下一年;**末年走完推进游标** `esbirka_last_date` |
| `cze_info` | GET 条目的补充信息端点(版本化哨兵地址) | 类型三件套(法律/规章/判决等机器码)+ 批准日,并入参数生成 `cze_doc` |
| `cze_doc` | GET 条目详情根(版本化哨兵地址) | **一个完整文档记录入账**:公布时间戳、生效窗、分册号、ELI 等(与登记册逐字段交叉校验,不符即升级);生成 `cze_odkazy` |
| `cze_odkazy` | GET 条目的下载指针端点 | 取信息化包的下载 id 生成 `cze_fetch`(全年代同一通道;扫描/法定文本块照常出现在响应里但不消费) |
| `cze_fetch` | GET 信息化包的下载工单(`/ZIP`) | 工单 JSON(文件 id + 包名 + 就绪状态);未就绪(`PROBIHA`,首次生成时常见)按暂态重试;**包名带日期 = 别名解析漂移,响亮报错**;就绪生成 `cze_file` |
| `cze_file` | GET 文件服务取回 ZIP | 解包取唯一的 `_IZ.xml` 成员,**XML 正文落盘**挂为该文档的主文件 |

任务链:`cze_list × 逐年 → cze_info × 每条 → cze_doc × 每条 → cze_odkazy → cze_fetch → cze_file`。info 先于 doc 是刻意的:账本文档行首写定终身,必须由单一任务带全字段产出;文件任务殿后,把 PDF 挂到已入账的文档行上。

命令行参数(key=value 形式):

```
window=FROM:TO    闭区间公布日窗口,如 2026-01-01:2026-01-31(必填,或改用 sync=1)
sync=1            增量:起点 = 游标 esbirka_last_date 次日,终点 = 昨天
max_docs=200      单次运行入账文档数上限(默认无;截断时链停、游标不推)
collections=sb    收录集合(默认 sb;逗号分隔可扩 sm=条约集等,放宽 = 新任务身份,零清库)
```

## 4. 数据落到哪

**零领域表**(扁平文档型路径,同德国 BGBl / 法国 JORF / 西班牙 BOE / 斯洛伐克 Slov-Lex):公报条目刊出即定、条目即文档本体,语料里没有跨文档的持久实体;修订/废止引用与版本谱系是字段不是实体。一切研究字段进 `documents` 一张表:

| 列 | 内容 |
|---|---|
| `doc_id` | `CZE_{公布日YYYYMMDD}_{hash8(source_url)}` |
| `title` | 完整题名(如 `Vyhláška, kterou se mění vyhláška č. 355/2020 Sb., …`) |
| `publication_date` | 公布日(来自详情端点的原生时间戳日期部分)——研究时间轴的主日期 |
| `issuing_authority` | 空(逐件接口无签发机构字段;权威值在门户每日开放数据转储中,未来可补,见 § 8) |
| `source_url` | `https://e-sbirka.gov.cz/sb/{年}/{号}/0000-00-00`——公布原文的稳定哨兵地址,可重建、永不漂移 |
| `raw_format` / `language` | `xml` / `ces`(捷克语;全年代逐件正文) |
| `doc_type` | 由类型机器码映射的受控类型(下表);捷克原码永存 meta |
| `entity_ref` | NULL(扁平国家) |
| `meta` | 见下 |

**meta 字段**(原生字段无损收,全字符串):`kod_dokumentu`(编号)、`rok`、`sbirka_kod`、`typ_zneni`(恒为 VYHLASENE=公布原文)、**`datum_cas_vyhlaseni`(公布时间戳,纸质时代=当日零点、电子时代精确到毫秒)**、**`datum_schvaleni`(批准日)**、**`datum_ucinnosti_od` / `datum_ucinnosti_do`(生效起/止,后者有条件出现)**、`datum_ucinnosti_zneni_od`、`typ_aktu` / `podtyp_aktu` / `druh_aktu`(类型三件套原码)、`cislo_castky` / `rok_castky`(所在分册)、`eli`(欧洲法规标识)、`stav`(登记册状态快照,如 AKTUALNE_PLATNY=现行有效 / ZRUSENY=已废止 / VYHLASENY_BEZ_UCINNOSTI=已公布未生效)、`dokument_base_id`、`uzemne_zavazne_cr`(全境拘束)、`nikdy_nebyl_ucinny`。下载通道与源站文件名(如 `Sb_2026_1_Bez_UZ_PZZ.pdf`)记在任务参数账里(tasks 表 params 列),可追溯。

**doc_type 映射**(原生优先:机器码与捷克原词永存 meta,映射只是受控别名;未见过的类型一律 OTHER):

| 类型机器码 | 捷克原词 | doc_type |
|---|---|---|
| ZAKON / ZAKONUST / OPATRSEN | zákon(法律)/ ústavní zákon(宪法性法律)/ zákonné opatření Senátu(参议院法定措施) | STATUTE |
| NARIZENI | nařízení vlády(政府条例) | REGULATION |
| VYHLASKA | vyhláška(部委规章) | DECREE |
| OPATRENI | opatření(措施) | SECONDARY_LEGISLATION |
| OZNAMENI / SDELENI / SDELENIUS / OZNREDAK | 通知/通告/公报更正 | ADMINISTRATIVE_NOTICE |
| NALEZ(宪法法院判决)及其余 28 词表中的类型 | — | OTHER |

文件落点("一项政策一个文件夹",集合码与年份分片):

```
{data_root}/CZE_policy/
├── state.db
├── failures/
└── 01_raw/esbirka/sb/2026/001/            ← 集合 sb → 年份 → 号(三位零填充;通告序列 n 前缀原样)
    └── sb_2026_001_vyhlasene.xml          ← 公布原文 XML 正文(信息化包提取,文档主文件)
```

## 5. 完整案例走查(2026-01 窗口一部真实规章,账本实值)

1. **枚举**:POST 登记册 `{"rok": 2026}` → 一月的 `sb` 条目里有 `staleUrl=/sb/2026/1`、`kodDokumentuSbirky=1/2026 Sb.`、`datum=2026-01-08` → 生成一个 `cze_info`。
2. **补充信息**:GET → `podtypAktuKod=VYHLASKA`(部委规章)、`typAktuKod=PRAVPRED`、`datumSchvaleni=2025-12-29`(批准日)。
3. **详情**:GET 哨兵地址 `/sb/2026/1/0000-00-00` → `datumCasVyhlaseni=2026-01-08T13:09:27.614+01:00`(公布精确到毫秒)、生效 `datumUcinnostiOd=2026-01-11`、分册 2026 年第 1 册、ELI `/eli/cz/sb/2026/1/0000-00-00`;与登记册逐字段核对一致 → 文档入账。
4. **下载**:指针端点 → 信息化包 id=4484 → 工单 OK(`Sb_2026_1_IZ.zip`,无日期后缀 = 公布原文包)→ 解包取 XML → 52,960 字节落盘挂账。
5. **账本行**:`doc_id=CZE_20260108_1779d78e`、title=完整题名、publication_date=2026-01-08、doc_type=DECREE、local_path=`01_raw/esbirka/sb/2026/001/sb_2026_001_vyhlasene.pdf`;该文档全链 5 个任务(list 为年共享)全部 done。
6. **窗口合计(2026-01-01..01-31,2026-10-15 真实运行 + 同日换装,账本实值)**:13 文档全链 done;**13 份 XML 正文,三方对账(登记册 ≡ 账本 ≡ 磁盘)逐一相同、哈希全验一致**;类型分布 DECREE 7 / OTHER 5(含 3 件宪法法院判决)/ ADMINISTRATIVE_NOTICE 1;同窗口重跑零请求(任务确定性跳过)。换装期 3 个工单 `PROBIHA`(服务器首次生成包)按暂态重试自愈,零升级零永久失败。另跑 2016-07-20 单日窗口抽验纸质时代:2 文档同样取得 **XML 原文包**(如 222/2016 Sb. = 81,806 字节,包内不含修法后才有的 § 22a,即 2016 年公布原文)——纸质年代逐件正文通道实证,账本 15 份全部为 XML、磁盘零 PDF。

## 6. 怎么跑

```bash
# 演练(不入队执行,看会抓什么)
python cli.py collect --country cze --source esbirka window=2026-01-01:2026-01-31 --dry-run

# 小窗口真实抓取(§5 的窗口)
python cli.py collect --country cze --source esbirka window=2026-01-01:2026-01-31

# 每日增量(从上次游标的次日追到昨天)
python cli.py collect --country cze --source esbirka sync=1

# 限定单次规模 / 扩集合(如加国际条约集)
python cli.py collect --country cze --source esbirka window=2026-03-01:2026-03-31 max_docs=50
python cli.py collect --country cze --source esbirka window=2026-01-01:2026-12-31 collections=sb,sm

# 状态 / 快照 / 修复
python cli.py status --country cze --source esbirka
python cli.py export --country cze
python cli.py requeue --country cze
```

## 7. 更新与增量

- **游标**:`esbirka_last_date`。年份链**走完窗口末年**(窗口内条目全部派发)才把游标推到窗口终点;中途截断(max_docs)或崩溃不推,下次自愈。
- **sync 终点取昨天**:当日条目随公布节奏陆续入库,当天可能未出全。
- **公布原文不变、不设重开**:同窗口重复运行安全(任务确定性身份,已抓直接跳过、零请求)。登记册状态(`stav`)是采集时点快照;研究需要现行效力时按 meta 字段读,或将来以参数化重开刷新。
- **补漏保险**:某条公布极晚(当日未入登记册、次日才出现)时,下一次 sync 的年份登记册自然包含它(增量按登记册重走,新条目即新任务)。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **签发机构字段空** | 逐件接口不提供;权威值(766 个机构词表 + 逐条映射)在每日开放数据转储的元数据集中,未来经转储源补齐零成本 |
| **版本序列不收** | 时点整合版与版本谱系为门户原生数据(版本列表端点、编纂链接数据集),本源只收公布原文;需要时按 versions 参数或转储源另立 |
| **PDF 一律不抓** | 法定文本/验证文本/信息化包内的 PDF 均按口径排除(2026-10-15 用户裁决);XML 与法定 PDF 出自同一段片正文,文本无损失;纸质年代的机器可读原文同样走信息化包(实测 1918 年起),无需扫描与 OCR |
| **34 件源站包生成失败** | 工单持续 PROBIHA 两日(状态端点自证),典型为大附件技术法规;needs_agent 在账可见,补齐备选 = 片段级逐条取文或源站修复后重开 |
| **573/2025 Sb. 整链缺失** | 其补充信息端点持续 HTTP 500(源站缺陷,手动复核)——2000–2025 序列唯一缺口;补齐需裁决放宽 info 前置(部分元数据入账先例) |
| **扫描按分册共享** | 纸质时代同册多条法令各挂一份相同扫描字节(文件名含分册号);接受重复,回填如需去重另行设计 |
| **条约集默认不收** | Sb. m. s. 编号序列经 `collections=` 参数可扩 |
| **1918–1992 出界** | 捷克斯洛伐克时代数据在源站存在,本源命令行拦截;跨越需另行决策 |
| **议会过程记缺** | 门户 e-Legislativa 模块未开源自 |
| **ELI 长链接** | 欧洲法规标识进 meta(如 `/eli/cz/sb/2026/1/0000-00-00`),可作永久引用 |

## 9. 端点速查表

**在用**(基地 `https://e-sbirka.gov.cz/sbr-externi`,staleUrl 须整体百分号编码,斜杠也编码):

| 用途 | 端点 |
|---|---|
| 枚举(每年一件) | `POST /chronologicke-rejstriky/dokumenty-sbirky-po-mesicich`,体 `{"rok": YYYY}` |
| 条目详情(文档本体) | `GET /dokumenty-sbirky/{enc}?…` 哨兵地址 `/sb/{年}/{号}/0000-00-00` |
| 补充信息(类型/批准日) | `GET /dokumenty-sbirky/{enc}/dalsi-informace` |
| 下载指针(选通道) | `GET /dokumenty-sbirky/{enc}/odkazy-ke-stazeni` |
| 工单(信息化包,在用) | `GET /stahni/informativni-zneni/{dokumentId}/ZIP`(包内 PDF+XML+JSON+DOCX 四格式同文) |
| 文件字节 | `GET https://e-sbirka.gov.cz/souborove-sluzby/soubory/{工单id}` |

**已确认存在、本源有意不用**(2026-10-15 口径:不抓 PDF;各通道一句话定位):

| 通道 | 价值 |
|---|---|
| 每日全量转储(opendata.eselpoint.gov.cz/datove-sady-esbirka/,46 数据集) | 登记册/元数据/版本/片段正文/编纂链接/引用一次下载全得——**全量回填的低成本通道**(约 1.9 GB;片段正文含 1918 年起全文) |
| ELI 链接数据(`opendata.eselpoint.gov.cz/esel-esb/{eli}`,Accept: application/ld+json) | 按欧洲法规标识逐条取版本指针与片段,链接数据研究友好 |
| SPARQL 端点(opendata.eselpoint.gov.cz/sparql) | 语义查询全套汇编数据;实测轻查询可用、按 ELI 前缀过滤的真实形状查询被拒(403)——不作为采集通道 |
| 版本历史端点(`/dokumenty-sbirky/{enc}/historie`) | 一部法规的全部版本时间线(各版生效窗与修订法)——版本序列源的钥匙 |
| 按月分册登记册(`POST /chronologicke-rejstriky/castky-po-mesicich`) | 按册(částka)枚举——纸质时代按册取扫描的天然入口 |

---

*更新日期:2026-10-24;数据快照:2026-10-24;数据由 window=2000-01-01:2026-01-31 全量回填背书(13,103 文档 / 13,069 份 XML 正文 1.51 GB;源级对账 2000–2025 缺 1 件 = 源站端点 500;34 件正文缺 = 源站 ZIP 生成失败,均 needs_agent 在账可见;哈希抽验与幂等零请求全过)。*
