# 秘鲁（PER）数据源说明——elperuano（Diario Oficial El Peruano 法规增刊）

> 文中数量为真实运行的实测参考值；你运行时的产出取决于所选窗口。
> 阅读前提：了解仓库根目录 `python cli.py` 的用法即可，不需要读代码。

## 1. 源概览

### 1.1 制度背景：Diario Oficial El Peruano 与 Normas Legales

**El Peruano**（[elperuano.pe](https://elperuano.pe)）是秘鲁的官方公报，1825 年 10 月 22 日由解放者西蒙·玻利瓦尔（Simón Bolívar）创刊，由国有企业 Editora Perú 出版。法规性内容（法律、立法法令、最高法令、紧急法令、各级行政决议、条例等）刊于每日随报发行的 **Normas Legales（法规增刊，separata）**——增刊自 1983 年开刊（2000-01-01 期报头标"AÑO XVIII - Nº 7131"，反推第一年为 1983 年），重大法规另有 **Edición Extraordinaria（特别增刊）** 单行发布。同一报系下还有 Boletín Oficial、Procesos Constitucionales、Casaciones、Índice Quincenal 等其他增刊（不在本源范围，见总览第 3 节）。

三个关键覆盖性质（2026-10-31 实测）：

- **数字档案自 1997 年 7 月起**：按日法规列表对 1996 年及更早日期返回空；1997 年内覆盖残缺（部分日期无数据）且含纯扫描件；**1998 年 1 月起为数字原生文本**（抽样 1998/1999/2000/2001 年各期 PDF 文本层完好）；
- **日均约 38 条**：抽样 9 个日期（1998–2026）每天 16–83 条不等；
- **2023 年 9 月为载体换代点**：之前的法规只有"整刊 PDF"（一天的法规合订一份）；之后每条法规有独立明细页（内嵌全文 HTML + 独立 PDF）。

全库量级估计：**约 35–40 万条法规**（按日均 38 条 × 约 10,650 个出版日推算）。

### 1.2 技术形态：免 key 三主机直连

| 主机 | 角色 |
|---|---|
| `diariooficial.elperuano.pe` | 旧门户（ASP.NET）：按日法规列表（POST 表单查询），新旧年代通吃 |
| `busquedas.elperuano.pe` | 新门户（2023-09 上线）：每条法规的明细页、每日站点地图 |
| `epdoc2.elperuano.pe` | 文件投递：整刊 PDF 与单条特别增刊 PDF 直链 |

全部免 API key、免会话（cookie）、免浏览器；本仓库 HTTP 层默认浏览器标识直连即通（2026-10-31 实测）。

### 1.3 双载体时代（读懂数据的关键）

按日列表里每条法规的链接形态自 2023-09 起换代，本包**逐条按链接形态判定**（不按日期猜测）：

- **旧年代（约 1997-07 ~ 2023-08）**：条目链接指向**当日整刊 PDF**（同日全部条目同一份文件）；每条的身份号（如 `128536-600`）藏在条目内被注释的按钮标记里。旧年代按条 PDF 端点（`obtenerDocumentoLegal`）返回带畸形加密的 PDF，主流 PDF 库均打不开——弃用，文件通道 = 整刊 PDF。
- **新年代（2023-09 起）**：绝大多数条目链接指向新门户**按条明细页**（内嵌全文）；个别特别增刊条目链接为 `epdoc2…/VistaNLSE.asp` 直出的**单条特别增刊 PDF**（实测样本 16 页，"SEPARATA ESPECIAL"报头）。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 零条目 |
| 会话 | **不需要**——全部端点裸 HTTP 直连（含 POST 查询，无 cookie/令牌依赖） |
| 限额 | 未观察到（探查期约 60 次请求无拦截）；保持默认礼貌间隔 |
| 响应格式 | 列表/明细 = UTF-8 HTML；文件 = PDF |
| 注意 | 按日列表是 **POST 表单**（`cddesde`/`cdhasta`，dd/MM/yyyy 日粒度），不是 GET；日期超过覆盖起点（1996-）返回 HTTP 200 的空模板——属正常"当日无刊"，不是错误 |

## 3. 抓什么：任务类型清单（3+1 种）

**一天的完整收编路径**：按日列表发现 → 旧年代整刊 PDF 落盘（当日全部法规共享）/ 新年代逐条明细页落盘 → 清理通道出统一 XML（新年代）。

```
per_day_list(日期) ──旧年代条目──> documents 登记 + per_day_edition(整刊直链, [身份号…])
    │                                        └─ 一份 PDF，当日每条法规的 documents 行共享挂靠
    └──新年代条目──> per_norm_detail(明细页路径, 日期, 机构)
                             └─ 明细页 HTML（或特别增刊 PDF）落盘 + documents 登记
（per_clean：对明细页/特别增刊产物做统一 XML 清理；整刊 PDF 不清理，见第 8 节）
```

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `per_day_list`（种子） | 按日列表 POST，某一天 | 当日全部条目：旧年代逐条登记 documents（标题/机构/日期/摘要/身份号），并派 1 个整刊任务；新年代派每条一个 `per_norm_detail`。当日无刊 = 完整消费，水位线照常推进 |
| `per_day_edition` | 整刊 PDF 直链（GET） | 一份 PDF 落盘；当日每条法规的 documents 行回填该文件路径与哈希（同字节重复挂靠，见第 4 节说明） |
| `per_norm_detail` | 明细页 HTML（GET）；特别增刊条目则直取 PDF | 文件落盘（HTML 或 PDF）+ documents 登记（标题取自页内，机构来自列表层传入） |
| `per_clean` | 本地读已落盘文件 | 明细页 HTML → 提取内嵌全文容器 → 统一 XML；特别增刊 PDF → 几何通道文本提取（扫描件响亮记缺） |

命令行参数（key=value）：

```
window=2000-01-01:2000-01-10   必填（或 sync=1）：闭区间日期窗，支持逗号分隔多段
                               （如 window=2000-01-01:2000-01-10,2026-10-26:2026-10-30）
sync=1                          从水位线（elperuano_last_date）次日跑到昨天
```

## 4. 数据落到哪

**零领域表（扁平公报型）+ documents 表 + 按源组织的一层目录**。法规在公报中一次刊登即定，语料内没有跨文档的持久实体，因此不建国家表——documents 表就是全部账目（同德国 BGBl、法国 JORF 的形态）。

| 位置 | 记什么 |
|---|---|
| `documents` 表 | 一行一条法规（一个出台事件）：标题、发布日期（= 增刊日期）、发布机构、类型受控值、`meta` 溢出列装原生字段 |
| `01_raw/elperuano/editions/{年}/{NL\|EX}{YYYYMMDD}.pdf` | 旧年代整刊 PDF（约 9,300 份的量级） |
| `01_raw/elperuano/dispositivo/{id 前 3 位}/{id}.html/.pdf` | 新年代按条明细页 HTML / 单条特别增刊 PDF |
| `02_cleaned/{doc_id 哈希 2 位}/{doc_id}.xml` | 清理产物（框架派生路径；仅新年代） |

documents 主要字段：

| 列 | 值 |
|---|---|
| `title` | sumilla（公报条目的一句话摘要题；缺则回退官方名称，如 `DECRETO SUPREMO 044-99-PCM`） |
| `publication_date` | 增刊日期（公报唯一的原生日期；制定日/生效日公报不载，记缺） |
| `issuing_authority` | 列表层按机构分节的节名（如 `MINISTERIO DE DEFENSA`） |
| `doc_type` | 按官方名称词首映射的受控值（见下）；原生名称整段存 `meta.designation` |
| `language` | `spa` |
| `meta` | `era`（edition=旧年代 / device=明细页 / separata=单条增刊）、`data_id`（身份号）、`designation`（官方名称）、`edicion`（NL/EX）、旧年代另存 `edition_code` + `edition_url`（整刊直链） |

**类型映射**（官方名称词首 → 受控值；原生名称永存 meta）：LEY / DECRETO LEGISLATIVO → `STATUTE`；DECRETO SUPREMO / DECRETO DE URGENCIA / 其余 DECRETO* → `DECREE`；RESOLUCION* / REGLAMENTO* / ORDENANZA* / DIRECTIVA / CIRCULAR → `SECONDARY_LEGISLATION`；其余 → `OTHER`。

**旧年代的共享文件**：一天一份整刊 PDF，当日每条法规的 documents 行都指向这份文件（`local_path` 相同、`file_hash` 相同）——这是"颁布原样快照"的诚实形态；同一文件的字节只落盘一份，多条账目共享挂靠。想知道某条法规在整刊第几页，需要版面切分（见第 8 节）。

## 5. 完整案例走查

以 2026-11-02 的双年代小窗实跑为例（`window=1998-01-02:1998-01-04,2026-10-26:2026-10-30`，合计 326 份文档、283 项任务），全程四步，每个数字可从 state.db 复查：

1. **旧年代列表**：`per_day_list` 抓 1998-01-02 → 该日 16 条，全部登记——其中一条为 `RESOLUCION MINISTERIAL 572-97-EM/VME`（能源矿业部），机构 `ENERGIA Y MINAS`，摘要题"Aprueban transferencia de titularidad de la servidumbre de electroducto…"；身份号 `77750-600`，派 1 个 `per_day_edition`。三天合计登记 56 条（16/26/14）；
2. **旧年代整刊**：`per_day_edition` 直链下载 `NL19980102.pdf`（15 页，134,149 字节，文本层完好）落 `01_raw/elperuano/editions/1998/`；当日 16 条 documents 行全部回填该路径与哈希（`doc_id=PER_19980102_88bdc6ca` 一行可复查 `local_path` 与 16 行共享）；
3. **新年代列表**：五天（10-26 至 10-30）共 271 条派 `per_norm_detail`（18/29/39/79/105，含 27 条特别增刊与 6 条单条增刊 PDF 形态）；
4. **新年代明细**：以某条特别增刊政令为例（`doc_id=PER_20261026_7f896b6b`，`DECRETOS DE URGENCIA` 节）——明细页 HTML 130,333 字节落盘，页内无 `h1.sumilla` 时标题自动回退到内嵌文档自身的 `<title>`（"Autorizan viaje del Ministro del Interior a El Salvador…"）；`per_clean` 产出统一 XML（11,645 字符）。全窗清理 268 件，平均 10,089 字符/件，最长 56,652 字符。

全程零静默丢数：仅有的 1 个永久失败（一条列表已载、新门户缺页的条目 `2544535-1`）与 1 个源端坏件 PDF（0 页可解析）均响亮记账；另有一条 400 页 81 MB 的特大型增刊（选举委员会决议汇编）清理耗时约 1 小时，已按计划时间延后重试。

## 6. 怎么跑

```bash
# 演练（不抓任何东西，看会入队什么）
python cli.py collect --country per --source elperuano window=2026-10-26:2026-10-30 --dry-run

# 双年代小窗（旧年代整刊 + 新年代按条，一次跑通两种载体）
python cli.py collect --country per --source elperuano window=1998-01-02:1998-01-04,2026-10-26:2026-10-30

# 增量同步（水位线次日 → 昨天）
python cli.py collect --country per --source elperuano sync=1

# 清理（只清新年代明细页/特别增刊产物；整刊 PDF 不在清理范围）
python cli.py clean --country per --source elperuano

# 状态 / 快照 / 修复
python cli.py status --country per --source elperuano
python cli.py export --country per
python cli.py requeue --country per
```

## 7. 更新与增量

- **重跑安全**：任务身份确定性去重——重复运行同一命令，已完成部分直接跳过，近零成本；
- **增量 = 日期水位线**：kv 键 `elperuano_last_date`，`sync=1` 从水位线次日跑到**昨天**（当日增刊可能尚未生成或晚出特别增刊，"尚未生成"与"当日无刊"同形，故 sync 永不领取今天）；
- **无刊日照常推进**：空产出是完整消费（假日/无增刊日），水位线照走并在账目留痕；
- **已收日期的重访**：日期窗参数化——对同日期带不同参数重跑会生成新任务自动重抓（例如将来放宽范围）；公报刊出即定，正常情况下无需重访。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| 整刊 PDF 不清理 | 旧年代一天一份合订 PDF，单条法规在整刊内的页码边界无逐条标记——按条正文切分需版面分析，属将来工作；原始 PDF 文本层完好（1998 起），研究者可自行提取 |
| 1997 年档案残缺 | 年内缺日、部分整刊为纯扫描件（0 文本字符，实测样本 88 页）；条目照收，扫描件如进清理会响亮记缺（OCR 界外） |
| 旧年代按条 PDF 不可用 | 旧门户按条端点返回带畸形加密的 PDF（三个主流 PDF 库均打不开）；如将来引入 qpdf/pikepdf 级工具可重新评估 |
| 生效日/制定日记缺 | 公报元数据只载公布日；SPIJ（司法部整合层）可能携带，但自本仓库网络不可达（2026-10-31 实测），接入后可补 |
| 特别增刊边角 | 新年代个别特别增刊条目走"单条 PDF"形态（SEPARATA ESPECIAL），已支持；旧年代特别增刊的整刊代码（EX 前缀）按列表内直链接收，未单独枚举验证 |
| 列表身份号藏在注释里 | 每条法规的身份号位于条目内被注释的按钮标记——站点改版（尤其"去注释"式重构）会响亮报错而不是静默丢数据 |
| 新门户供给滞后 | 列表已出、新门户明细页尚未生成的条目（试跑期实测 5/125，其中 4 条数分钟后自愈）：明细页 404 按故障响亮记账，重跑修复通道即可补齐；1 条（2569043-1 同款现象）已实证可自愈 |
| 附录件（TUPA 等）不抓取 | 2026-10-28 起条目可带"Descargar TUPA"类附录按钮——同一法规的姊妹 PDF（part 号递增），身份号记入 meta.annex_ids 不抓取；如需附录件按 part 号扩展即可 |
| 个别 PDF 源端坏件 | 实测一条特别增刊投递了页面树为空的 4.9 MB PDF（0 页可解析）——清理时按"源端不可读"响亮记账，原始字节保留备查；另见 400 页 81 MB 的特大型增刊（JNE 决议汇编），几何通道耗时数分钟属正常 |
| 新门户检索不作主通道 | 新门户全文检索（40,755 命中，2026-10-31 实测）只回溯到 2023-09，且单次结果上限 10,000——只作辅助核对，枚举一律走按日列表 |
| 商业化形态 | Editora Perú 门户带广告与订阅入口（suscripciones.elperuano.pe）；本次所依赖的通道全部免费可达，若深档出现付费墙按出界处理 |

## 9. 端点速查表

在用端点（全部免 key；2026-10-31 实测）：

| 用途 | 端点与参数 |
|---|---|
| 按日法规列表 | `POST https://diariooficial.elperuano.pe/Normas/Filtro`，表单 `btnBuscar=`、`cddesde`/`cdhasta`（dd/MM/yyyy 单日）、`X-Requested-With: XMLHttpRequest` → HTML 片段：每条一个 `<article>`（h4 机构 / h5 官方名称+链接 / p 日期（+特别增刊标记）/ p 摘要题；身份号在条目内注释的 `data-id`） |
| 按条明细页（新年代） | `GET https://busquedas.elperuano.pe/dispositivo/{NL\|EX}/{id}-{n}` → SSR HTML：`h1.sumilla`、`h2` 类型与号、内嵌完整 XHTML（`div#visor-html`，含全文 `p.cuerpo` 段落）+ PDF 直链 token |
| 单条特别增刊 PDF | `GET https://epdoc2.elperuano.pe/EpPo/VistaNLSE.asp?Referencias={base64("{id}-{n}{YYYYMMDD}")}` → 该条法规的独立 PDF（"SEPARATA ESPECIAL"） |
| 整刊 PDF 直链 | `GET https://epdoc2.elperuano.pe/EpPo/Descarga.asp?Referencias={base64("{NL\|EX}{YYYYMMDD}")}` → 当日整刊（列表响应内直接给出，无需自构） |
| 每日站点地图 | `GET https://busquedas.elperuano.pe/sitemap.xml` → `sitemap-normas_legales.xml`（当日明细 URL 清单，每日重生成，无历史归档） |
| 整刊查看器 | `https://busquedas.elperuano.pe/cuadernillo/{NL\|EX}/{YYYYMMDD}`（人读页；PDF 经 `/api/archivo/file/{token}/*/{code}{date}.pdf`，token 在页面 HTML 内） |

未在用的端点/信息（研究价值备注）：

| 端点 | 一句话价值 |
|---|---|
| `GET /_root.data?query=…&ci=all\|ONLY&tipoPublicacion=NL\|BO\|PC\|CA\|IN&fechaIni=…&fechaFin=…&start=…` | 新门户检索数据端点（turbo-stream 编码）——全文检索仅覆盖 2023-09 后、单次上限 10,000 条，可作对账旁证 |
| `GET /Normas/Verificador`、`/Normas/Indices`、`/Normas/normasactualizadas` | 旧门户的法规核验/索引/最新法规页——未探 |
| `https://spij.minjus.gob.pe` | 司法部 SPIJ 免费法规整合层——本网络不可达（TCP 超时），跨网络环境值得补验（生效日/整合文本/版本形态的候选来源） |

---

*更新日期：2026-11-02；数据快照：2026-11-02；数据由双年代小窗口真实试跑背书（1998-01-02..04 + 2026-10-26..30，326 份文档 / 283 项任务，证据见源文件第 5 节）。*
