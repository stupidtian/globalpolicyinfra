# 巴西（BRA）数据源说明——dou（联邦官方公报 DOU）

> 数据快照日期：2026-10-02。文中条目计数、字节数与状态码均为当日对源站直连实测的真实值（可重放复核）；账本内计数见 §5（首次真实运行实值）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。巴西全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：DOU 是什么、装了谁的产出

**DOU**（*Diário Oficial da União*，联邦官方公报）是巴西**联邦层级一切规范文件的法定公布媒介**——联邦法律、法令、部委令只有在此公布才产生效力。运营方是**国家印刷局**（Imprensa Nacional），现行治理依据是 **Decreto nº 9.215/2017**（2017 年 11 月 29 日法令）：第 2 条规定 DOU 的公布权属国家印刷局；**第 3 条规定 DOU 纯电子出版、公布于国家印刷局网站，且"公众获取 DOU 免费"（§1º）**；第 4 条要求数字版满足 ICP-Brasil 公钥基础设施的真实性要求。

公报每个工作日出版（周六常有刊、周日与法定节假日无刊），按**刊（seção）**分组：

| 刊 | 名称 | 内容 | 默认是否采集 |
|---|---|---|---|
| `do1` | Seção 1 | **联邦规范性文件**：Lei（法律）、Medida Provisória（临时措施令）、Decreto（法令）、Emenda Constitucional（宪法修正案）、Portaria（部委令）、Resolução（决议）、Instrução Normativa（规范性指令）、Despacho、Ato 等 | **是（默认，规范类+更正，见 §3）** |
| `do1e` | Seção 1 特刊（DO1_EXTRA_A..H 族） | Seção 1 的增刊/特刊——**整期正刊内容可能整个发成特刊**（如 2021-04-01 那期 Seção 1 正刊为零条、全部内容在特刊 DO1_EXTRA_F，含 Lei 14.133/2021） | **是（默认，规范类+更正，见 §3）** |
| `do2` / `do2e` | Seção 2 | 人事任免、招考公告 | 否（参数可扩） |
| `do3` / `do3e` | Seção 3 | 司法系统文书、其他公告 | 否（参数可扩） |

日常体量（2026-10-02 实测）：Seção 1 正刊 415 条、特刊族 9 条、Seção 2 为 646 条、Seção 3 为 2,334 条。研究"联邦政府每天出台了什么规范"，Seção 1（正刊+特刊）一张网收全。

**不在本源里的东西**：国会立法过程（提案/审议/投票——国会两院有各自的免钥开放接口，属过程数据结构，本源记缺）；现行整并文本（planalto.gov.br 的法规汇编站，另一套系统）；州/市级公报（各州自办，出界）。

### 1.2 与法律体系的关系

DOU 是**公布层**：法律由国会通过、总统签署后在此刊出全文（颁布原样快照）；法令、部委令由行政分支在此刊出。同一法规的"当前有效版"（整并文本）不在本源——本源只有 as-published 序列。法规间的修订/废止关系，DOU 条目不携带结构化引用字段（题名内的人读式引用如"altera a Lei nº …"随题名原样入账）。

### 1.3 数据通道：公报门户的按日阅读页 + 条目详情页（免 key、无会话依赖）

**① 按日/按刊枚举——阅读页内嵌 JSON**：

```
GET https://www.in.gov.br/leiturajornal?secao=do1&data=02-10-2026
```

- `secao` 取小写刊代号（do1 / do1e / do2 / do2e / do3 / do3e），`data` 格式 **DD-MM-YYYY**；
- 返回的 HTML 页内有一个 `id="params"` 的元素，其内容是一段 **JSON**（2026-10-02 实测该日 Seção 1 为 433,342 字符），结构：

```json
{
  "section": "DO1",
  "dateUrl": "02-10-2026",
  "typeNormDay": {"DO1": true, "DO1A": false, "DO1E": true, "DO2": true, "DO2E": true, "DO3": true, ...},
  "jsonArray": [
    {"pubName": "DO1",
     "urlTitle": "portaria-alf/vcp-n-134-de-30-de-setembro-de-2026-736019421",
     "numberPage": "48",
     "title": "PORTARIA ALF/VCP Nº 134, DE 30 DE SETEMBRO DE 2026",
     "content": "PORTARIA ALF/VCP Nº 134 ... Disciplina locais e condições ...",   ← 文摘（题名+正文开头）
     "editionNumber": "187",
     "artType": "Portaria",
     "pubDate": "02/10/2026",
     "hierarchyStr": "Ministério da Fazenda/Secretaria Especial da Receita Federal do Brasil/…/Alfândega …",
     "hierarchyLevelSize": "5", "pubOrder": "DO100028:…", "subTitulo": "", "titulo": ""}
  ]
}
```

- **`jsonArray` 一行即一条公布条目**，题名、文摘、发布机构层级路径、版次、页码、类型、刊日齐全；
- `urlTitle` 是条目详情页地址的尾段（可含斜杠），尾部连字符后的数字是该条目的稳定编号；
- **无刊日的形态干净可判**：HTTP 200、`jsonArray` 为空数组、`typeNormDay` 全部 false（2026-10-04 周日实测）——没有 404 语义；
- **年代覆盖**：2013-01-02 起有数据（2013-01 实测 31 条、2015-01 实测 84 条、2020-01 实测 210 条）；2012 年及更早一律返回空数组——老年代不在此通道（见 §8）。

**② 条目详情——一篇一页的公布原文**：

```
GET https://www.in.gov.br/web/dou/-/{urlTitle}
```

服务端渲染 HTML（UTF-8，典型 125–404 KB/条），全部内容在 `<article id="materia">` 容器内：

| 元素 | 内容 |
|---|---|
| `span.publicado-dou-data` | 刊日（DD/MM/YYYY，如 02/10/2026） |
| `span.edicao-dou-data` | 版次号（正刊为数字如 `187`；特刊带字母后缀如 `61-F`） |
| `span.secao-dou` / `span.secao-dou-data` | 刊号（"Seção: 1"）与页码 |
| `span.orgao-dou-data` | 发布机构完整层级路径（与枚举行的 hierarchyStr 同源） |
| `p.identifica` | 条目正式题名 |
| `p.ementa` | 语境摘要（法律类是"国民议会 decree…"前的权威摘要句） |
| `p.dou-paragraph` | **正文段落**（Portaria 实测 116 段；Lei 14.133/2021 实测 1,556 段） |
| `p.assina` / `p.cargo` | 签署人 / 职务 |
| 链接 `pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?data=…&jornal=…&pagina=…` | 该条所在公报版面页的取数参数（已入账，供未来取 PDF 版面件，见 §8） |

**③ 公报版面 PDF**（本源默认不取，参数已入账）：整页版面 PDF 走 `pesquisa.in.gov.br` 的查看器——先访问一次 visualiza 页面取得站点会话 cookie，再请求 `…/servlet/INPDFViewer?jornal=515&pagina=48&data=02/10/2026&captchafield=firstAccess`（口令参数值固定为 `firstAccess`，需带 Referer 与会话）返回 application/pdf（2026-10-02 实测 193,432 字节、%PDF-1.4）。条目页 HTML 已含全文，PDF 版面件仅在需要印刷版式时按 meta 中的参数补取。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 条目与枚举页无会话依赖（2026-10-02 连续数百请求实测）；仅版面 PDF 取件需要站点会话（§1.3 ③）——默认不取 PDF，故整源按无会话运行 |
| 代理 | **部分网络环境必需**：实测（2026-10-02）从中国大陆直连被连接层重置（多客户端、多指纹、明文/加密、三个独立源站 IP 段同型失败），经代理出口（美国节点实测）一切正常。采集运行前设标准环境变量：`HTTPS_PROXY=http://<代理> HTTP_PROXY=http://<代理>`（框架传输层原生支持，零代码） |
| 限额/反爬 | 无 key、无限额提示、无验证码（连续数百请求实测零拦截）；框架统一限速足够 |
| robots 声明 | 站点 robots.txt 声明全站 `Disallow: /`（2026-10-02 实测）。与之并存的事实：DOU 为法定免费公开出版物（Decreto 9.215/2017 §3º"公众获取免费"），门户设有官方开放数据专栏（XML/ZIP 打包文件）。本源以保守限速运行并将此并存事实留档 |
| 许可 | 公报内容为巴西联邦政府公文——巴西《著作权法》第 8 条官方文件不受版权保护；官方开放数据专栏明示 XML 格式开放获取 |

## 3. 抓什么：任务类型清单

每种任务 = 一次下载（或一次本地读取）+ 一次解析。采集 **2 种** + 清理 **1 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `dou_leitura`（种子，每 [日 × 刊] 一个） | GET 按日阅读页（§1.3 ①） | 解析 `#params` JSON → 按类型过滤（默认 = 规范类+更正预设，见 §3 参数表）→ 每个保留条目生成一个 `dou_artigo`；当日该刊无版（空数组 + typeNormDay 全 false）或全部条目被类型过滤掉 → 合法空产出；两种情况都推进该刊游标 `dou_last_<secao>`（账本里"该刊已完整消费到哪天"的进度标记，详见 §7） |
| `dou_artigo`（每条目一个） | GET 条目详情页（§1.3 ②） | 一个文档记录 + 详情页 HTML 原样字节 **gzip 压缩**落盘为 `doc.html.gz`（文档主文件；解压即源站原页，压缩为体积考虑——页面约六成是每页重复的门户导航，拉脱维亚源同款做法）；推进无 |
| `dou_clean`（每文档一个，本地读取，无网络） | 读已落盘的 `doc.html.gz`（自动解压） | 去门户装饰的纯文本（UTF-8，`\n` 行界）落 `02_cleaned/`：保留正文容器 `#materia`，丢弃四个装饰块（刊头社徽/刊名、`Publicado em…Órgão` 元数据行——账本已全有、"本内容不替代认证版"法定提示、页脚装饰图），正文与签署人保留；规则版本号入账，升版自动全库重清 |

任务链：`dou_leitura × 每日每刊 → dou_artigo × 每条目`。

命令行参数（key=value 形式）：

```
window=FROM:TO    闭区间日期窗口，如 2026-10-01:2026-10-02（必填，或改用 sync=1）
sync=1            增量：起点 = 该刊游标的次日，终点 = 昨天（当日公报上午生成，
                  提前抓会得到与"无刊日"相同的空形态，故增量从不认领今天）
secoes=do1,do1e   采集哪些刊（逗号分隔小写代号；默认 do1,do1e = Seção 1 正刊+特刊；
                  可扩 do2,do2e,do3,do3e；每刊各有独立游标）
tipos=normativo   类型范围（默认即此档 = 规范类+更正预设：Lei、
                  Medida Provisória、Emenda Constitucional、Decreto、
                  Portaria 族、Resolução、Instrução Normativa、
                  Ato Normativo、Retificação——约占 Seção 1 体量一半，
                  其余为程序性/司法性残余）；all = 全部照收；
                  或显式逗号列表（如 Lei,Decreto）。过滤在枚举层执行、
                  随任务参数走，将来放宽 = 新任务身份自动补抓、无需清库
```

## 4. 数据落到哪

**零领域表**（扁平文档型路径，同德国 BGBl / 西班牙 BOE / 法国 JORF）：公报条目刊出即定、条目即文档本体，语料里没有跨文档的持久实体；一切研究字段进 `documents` 一张表：

| 列 | 内容 |
|---|---|
| `doc_id` | `BRA_{刊日YYYYMMDD}_{hash8(source_url)}` |
| `title` | 条目正式题名（详情页 identifica；与枚举行 title 不一致时以详情页为准、枚举行原词入 meta） |
| `publication_date` | 刊日（publicado-dou-data）——研究时间轴的主日期 |
| `issuing_authority` | 发布机构完整层级路径（如 `Ministério da Fazenda/Secretaria Especial da Receita Federal do Brasil/…/Alfândega da Receita Federal do Brasil no Aeroporto Internacional de Viracopos`） |
| `source_url` | `https://www.in.gov.br/web/dou/-/{urlTitle}`——条目正门地址，无一次性参数、可重建 |
| `raw_format` / `language` | `gz`（gzip 载体的 html，框架按文件后缀记账）/ `por` |
| `doc_type` | 由 artType 映射的受控类型（下表）；葡语原词永存 meta |
| `entity_ref` | NULL（扁平国家） |
| `meta` | 见下 |

**meta 字段**（原生字段无损收，全字符串）：`url_title`、`pub_name`（DO1 / DO1_EXTRA_F 等实际刊名）、`edicao`（版次 187 / 61-F）、`art_type`（类型原词，如 Portaria）、`number_page`（公报页码）、`edition_number`、`hierarchy_str`（机构层级路径）、`hierarchy_level_size`、`pub_order`（源站排序键）、`sub_titulo`、`ementa`（语境摘要）、`assinou`（签署人）、`cargo`（职务）、`n_paragraphs`（正文段落数，质量雷达用）、`jornal` / `pagina` / `visualiza_data`（版面 PDF 取件参数）、`list_title`（枚举行题名，与详情页不一致时保留）、`pub_date_raw`（DD/MM/YYYY 原格式）。

**doc_type 映射**（原生优先：artType 原词永存 meta，映射只是一层受控别名；跨国可比的统一类型学不在采集层做）：

| artType（葡语原词族） | doc_type |
|---|---|
| Lei*（含 Lei Complementar/Delegada）、Medida Provisória、Emenda Constitucional | STATUTE |
| Decreto*（含 Decreto Legislativo 等） | DECREE |
| Portaria*（含 Conjunta/Interministerial）、Resolução、Instrução Normativa、Ato Normativo、Circular、Ordem de Serviço | ORDER |
| Retificação / Retificações（更正） | RETIFICATION |
| 其余（Despacho、Ato、Pauta、Ato Declaratório、Acórdão…） | OTHER |

类型词表是开放集（2026-10-02 单日 Seção 1 实测 19 种），映射表只加不改：新词落 OTHER 并在 meta 留原词。

文件落点（"一项政策一个文件夹"，年/日双层分片，刊名一层防同日多版互撞）：

```
{data_root}/BRA_policy/
├── state.db
├── failures/
├── 01_raw/dou/
│   └── 2026/D20261002/                     ← 年 = 刊日年；日 = 刊日
│       └── DO1/                            ← 实际刊名（正刊/特刊各归各夹）
│           └── 736019421/                  ← 条目稳定编号（urlTitle 尾段）
│               └── doc.html.gz             ← 详情页 HTML 原样字节的 gzip 压缩（文档主文件；gunzip 即源站原页）
└── 02_cleaned/
    └── 9a/                                 ← doc_id 哈希前两位分片
        └── BRA_20170206_c8bac0ea.txt       ← 去装饰纯文本（§3 dou_clean 产出）
```

## 5. 完整案例走查（2026-10-02 一日，源站与账本实值）

一个真实刊日的全链数据（每步可重放）：

1. **枚举**：`GET /leiturajornal?secao=do1&data=02-10-2026` → 200，584,053 字节，内嵌 JSON 中 `jsonArray` 共 **415 条**（该日特刊族 do1e 另有 9 条）；首条即上文示例 `PORTARIA ALF/VCP Nº 134, DE 30 DE SETEMBRO DE 2026`（卫生部系统海关，公报第 187 期第 48 页）。
2. **条目**：`GET /web/dou/-/portaria-alf/vcp-n-134-de-30-de-setembro-de-2026-736019421` → 200，125,532 字节。解析出：题名与枚举行一致；刊日 02/10/2026；版次 187；Seção 1 第 48 页；机构路径 Ministryio da Fazenda/…（5 级）；正文 116 段；类型 Portaria → doc_type `ORDER`。
3. **入账落盘**：文件夹 `01_raw/dou/2026/D20261002/DO1/736019421/`（该次试跑存明文 `doc.html`；2026-10-13 起改存 gzip `doc.html.gz`）；documents 一行（doc_id 以刊日与正门 URL 计算；meta 含上述全部原生字段 + 版面参数 jornal=515/pagina=48）。
4. **特刊日对照**（window=2021-04-01）：该日 Seção 1 正刊零条（`do1` 枚举返回空数组），但整期内容发成了特刊——`secao=do1e` 返回 226 条，其中 `lei-n-14.133-de-1-de-abril-de-2021-311876884` 即 **Lei nº 14.133/2021**（新采购法），详情页 404,152 字节、正文 1,556 段、版次 `61-F`（特刊 F）。该条同时存在于 LexML（urn:lex:br:federal:lei:2021-04-01;14133）与众议院法规档案——三源一致。
5. **窗口合计与全量回填**（库内实值）：双窗试跑（654 任务/650 文档）之后完成 **2013–2025 全量回填**（2026-10-18 终局：409,061 任务全 done、399,561 文档）。游标随回填推进至 dou_last_do1 = dou_last_do1e = **2014-12-31**（2013/2014 稀疏年收尾时向后携带，§7：下次 sync 幂等重扫 2015 起，无害）。
5b. **全量回填逐年分布**（2013–2025，库内实值）：2013=8,290（稀疏年代，接口仅有部分日期）/ 2014=995（接口低保真年）/ 2015=13,440 / 2016=31,161 / 2017=32,818 / 2018=39,163 / 2019=34,035 / 2020=29,547 / 2021=39,489 / 2022=40,802 / 2023=40,746 / 2024=43,558 / 2025=45,093。doc_type 全量分布（2026-10-19 更正类独立成类后）：ORDER 368,702 / RETIFICATION 21,322 / DECREE 6,086 / STATUTE 3,146 / OTHER 305。
6. **三方对账**（2026-10-02 抽样逐字节核对）：磁盘文件 ≡ 账本 file_hash（sha256 抽 3 份含正刊/特刊全一致，650/650 文件在盘）；源站直连重取与盘上字节在**正文容器上逐字节一致**——整页仅有 10 字节的页面外框易变片段（Liferay 会话令牌 authToken 与客户端版本回显，位于 `<article>` 容器之外），符合"源站字节不稳定不作跨下载一致性依据"的既知语义。重复运行同窗口零请求（任务确定性跳过，实测 0 seeds / 0 done）。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country bra --source dou window=2026-10-01:2026-10-02 --dry-run

# 小窗口真实抓取（美国出口代理；其他网络可直连）
HTTPS_PROXY=http://<代理> HTTP_PROXY=http://<代理> \
python cli.py collect --country bra --source dou window=2026-10-01:2026-10-02

# 每日增量（从各刊游标的次日追到昨天）
HTTPS_PROXY=… python cli.py collect --country bra --source dou sync=1

# 只收法律/法令/临时措施/宪法修正四族
HTTPS_PROXY=… python cli.py collect --country bra --source dou window=2026-10-01:2026-10-02 tipos=normativo

# 扩展范围（同时收 Seção 2 人事刊）
HTTPS_PROXY=… python cli.py collect --country bra --source dou window=2026-10-01:2026-10-02 secoes=do1,do1e,do2

# 状态 / 快照 / 修复
python cli.py status --country bra --source dou
python cli.py export --country bra
python cli.py requeue --country bra

# 清理（01_raw → 02_cleaned 纯文本，本地读取、无网络；已清理的自动跳过，
# 升规则版本后重跑即全库重清）
python cli.py clean --country bra            # 先加 --dry-run 看将清理多少
python cli.py clean --country bra --limit 50 # 小批试跑
```

## 7. 更新与增量

- **游标（每刊一个）**：`dou_last_do1`、`dou_last_do1e`（扩刊后为 `dou_last_do2` 等）。每个 `dou_leitura` 完整消费**自己那一刊的那一天**才把该刊游标推到该日——200 且解析完成（无论有无条目）、空版日也算完整消费；中途崩溃该日不推，下次自愈。
- **sync 终点取昨天、不取今天**：当日公报上午生成（确切时点未逐时实测），提前抓会得到与无刊日相同的空形态；为杜绝把"尚未生成"误判为"当日无刊"，增量默认只到昨天。确需当天数据：显式跑 `window=…:今天`。
- **抓的是快照，不设重开**：公报刊出即定，同窗口重复运行安全（任务确定性去重，已抓直接跳过、零请求）。源站无"更新时间"类信号字段，故无重开规则；条目正文永不变。
- **特刊即正刊**：某些日子整期内容发成特刊（`do1` 空、`do1e` 载全部条目），因此默认枚举恒扫 `do1,do1e` 两族；单扫正刊会漏期（2021-04-01 实例，§5）。
- 覆盖边界：阅读页通道 2013-01-02 起；更早日期返回空形态（与无刊日同形、照常入账为合法空），批量回填老年代需走打包文件层（另议）。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **版面 PDF 不取** | 印刷版式不落盘；条目页 HTML 已含全文（Lei 14.133 全文 1,556 段实测），版面取件参数（jornal/pagina/data）已入 meta，需要时按 §1.3 ③ 补取 |
| **2012 年及以前无条目级数据；2013–2015 为稀疏年代** | 阅读页接口覆盖自 2013-01-02，但回溯迁移不全：2014 全年条目个位数、**2015 年 3–7 月整段为空**、12 月稀疏（2015 全年扫荡实测，13,440 条 vs 年中位数外推 ~4.7 万）。老年代（实测 1990–2012 间可达，零星空洞；1980 年代及以前无）在**旧版公报系统**有整页 PDF（按日期+刊+页编址、免 key、无版时返回机器可读错误页，文字层实测存在——可检索扫描件），但无条目级结构。**官方打包 XML/ZIP 通道**（§9）2026-10-19 实测：2013-11..2015-02 与 2015-08..12 各月的 Seção 1 包全部在（月包 10–19MB、条目级 XML、量级为阅读页同期的 ~80 倍），2015-03..07 两通道同缺（上游丢失）；**本数据集当前以 2016–25 为主用区间，2013–2015 仅供定位参考、不完整** |
| **2013–2017 页面正文有源站粘连词** | 该年代源站 PDF→HTML 转换在任意位置丢空格（如 "novembrode 2011"、"acesso,observados"）；以"逗号/分号后直接跟字母"计，密度中位数每万字节 2013=4.7、2016=3.5、2017=2.8，**2018 起为 0**（2021/22 有零星个例）。清理不修（无可靠恢复依据），该年代做文本分析需容忍；如需洁净文本可按 meta 版面参数走 PDF 文字层重提取 |
| **老年代表格无文字层** | 2013–2017 年代约 3% 文档（实测 10/300 抽样，全部集中在 2013/2015/2016/2017）的正文表格是服务端渲染**图片**（`/images/…/TABLE(…)`），清理后文本在表格处空洞；2020+ 表格为文本。图片内容需按版面 PDF 补取（OCR 属另行工程，不在清理范围） |
| **极少数退化题名** | 59/399,561 条题名为空或 ≤3 字符（53 条为"."，集中在 2020-08-27 等）——源站当天 identifica 即如此，原样保留，正文与 meta 完好 |
| **Seção 2/3 默认不收** | 人事刊（约 650 条/日）与司法刊（约 2,300 条/日）出默认范围，`secoes` 参数可扩 |
| **类型过滤词表是开放集** | artType 无官方受控词表端点；映射表按已知词族维护，新词落 OTHER、原词永存 meta（发现高频新词后补映射即可，无需重抓） |
| **robots 声明与免费公开并存** | 站点 robots.txt 全站 Disallow（§2）；以官方公报法定免费地位 + 官方开放数据计划为依据采集，保守限速，事实留档 |
| **网络出口依赖** | 部分网络环境直连被重置（§2）；运行需代理环境变量。出口节点质量有差异：实测（2026-10-02）美国节点通、香港节点被源站边缘拒绝 |
| **条目页与枚举行的日期互校** | 两处刊日不一致时响亮失败（设计如此：枚举到详情只隔数分钟，不一致 = 源站形状变化或迁移期异常，宁响亮不吞数据） |
| **DO1A/DO*SP 等罕见版次** | 源站版次标志位里还有 DO1A、DO2ESP 等变体旗标（2026-10-02 单日未见实例）；当前枚举按显式刊代号请求，罕见版次一旦出现是否被 do1/do1e 覆盖未知——首次撞见应响亮排查 |
| 当日生成前抓不到 | sync 到昨天规避（§7）；显式 window 含今天时自行承担时点风险 |

## 9. 端点速查表

**在用**：

| 用途 | URL 模式 |
|---|---|
| 按日按刊枚举（唯一枚举入口） | `GET https://www.in.gov.br/leiturajornal?secao={do1/do1e/do2/do2e/do3/do3e}&data={DD-MM-YYYY}`（页内 `#params` 内嵌 JSON） |
| 条目详情（元数据+全文） | `GET https://www.in.gov.br/web/dou/-/{urlTitle}` |
| 条目正门（source_url 基底） | `https://www.in.gov.br/web/dou/-/{urlTitle}` |

**已确认存在、本源未用**（各自一句话研究价值）：

| 端点/资产 | 价值 |
|---|---|
| `http://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?data=…&jornal=…&pagina=…` → `…/servlet/INPDFViewer?…&captchafield=firstAccess` | 公报**版面页 PDF**（印刷版式原件；需站点会话；参数已逐条入 meta）。**同时是老年代（约 1990–2012）唯一的在线通道**：按日期+刊+页编址直出整页 PDF，免 key；jornal=1/2/3 对应 Seção 1/2/3（2013 前后编号语义不同，以实取为准） |
| `https://www.in.gov.br/acesso-a-informacao/dados-abertos/base-de-dados` | 官方**开放数据专栏**：条目级 XML 按月×分册打包 ZIP（文件名 S01/S02/S03 + 月 + 年，如 `S01062014.zip`，月包 10–19MB）；页面 `?ano=YYYY&mes=月名（葡语）` 参数服务端渲染出 `documents/…` 直链（2026-10-19 实测纯 HTTP 可枚举可下载，覆盖 2012–2026；约 17% 条目为更正类，其 XML 生成器有"闭合标签粘进属性"的缺陷、内容完好可规则修复）。**2013–2015 稀疏年代的补全候选通道**（2015-03..07 同缺，见 §8） |
| `https://dados.gov.br/dados/organizacoes/visualizar/imprensa-nacional-in` | 国家开放数据门户的国家印刷局组织页（目录站；其 CKAN API 需注册密钥，打包文件真实主机在上一行的 in.gov.br 页面内） |
| `https://www.in.gov.br/consulta/-/buscar/dou` + `POST pesquisa.in.gov.br/imprensa/core/jornalList.action` | 全文检索 UI 及其数据端点（关键词检索用；枚举不需要） |
| `https://www.gov.br/pt-br/servicos/acessar-o-diario-oficial-da-uniao` | 官方服务页（移动 APP DOU 下载入口） |

---

*更新日期：2026-10-18；数据快照：2026-10-18；数据由 **2013–2025 全量回填**实跑背书（终局 409,061 任务全 done / **399,561 文档** / raw gzip 8.15GB + 账本 1.82GB；双窗试跑 654 任务在账为子集），§5 实值。*
