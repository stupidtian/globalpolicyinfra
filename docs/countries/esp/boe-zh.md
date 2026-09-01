# 西班牙（ESP）数据源说明——boe（国家官方公报 BOE）

> 数据快照日期：2026-09-01。文中条目计数、字节数与状态码均为当日对源站直连实测的真实值（可重放复核）；账本内计数在首次真实运行后补记（§5 末行）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。西班牙全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：BOE 是什么、装了谁的产出

**BOE**（*Boletín Oficial del Estado*，西班牙国家官方公报）是西班牙**国家层级一切规范文件的法定公布媒介**——国家法律与法规只有在此公布才生效（对第三人具有效力）。运营方是**国家官方公报署**（Agencia Estatal Boletín Oficial del Estado，隶属首相府系统），门户 www.boe.es。

公报每个工作日出一期，期内按**部（sección）**分组，各部装的东西差别很大：

| 部代号 | 名称 | 内容 | 本源是否采集 |
|---|---|---|---|
| `1` | I. Disposiciones generales（一般条款） | **国家层成品规范**：Ley / Ley Orgánica（法律/组织法）、Real Decreto-ley / Real Decreto Legislativo / Real Decreto（王室令-法/立法王室令/王室令）、Orden（部委令）等 | **是（默认）** |
| `2A` / `2B` | II. Autoridades y personal | 人事任免、招考公告 | 否 |
| `3` | III. Otras disposiciones | 机构决议（Resolución）、指令（Instrucción）、通告（Circular）等 | 否（可经参数扩展） |
| `4` | IV. Administración de Justicia | 司法行政管理文书 | 否 |
| `5A`–`5C` | V. Anuncios | 公共采购公告、其他官方公告、私人公告 | 否 |

**出版节奏**：周一至周六每日一期（每周 6 期），周日通常无刊；偶发节日停刊；极罕见地在休息日出**特刊**（edición extraordinaria）。期号按年连续（如 2026-08-28 = 第 212 期；212→周六 213→周日无→周一 214，实测连续）。

一个对研究范围重要的事实：**自治区（Comunidades Autónomas）的规范绝大多数发自己的官方公报**（如加泰罗尼亚 DOGC、巴斯克 BOPV），不在 BOE；**但有例外**——个别大区把立法交由 BOE 刊发。2026-08-29（周六）第 I 部实测 4 条中有 2 条是马德里自治区的法律（Ley 4/2026, de Caza y Pesca 等），其 `origen_legislativo` 字段为 `codigo="2"` Autonómico（自治区层）。站内高级检索的"自治区来源"过滤器查不到这类条目（2026 全年 0 条，2026-09-01 实测——**检索索引与公报实况不符，不能作范围依据**）。因此本源以条目详情的 `origen_legislativo` 字段为权威：**默认只收 Estatal（国家层）**，`origen=all` 参数放宽（§3）。

**第 I 部的日常构成**：以部委令（Orden）和机构决议为绝对主体，法律只在颁布日出现。2026-08-28（周五）整期 98 条中第 I 部仅 1 条；2026-08-31（周一）整期 297 条（六部）中第 I 部为 **0 条**——研究"政府每天出台了什么规范"，本源一张网收全第 I 部；第 III 部的机构文件性质上接近美国"机构指引层"，需要时经参数扩展（§3）。

**不在本源里的东西**：国会立法过程（Congreso/Senado 两院系统）、EU 法原文（欧盟条例在《欧盟官方公报》直接生效）、以及**现行编纂文本**（texto consolidado，同一法规的"当前有效版"汇编——那是另一套在线系统，机器通道已确认存在，见 §9"暂未用"清单）。

### 1.2 与欧盟法的关系

1. **转化立法——在 BOE 内，正常逐条抓取。** 西班牙把 EU 指令转化为国内法用的是普通 ley / real decreto，与本国立法同通道刊出，按普通条目处理。
2. **直接生效的 EU 条例——不在 BOE。** 需要 EU 条例原文须去《欧盟官方公报》（OJ EU），超出本源范围。
3. **ELI ≠ EU 标记。** ELI（European Legislation Identifier，欧洲统一立法标识方案）是西班牙给本国规范逐步编的统一 URL 标识，**与是否涉及 EU 法无关**（条目标题、机构与引用关系才相关，判据同法国 JORF 的口径）。

### 1.3 数据通道：BOE 官方开放数据 API（免 key、无会话、无浏览器）

boe.es 站内有一套**官方开放数据 API**（文档页 `www.boe.es/datosabiertos/api/api.php`，2026-09-01 实测 200）。本源用其中两个端点：

**① 按日摘要**（枚举的唯一入口）：

```
GET https://www.boe.es/datosabiertos/api/boe/sumario/{YYYYMMDD}
Accept: application/xml
```

- **URL 由日期直接构造**，无需先抓任何索引页（这是与德国"树形导航"、法国"目录列表"最大的不同——种子任务可以直接逐日生成）；
- **必须带 `Accept: application/xml`（或 `application/json`）请求头**：不带则 HTTP 400 拒答（2026-09-01 实测，错误体写明"不支持该 Accept 的 MIME 类型"）；两种格式内容同构，本源统一用 XML；
- 响应结构（2026-08-28 实测形状）：`sumario → metadatos(公报名, 日期) → diario(期号) → seccion(部代号+名) → departamento(部门代号+名) → epigrafe(主题目) → item`；条目字段：`identificador`（如 `BOE-A-2026-18261`，全库唯一主键）、`control`（流水号）、`titulo`、`url_pdf`（带字节数与起止页码）、`url_html`、`url_xml`；
- 条目可直接挂在 departamento 下或再隔一层 epigrafe，两种形状都出现（2026-08-28 与 2026-08-31 两日实测），解析对两者都处理；
- **无刊日（周日、节日）返回 HTTP 404 + 固定形状的 XML 错误体**（"La información solicitada no existe"，样本已留存）——这是"当日无刊"的正常回答，不是故障（怎么区分见 §3）；
- **档案覆盖 1961 年起**（1961-01-10 实测 200；1960-01-09 实测 404；起点在 1960–1961 之间，逐日枚举自然发现，无需预知）。

**② 条目详情**（一条 = 元数据 + 分析 + 全文，一站式）：

```
GET https://www.boe.es/diario_boe/xml.php?id={identificador}
Accept: application/xml
```

响应为一棵 `documento` 树，四个子块：

| 子块 | 内容 | 本源用法 |
|---|---|---|
| `metadatos` | 33 个字段：标识、部门、类型、三个日期、期号部号、页码、PDF/EPUB 链接、效力状态等 | **文档记录的主要来源**（字段清单见 §4） |
| `metadata-eli` | ELI 的 RDF 描述（类型、主题词、版本关系） | ELI 与主题词入 meta |
| `analisis` | materias（主题）、notas（勘误注记）、referencias（引用关系）、alertas（警报词） | referencias 随源照收入 meta（谁修订谁的字段证据） |
| `texto` | **全文**（类 XHTML：段落 / 引用块 / 表格） | 主文件原样落盘 |

**三个日期齐全**是本源对时间序列研究的核心价值（§4 字段表）。**全文的年代边界**：1990 年起 `texto` 有内容（1990/1995/2005/2009/2012 各年抽样实测）；更早的条目 `texto` 为空元素（扫描年代，如 1964-01-06 的 BOE-A-1964-417，唯一内容是 8,355,776 字节的扫描 PDF）。

**一个口径要点：详情是"活视图"。** `metadatos` 里的效力状态字段（是否废止、是否被司法撤销等）由公报署持续维护——1964 年那条的"更新时间"是 2024-10-14（实测）。本源采集的语义是**取到时刻的快照**：公报刊出即定的部分（标题、日期、页码、全文）永不变化；效力状态记录的是抓取当日状态。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 无（无 cookie、无 token；全部请求无状态直连，2026-09-01 连续约 60 请求实测） |
| 请求头 | **必须带 `Accept: application/xml`**（本源唯一特殊要求，见 §1.3） |
| 限额 | 无公开限额。连续数十请求无拦截（2026-09-01 实测）；框架统一限速（0.5–1 秒/请求）足够安全 |
| 反爬 | 无（无 Cloudflare 类防护，curl 直连即可） |
| 响应格式 | XML，UTF-8；摘要典型 80–150 KB/日，条目详情典型 15–45 KB/条 |
| 许可 | **公报署 2024-06-27 决议批准的标准再利用条款**（西班牙《公共部门信息再利用法》Ley 37/2007 框架）：允许商用与非商用再利用；须注明来源——引用格式为 *"Fuente de los datos: Agencia Estatal Boletín Oficial del Estado"* 并附 www.boe.es 链接（aviso legal 页 §Cuarta，2026-09-01 实测） |

站内另有**高级检索**（`/buscar/legislacion_ava.php`，HTML 表单通路）2026-09-01 复测仍可用，但它只索引"立法类"文档（2026-08-28 整期 98 条中只返回 1 条），不作为采集通道。

## 3. 抓什么：任务类型清单

每种任务 = 一次下载 + 一次解析。共 **2 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `boe_sumario`（种子，逐日一个） | GET 按日摘要 API（§1.3 ①） | 解析目标部的条目（默认 `1`，参数可改）→ 每条生成一个 `boe_item`；当日无目标部 → 合法空产出；当日无刊（404，验证响应体为已知"无刊"形状后）→ 合法空产出；两种情况都推进游标 `boe_last_date`（账本里"已完整消费到哪一天"的进度标记，详见 §7） |
| `boe_item` | GET 条目详情 XML（§1.3 ②） | 一个文档记录 + 一个文件落盘（响应字节原样为 `doc.xml` 主文件）；自治区来源条目在默认口径下记合法跳过（见下）；推进无 |

任务链：`boe_sumario × 每一天 → boe_item × 每条目标部条目`。

命令行参数（key=value 形式）：

```
window=FROM:TO    闭区间日期窗口，如 2026-08-28:2026-08-31（必填，或改用 sync=1）
sync=1            增量：起点 = 游标 boe_last_date 次日，终点 = 昨天（为什么不是今天见 §7）
secciones=1       采集哪些部，逗号分隔（默认 1；如 1,3 同时收第 III 部）
origen=estatal    来源层级过滤：estatal（默认，只收国家层）| all（连自治区条目一起收）
```

**来源层级过滤在条目层执行**：摘要不带来源字段，且高级检索的自治区过滤器不可靠（§1.1），所以每个条目都照常抓详情、以详情里的 `origen_legislativo` 字段为准——自治区条目在默认口径下记"合法跳过"（任务完成、不入账）；该选择随任务参数走，将来改 `origen=all` 重跑会自动补抓，无需清库。

**"404 = 当日无刊"的判定纪律**（本源与既有各国源差异最大的一处）：

1. 摘要请求在构造时显式声明"此请求的 404 是数据、不是故障"——框架对未作此声明的请求（包括本源的条目请求）仍把 404 记为永久失败；
2. 收到 404 后**先验证响应体形状**是否为已知的"无刊"XML（`<response><status><code>404</code>…`）：是 → 判定"当日确认无刊"，任务记完成、游标照推；形状不符（HTML 报错页、空体等）→ 按故障升级，绝不静默吞掉；
3. 条目请求**不做**此声明：条目标识来自几分钟内刚拿到的摘要，正常不可能 404，一旦出现就是真异常，应当响亮失败。

## 4. 数据落到哪

**零领域表**（扁平文档型路径，同德国 BGBl / 法国 JORF）：公报条目刊出即定、条目即文档本体，语料里没有跨文档的持久实体；条目间的引用关系（谁修改谁）是**字段**不是实体，随源照收进 meta（建图留给分析阶段）。一切研究字段进 `documents` 一张表：

| 列 | 内容 |
|---|---|
| `doc_id` | `ESP_{出版日YYYYMMDD}_{hash8(source_url)}` |
| `title` | 完整题名（如 `Orden PJC/903/2026, de 26 de agosto, por la que se modifica el anexo II del Real Decreto 1205/2011…`） |
| `publication_date` | 公报刊出日（fecha_publicacion）——研究时间轴的主日期 |
| `issuing_authority` | 部门全名（departamento，如 `Ministerio de la Presidencia, Justicia y Relaciones con las Cortes`） |
| `source_url` | `https://www.boe.es/buscar/doc.php?id={identificador}`——公报署的文档正门 URL，1964 年与 2026 年条目实测均有效（全年代稳定、可重建） |
| `raw_format` / `language` | `xml` / `spa` |
| `doc_type` | 由 rango 映射的受控类型（下表）；西语原词永存 meta |
| `entity_ref` | NULL（扁平国家） |
| `meta` | 见下 |

**meta 字段**（原生字段无损收，全字符串）：`identificador`（BOE-A-… 主键）、`control`、`rango` + `rango_codigo`（类型原词+代码）、`numero_oficial`（文号如 PJC/903/2026）、**`fecha_disposicion`（制定/签署日）**、**`fecha_vigencia`（生效日）**（与 publication_date 合成日期三件套）、`origen_legislativo`（来源层级：Estatal 国家层 / Autonómico 自治区层——默认过滤的依据字段，§3）、`seccion`、`diario_numero`（期号）、`pagina_inicial` / `pagina_final`、`url_pdf`（+字节数）、`url_epub`、`url_eli`（老条目无，如实缺省）、`estatus_derogacion` / `fecha_derogacion`（废止状态与日期，2026-09-01 实测新条目均为 N/空）、`judicialmente_anulada`、`estado_consolidacion`、`letra_imagen`、`materias`（主题词，分号连接）、`alertas`（警报词）、`referencias`（引用关系串，格式 `BOE-A-2015-11724:MODIFICA;…`）、`fecha_actualizacion`（源站快照时间戳）、`n_texto_blocks`（全文块数）、`files`（文件清单）。

**doc_type 映射**（原生优先：rango 原词与代码永存 meta，映射只是一层受控别名；跨国可比的统一类型学不在采集层做）：

| rango（西语原词） | 代码 | doc_type |
|---|---|---|
| Constitución | 1070 | CONSTITUTION |
| Ley Orgánica / Ley | 1290 / 1300 | STATUTE |
| Real Decreto-ley / Real Decreto Legislativo / Real Decreto / Decreto-ley / Decreto Legislativo / Decreto | 1320 / 1310 / 1340 / 1500 / 1470 / 1510 | DECREE |
| Orden / Orden Foral | 1350 / 1540 | ORDER |
| 其余（Instrucción、Circular、Acuerdo、Resolución…） | — | OTHER |

文件落点（"一项政策一个文件夹"，年/日双层分片）：

```
{data_root}/ESP_policy/
├── state.db
├── failures/
└── 01_raw/boe/
    └── 2026/D20260828/                        ← 年 = 出版年；日 = 公报刊出日
        └── BOE-A-2026-18261/                  ← 一条条目一个文件夹（全库主键命名）
            └── doc.xml                        ← 条目详情 XML 原样字节（文档主文件）
```

- `doc.xml` 是文档主文件（唯一挂 doc_id 的文件，账本 local_path 指向它）；PDF 不抓（§8），其 URL/字节数/页码已入 meta，将来需要可按 URL 直接补抓、无需重新枚举。
- v1 每文件夹单文件；多文件惯例（正文拆分、双语版本）留待有真实需要时启用。

## 5. 完整案例走查（2026-08-28 一期，源站直连实值）

一个真实出版日的全链数据（每步可重放）：

1. **摘要**：`GET …/sumario/20260828` → 200，81,149 字节。当期 = 第 212 期，共 7 部 98 条（I:1、II-A:7、II-B:6、III:5、V-A:60、V-B:18、V-C:1；该日无第 IV 部）。目标部（I）只有 1 条 → 生成 1 个 `boe_item`。
2. **条目详情**：`GET …/xml.php?id=BOE-A-2026-18261` → 200，17,463 字节。解析出：类型 `Orden`（代码 1350）→ doc_type `ORDER`；文号 `PJC/903/2026`；部门 `Ministerio de la Presidencia, Justicia y Relaciones con las Cortes`（9585）；制定日 2026-08-26、刊出日 2026-08-28、**生效日 2026-08-29**（三日期齐全）；期号 212、部号 1、页码 117076–117078；ELI `https://www.boe.es/eli/es/o/2026/08/26/pjc903`；主题词 7 个（Juguetes、Seguridad de productos…）；全文 18 个块（含 1 个镍/钴限值表格）；PDF 207,253 字节（不抓，URL 入 meta）。
3. **入账落盘**：文件夹 `01_raw/boe/2026/D20260828/BOE-A-2026-18261/doc.xml`；documents 一行（doc_id 以刊出日与正门 URL 计算）；meta 含上述全部原生字段。
4. **同窗口的边界形态**（2026-08-28:31 四日窗口，2026-09-01 实跑库内实值）：28 日（周五 212 期）第 I 部 1 条 → 正常入账；29 日（周六 213 期）第 I 部 4 条 → **2 条 Estatal 入账 + 2 条马德里自治区法律合法跳过**（origen 过滤首次真实触发）；30 日（周日）→ 404"无刊"→ 记完成、游标照推；31 日（周一 214 期）整期无第 I 部 → 合法空产出、游标照推。**四个日期覆盖五种形态**（正常日 / 含跳过日 / 无刊日 / 无目标部日）。
5. **一条法律的样子**（2026 年真实样本）：`BOE-A-2026-16653`（Ley 2/2026），详情 42,619 字节、全文 54 块；引用关系显示其 `MODIFICA` 文本汇编 RDL 8/2015（BOE-A-2015-11724）——修订关系的原始证据即此收进 meta。
6. **窗口合计**（库内实值）：**9 任务全 done（4 boe_sumario + 5 boe_item）、0 失败、0 告警；3 文档、3 文件、游标 `boe_last_date=2026-08-31`**。文件树 `01_raw/boe/2026/` 下 `D20260828/`（1 个政策文件夹）与 `D20260829/`（2 个）。
7. **三方对账**（2026-09-01 逐字节核对）：磁盘文件 ≡ 账本 file_hash ≡ 源站直连响应字节，3/3 一致。重复运行同窗口零请求（任务确定性跳过）；`sync=1`（游标已在昨天）零种子零请求。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country esp --source boe window=2026-08-28:2026-08-31 --dry-run

# 小窗口真实抓取（§5 的四日窗口）
python cli.py collect --country esp --source boe window=2026-08-28:2026-08-31

# 每日增量（从上次游标的次日追到昨天）
python cli.py collect --country esp --source boe sync=1

# 扩展采集范围（同时收第 III 部机构文件）
python cli.py collect --country esp --source boe window=2026-08-28:2026-08-31 secciones=1,3

# 连自治区条目一起收（如马德里法律）
python cli.py collect --country esp --source boe window=2026-08-29:2026-08-29 origen=all

# 状态 / 快照 / 修复
python cli.py status --country esp --source boe
python cli.py export --country esp
python cli.py requeue --country esp
```

## 7. 更新与增量

- **游标**：`boe_last_date`。每个 `boe_sumario` 完整消费**自己那一天**才把游标推到该日——200 且解析完成（无论目标部有无条目）、或 404 经响应体验证为"无刊"，都算完整消费；中途崩溃该日不推，下次自愈。
- **sync 终点取昨天、不取今天**：当日摘要上午生成（2026-09-01 实测马德里 11:24 前已可取；更早的确切时点未逐时实测）。在生成前去问当天会得到与无刊日**完全相同**的 404——为杜绝把"尚未生成"误判为"当日无刊"，增量默认只到昨天。确需当天数据：在马德里上午生成时点之后显式跑 `window=…:今天`。
- **抓的是快照，不设重开**：公报刊出即定，同窗口重复运行安全（任务确定性去重，已抓直接跳过、零请求）。详情里的效力状态字段（是否废止等）是活视图，本源记录抓取当日状态；持续跟踪废止需周期性按新身份重扫（机制上与韩国源的 refresh 模式同构，本源暂未启用）。
- 往更早日期回填会把游标往回带，下次 sync 幂等重扫（无害，与美德既有判例一致）。
- 1961 年之前的日期一律 404——那是档案边界，不是故障。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **PDF 不抓** | 印刷版式不落盘；URL/字节数/起止页码入 meta 无损。1961–1989 扫描年代（XML 全文为空）回填时**必须**改抓 PDF，属回填议题 |
| **全文年代边界** | 1990 年起详情 XML 含全文；更早条目只有元数据（§1.3）——小窗口与现代增量不受影响 |
| **只收第 I 部** | 第 III 部机构文件（Resolución/Instrucción 等）未收，`secciones` 参数可扩；第 II/IV/V 部（人事/司法/公告）不在目标内 |
| **自治区条目默认排除** | 第 I 部偶发自治区规范（如马德里法律，§1.1）——详情层按 `origen_legislativo` 过滤、记合法跳过；`origen=all` 放宽（§3） |
| **ELI 覆盖不全** | 新条目必有（2026 实测），老条目没有（1964 实测）；ELI 只入 meta 不作文档标识，缺省如实留空 |
| **效力状态是时点快照** | 废止/撤销状态抓的是当天值，不会自动更新（§7） |
| **当日生成前抓不到** | sync 到昨天规避（§7）；显式 window 含今天时自行承担时点风险 |
| **周日特刊** | 逐日枚举不跳过任何日期，特刊一旦出刊即正常入账（这正是不按星期几跳日的理由） |
| 同日多期 | 摘要 XML 的 `diario` 结构上是列表（同日多期=特刊），实测均为单个；解析遍历全部，不为单期写死 |
| 老数据脏值 | 1960 年代条目文号（numero_oficial）常为空——原样入库，不推断 |
| 高级检索通路 | 仍可用（2026-09-01 复测 200）但只索引立法类文档，仅作交叉核对，不作采集通道 |

## 9. 端点速查表

**在用**：

| 用途 | URL 模式 |
|---|---|
| 按日摘要（枚举唯一入口） | `GET https://www.boe.es/datosabiertos/api/boe/sumario/{YYYYMMDD}`（须带 `Accept: application/xml`） |
| 条目详情（元数据+分析+全文） | `GET https://www.boe.es/diario_boe/xml.php?id={identificador}`（须带 `Accept: application/xml`） |
| 文档正门 URL（source_url 基底） | `https://www.boe.es/buscar/doc.php?id={identificador}`（浏览器可开；采集不走此通道） |

**已确认存在、本源未用**（各自一句话研究价值）：

| 端点 | 价值 |
|---|---|
| `…/datosabiertos/api/legislacion-consolidada/id/{id}`（另有 `/metadatos` `/texto` `/analisis` `/texto/indice` 子端点） | **现行编纂文本的机器通道**——版本序列研究的直接素材（2026-09-01 实测：有编纂版的 id 返回 200，无则 404） |
| `…/datosabiertos/api/datos-auxiliares/{rangos\|materias\|departamentos\|estados-consolidacion\|relaciones-anteriores\|relaciones-posteriores\|ambitos}` | 官方受控词表族——跨国类型学对齐时的权威对照 |
| `…/datosabiertos/api/borme/sumario/{fecha}` | 商事登记公报（BORME）——公司注册数据，另一研究对象 |
| `https://www.boe.es/boe/dias/{Y}/{M}/{D}/pdfs/{标识}.pdf` | 印刷版 PDF 直链（含 1960 年代扫描件）——回填扫描年代时用 |
| `https://www.boe.es/buscar/legislacion_ava.php` | 高级检索（立法索引）——交叉核对用 |

**rango 类型词表**（meta.rango 观测来源；34 项全表自官方检索表单提取，另有机器版见上词表族端点）：Constitución(1070) / Ley Orgánica(1290) / Ley(1300) / Real Decreto-ley(1320) / Real Decreto Legislativo(1310) / Real Decreto(1340) / Decreto-ley(1500) / Decreto Legislativo(1470) / Decreto(1510) / Orden(1350) / Orden Foral(1540) / Instrucción(1410) / Circular(1390) / Resolución(1370) / Acuerdo(1020) / Sentencia(1240) / Auto(1250) / Corrección(1590) / Acuerdo Internacional(1180) / 及其余（Decreto Foral、Ley Foral、Reforma、Edicto、Directiva、Decisión、Declaración、Recomendación、Reglamento、Providencia、Nota Diplomática、Otros）。

---

*更新日期：2026-09-01；数据快照：2026-09-01；数据由 window=2026-08-28:2026-08-31 实跑背书（9 任务零失败 / 3 文档 3 文件 / 磁盘≡账本≡源站逐字节一致 / 幂等重跑零请求）。*
