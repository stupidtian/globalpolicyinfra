# 阿根廷（ARG）数据源说明——bora（国家官方公报 BORA）

> 数据快照日期：2026-09-03（通道裁决与首次真实运行背书；探查原始样本 2026-09-02/03 固化在任务档案）。文中条目计数、字节数与状态码均为对源站直连实测的真实值（可重放复核）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。阿根廷全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：BORA 是什么、装了谁的产出

**BORA**（*Boletín Oficial de la República Argentina*，阿根廷共和国官方公报）是阿根廷**国家层级一切规范文件的法定公布媒介**——法律、总统令（含 DNU，见下）、部委决议在此颁布方对第三人产生效力。运营方是国家官方公报局（Dirección del Registro Oficial，隶属司法部系统），门户 www.boletinoficial.gob.ar。

公报每个工作日出一期，期内按**部（sección）**分组。部有四个（2026-09-02 实测，门户导航直接可见）：

| 部 | 名称 | 内容 | 本源是否采集 |
|---|---|---|---|
| `primera` | 第一部 | **国家层成品规范与官方公告**：Ley（法律）、Decreto（总统令，含 DNU）、Resolución（决议）、Disposición（处令）、Decisión Administrativa（行政决定）、Acordada（法院协定）、Tratado（条约）、Convención Colectiva de Trabajo（集体劳动合同）、Aviso Oficial（官方公告）等（官方 25 个类目全表见 §9） | **是** |
| `segunda` | 第二部 | 人事任免与招考 | 否（门户 robots.txt 唯一禁抓的部，2026-09-02 实测 103 字节；也无研究价值） |
| `tercera` | 第三部 | 采购与招标（SUMINISTROS 物资供应类目为主，2026-08-28 实测 62 条） | 否 |
| `cuarta` | 第四部 | `.ar` 域名注册公告（2026 年前后新增的部，2026-08-28 实测类目仅 DOMINIOS 公告） | 否 |

**DNU**（*Decreto de Necesidad y Urgencia*，必要性与紧迫性总统令）是阿根廷特有的高阶政策工具：总统在国会无法及时立法时绕开立法程序直接颁布的法令（宪法第 99 条授权，国会事后审议）。它在公报里与普通总统令同载第一部、类目同为 DECRETOS，但每条目自带的规范标识（§1.4 的 Norma ID）以 `DNU-` 开头（如著名的 `DNU-2023-70-APN-PTE`，即 2023 年 12 月的第 70 号 DNU"阿根廷经济重建基础"，实测刊于 2023-12-21、占公报第 3–56 页）。本源按此原生标识把它与普通总统令区分开（§4）。

**出版节奏**：周一至周五每日一期（周六日无刊），节假日停刊；偶发节日调休。官方出版日历端点给出权威的出刊日清单（§9）：2026 年至 9 月 2 日共 162 个出刊日，全部为工作日；历史年份每年约 246–278 个出刊日（1940–2020 各年实测）。**档案在线覆盖 1940 年至今**（1940-01-02 列表实测可达 62 条；与旧一代采集的起点一致），更早年份未穷尽下探。

### 1.2 机器通道：枚举走分部页会话链（公报原件视图）

门户没有 sitemap（`/sitemap.xml` 返回 302 错误页，2026-09-02 实测），也没有开放数据 API。采集走门户页面脚本自用的三个 HTTP 端点族：

| # | 通道 | 形态 | 本源用途 |
|---|---|---|---|
| ① | **分部页链**（枚举主通道） | `GET /edicion/actualizar/{DD-MM-YYYY}`（XHR，把日期写进服务端会话）→ `GET /seccion/primera`（当日第一期列表，HTML）→ `GET /seccion/actualizar/primera?pag=N&ult_rubro=…`（无限滚动翻页 JSON 片段） | **按日枚举第一部条目**。这是公报自己的期视图，完整（§1.3 实证） |
| ② | 条目详情页 | `GET /detalleAviso/{部}/{条目id}/{YYYYMMDD}` | 一条 = 标题块 + 正文全文 + 附件清单（§1.4）。**无会话依赖**（日期在 URL 内；1950 会话取 2026 页、无会话直取均正确，双双实测） |
| ③ | 附件 PDF 端点 | `GET /pdf/download_anexo?…`（四选择参数全在 URL） | 条目附件逐个下载（GET 与浏览器实际使用的 POST 字节级等价，2026-09-02 实测） |

会话语义（§6.3 契约的既有模式）：日期选择是**服务端会话状态**——同一次采集运行内，"设日期"任务必须先于该日的列表任务、且同一时刻只激活一天。本源用**任务链**表达这个顺序：每一天的最后一页列表任务登记下一天的"设日期"任务；种子只播第一天（游标之后的首日，附每次运行的运行戳，使崩溃重跑能重建设置请求的副作用）。列表任务自带双保险：页面内嵌的 `fechaSeleccionadaYMD` 必须等于任务日期（不符按瞬时错误重试——陈旧链自愈），每个条目行的日期也逐一校验。

### 1.3 枚举通道裁决：为什么不是站内检索端点

门户另有高级检索数据端点（`GET /busquedaAvanzada/realizarBusqueda`，页面脚本所用，GET/POST 等价）——本源最初用它枚举，**真实运行对账后否决**：2026-08-28..31 验证窗内，检索通道漏掉 8 个分部页实际列出的条目（08-28 漏 346550/346551/346552，08-31 漏 346572/346623/346630/346631/346632，均为机关公告类）；这 8 个条目在邻近日、乃至横跨 10 天共 445 条的宽窗检索里都查不到（2026-09-03 实测）——**检索索引有真窟窿，不是日期归属模糊**。计数对账曾长期掩盖这一点（漏掉的条目恰好被若干"提前入库的未来条目"在数量上抵消）；逐 ID 集合比对才现形。分部页通道则是逐条相等：08-28 = 43 条同 ID、08-31 = 78 条同 ID（2026-09-03 双通道对账）。检索端点保留为对账工具（§9）。

另有一个检索通道暴露的真实现象（分部页通道不受影响）：检索会把**尚未出版**的条目提前挂在近邻日返回（其详情页自报出版日为 1–4 天后）。按本源的身份规则（§5，页面自报出版日为准），这类条目即使提前抓到也会落在正确的日期轴上。

### 1.4 条目详情页的两种形态（按页面自身形状区分，不按年份假设）

| 形态 | 页面判据 | 内容 |
|---|---|---|
| **文本型**（现代年代） | `#tituloDetalleAviso` 标题块：`<h1>` 机关名（如 PODER EJECUTIVO）+ `<h2>` 规范引用（如 `Decreto 817/2026`）+ `<h6>` **规范标识与描述**（如 `DECTO-2026-817-APN-PTE - Dispónese Intervención. Designación.`）；`#cuerpoDetalleAviso.detalle-cuerpo` 正文块（**全文 HTML 内联**，含签署日如 `Ciudad de Buenos Aires, 27/08/2026`） | 正文 + `Fecha de publicación 28/08/2026`（刊出日）+ 公报页码区间（如第 4–6 页）+ 附件清单 `#anexosDiv`（有则）。**通知子形态**（2026-09-03 首次真实运行发现）：机关公告类条目标题块只有 `<h1>` 机关名、无 h2/h6——标题合成"{机关} - {类目}"（如 `AGENCIA DE RECAUDACIÓN Y CONTROL ADUANERO - Aviso Oficial`） |
| **扫描壳型**（早年） | 无标题块与正文块，但刊出日仍在；页面脚本里有 `convertBase64InUrlBlob("JVBERi0…")`——**整份扫描 PDF 以 base64 内嵌在页面里**（这就是此类页面约 0.4–1 MB 的来源） | 刊出日 + 内嵌扫描 PDF（同一响应内即可提取，无需第二个请求）；此形态下逐条目 PDF 端点返回 500（1950 年条目实测） |

**规范标识（Norma ID）**：`<h6>` 首段的 `{类型}-{年}-{号}-{机关}` 结构（`DECTO-2026-817-APN-PTE` / `DNU-2023-70-APN-PTE` / `RESOL-2026-247-APN-SCLYA#JGM`）——类型标记比部内类目（rubro）更细，是区分 DNU 与普通总统令的原生依据。

**附件（anexo）**：部分条目把附表、名单等做成独立 PDF 附件，详情页 `#anexosDiv` 内逐个列出（每个有独立 `idAnexo` 数字标识与序号）。正文明言"附件……发布于 BORA 网络版"——**印刷版不含附件，网络版是附件的唯一官方载体**，因此附件属于采集范围。单条目附件数可达 12 个（2026-08-28 实测）。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目 |
| 会话 | 枚举链需要传输层 cookie jar（§1.2；详情页与附件端点则完全免会话——日期在 URL） |
| 请求头 | 分部页翻页与"设日期"请求带 `X-Requested-With: XMLHttpRequest`（门户自身脚本的同款头） |
| 限额 | 无公开限额。15 个请求连发（1–1.5 秒间隔、混合端点）零拦截（2026-09-02 实测） |
| 反爬 | 无 Cloudflare。站点在企业级负载均衡（F5）之后，会发几个 `TS*` 开头的管理 cookie（HttpOnly，逐响应轮换）——HTTP 客户端带 cookie jar 即可，无脚本挑战 |
| 代理 | **注意**：本机若配有系统级代理（Windows 注册表代理即算），HTTP 库会默认走代理出境，该路径对阿根廷政府站点会被掐断 TLS（`SSL EOF`，2026-09-03 实测与归档）；**运行时设 `NO_PROXY=www.boletinoficial.gob.ar` 直连即可**（直连路径全窗口实测稳定） |
| 响应速度 | **服务器偏慢**：普通请求中位约 4.7 秒，PDF 6–9 秒，早年扫描壳页 0.4–1 MB（2026-09-02 实测）。建议请求间隔 1.5–3 秒（`collect --delay 1.5:3`） |
| 编码 | UTF-8 |

## 3. 抓什么：任务类型清单

每种任务 = 一次下载 + 一次解析。共 **4 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `bora_fecha`（种子，逐窗一个起链） | GET 设日期端点（XHR） | 把窗口内"下一个未消费日"写进服务端会话 → 链出该日的 `bora_seccion`。种子参数带运行戳：崩溃重跑时重建设置请求（其副作用不随进程存活，done-skip 不得吞掉它） |
| `bora_seccion` | 页 1：GET `/seccion/primera`（HTML）；续页：GET 翻页端点（JSON 片段） | 解析列表（类目分组头 + 条目行；回形针附件变体链接不成为行）→ 每条一个 `bora_detalle` 种子（携带类目、机关、编号、描述——扫描壳型条目的标题来源）。**页 1 自证**：页面内嵌 `fechaSeleccionadaYMD` 必须等于任务日期（不符 = 陈旧链，瞬时错误重试自愈）；**无刊日**（周六日、节假日）：分部页重定向到主页（传输层跟随后的 200）——按"有主页日历标记且无列表容器"判型，记合法空产出并推游标；**翻页完成**（片段答 `hay_mas_datos=false`）→ 推游标 `bora_last_date` + 链出下一日 `bora_fecha`（窗口未完时）。每页 100 条上限，单页即全量的小日也会探测一次空页 2 作为完成信号（该通道无总数字段） |
| `bora_detalle` | GET 条目详情页（§1.4） | 一个文档记录 + 一个主文件：文本型存 `detalle.html`（响应字节原样）；扫描壳型从页面提取内嵌 PDF 存 `aviso.pdf`；页面带附件清单 → 在文档 meta 预声明附件文件名 + 每个附件生成一个 `bora_anexo` 种子。**身份以页面自报出版日为准**（§5） |
| `bora_anexo` | GET 附件 PDF 端点（`seccion`/`nroAnexo`/`idAnexo`/`fechaPublicacion` 四参数全在 URL） | 一个 PDF 文件，落到对应条目文件夹的 `anexo_{序号}.pdf` |

任务链：`bora_fecha(D) → bora_seccion(D) 页 1..N → [bora_detalle × 每条 → bora_anexo × 每附件]，页 N 完成 → bora_fecha(D+1) → …`。详情与附件任务免会话，可与链并行消化。

命令行参数（key=value 形式）：

```
window=FROM:TO    闭区间日期窗口，如 2026-08-28:2026-08-31（必填，或改用 sync=1）
sync=1            增量：起点 = 游标 bora_last_date 次日，终点 = 昨天（为什么不是今天见 §7）
```

播种规则（链纪律）：**只播游标之后的首日**一个 `bora_fecha` 种子（带运行戳），其余日子由链逐日登记——这保证服务端会话里同一时刻只有一天被激活。整个窗口都在游标之内时不产生种子（游标语义 = "已确认消费到"；重刷旧窗口属修复通道事务，不是重扫）。

## 4. 数据落到哪

**零领域表**（扁平文档路径，同德国 BGBl / 法国 JORF / 西班牙 BOE）：公报条目刊出即定、条目即文档本体，语料里没有跨文档的持久实体；条目间的修订/引用关系是正文文本内容，不是结构化关系字段（建图留给分析阶段）。一切研究字段进 `documents` 一张表：

| 列 | 内容 |
|---|---|
| `doc_id` | `ARG_{出版日YYYYMMDD}_{hash8(source_url)}` |
| `title` | 文本型规范形 `"{规范引用} - {描述}"`（如 `Decreto 817/2026 - Dispónese Intervención. Designación.`）；通知形 `"{机关} - {类目}"`（如 `AGENCIA DE RECAUDACIÓN Y CONTROL ADUANERO - Aviso Oficial`）；扫描壳型用列表行拼同款格式 |
| `publication_date` | 详情页 `Fecha de publicación`（权威；失败回退 URL 日期） |
| `issuing_authority` | 列表行机关（比详情页 h1 更稳：个别条目 h1 是法令名而非机关——如 DNU 70/2023 为 "BASES PARA LA RECONSTRUCCIÓN DE LA ECONOMÍA ARGENTINA"；h1 原词永存 meta） |
| `source_url` | `https://www.boletinoficial.gob.ar/detalleAviso/{部}/{条目id}/{出版日YYYYMMDD}`——**以页面自报出版日为准的规范形式**（该日期形式实测可服务；同一条目可能挂多日列表，页面日期给出唯一身份；站内偶见的 `?busqueda=1`、`?anexos=1` 参数一律剥除） |
| `raw_format` / `language` | 文本型 `html`、扫描壳型 `pdf`；`spa` |
| `doc_type` | 类目 + 规范标识前缀联合映射（下表）；两个原词永存 meta |
| `entity_ref` | NULL（扁平国家） |
| `meta` | 见下 |

**meta 字段**（原生无损收，全字符串）：`aviso_id`（条目数字标识，全库主键）、`seccion`、`rubro`（部内类目）、`norma_id`（规范标识全串）、`norma_tipo`（前缀：DECTO/DNU/RESOL/…）、`nro_norma`（如 `817/2026`）、`detalle_h1`（详情页 h1 原词）、`lista_autoridad` / `lista_nro` / `lista_desc`（列表行原词）、`fecha_publicacion_raw`、`pagina_desde` / `pagina_hasta`、`url_pdf`（逐条目印刷版 PDF 直链）、`anexos`（`序号:附件id;…`）、`files`（主文件 + 附件清单）、`forma`（`texto` 文本型 / `scan` 扫描壳型）、`n_bloques`（正文块数）。

**doc_type 映射**（原生优先：类目原词与规范标识前缀永存 meta，映射只是一层受控别名；跨国可比的统一类型学不在采集层做）：

| 原生（类目 ∩ 标识前缀） | doc_type |
|---|---|
| Leyes / Legislacion | STATUTE |
| DECRETOS 类目且前缀 `DNU-` | EMERGENCY_DECREE |
| DECRETOS 类目（`DECTO-` 及其余） | DECREE |
| 其余 22 个类目（Resoluciones / Disposiciones 各变体 / Decisiones Administrativas / Acordadas / Sentencias / Fallos / 集体合同 / 条约 / 官方公告…） | OTHER |

**日期口径说明**：BORA 无结构化的制定日/生效日字段——签署日只存在于正文文本（如 `Ciudad de Buenos Aires, 27/08/2026`），部分条目正文尾还有公报登记行（`e. 28/08/2026 N° 61202/26 v. 28/08/2026`，登记号与出入日期）。两者都随正文原样收录，结构化抽取留给清洗阶段；采集层只入刊出日一列，如实记缺不猜。

文件落点（一项政策一个文件夹，**年/日双层按出版日分片**——与 doc_id 同一日期轴）：

```
{data_root}/ARG_policy/
├── state.db
├── failures/
└── 01_raw/bora/{出版年}/D{出版日YYYYMMDD}/
    └── {条目id}/
        ├── detalle.html      ← 文本型主文件（响应字节原样）
        ├── aviso.pdf         ← 扫描壳型主文件（内嵌 base64 提取）
        └── anexo_{序号}.pdf  ← 附件（由 bora_anexo 任务落盘，文件名在主文档 meta 已预声明）
```

## 5. 完整案例走查（2026-08-28..31 四日窗口，真实运行实值）

1. **窗口总览**（库内实值）：**173 任务全 done（4 bora_fecha + 5 bora_seccion〔28 日 1 页 + 探测页、29/30 日各 1 页、31 日 1 页 + 探测页〕+ 121 bora_detalle + 43 bora_anexo）、0 失败 0 升级 0 空告警；121 文档、163 文件、游标 `bora_last_date=2026-08-31`**。
2. **逐日**：08-28（周五）43 条入账；08-29（周六）+ 08-30（周日）无刊——分部页重定向到主页，判型后记合法空、游标照推；08-31（周一）78 条入账。
3. **一条总统令**：`GET /detalleAviso/primera/346512/20260828` → 61,558 字节。标题块：机关 `PODER EJECUTIVO`、引用 `Decreto 817/2026`、标识 `DECTO-2026-817-APN-PTE - Dispónese Intervención. Designación.`；正文全文内联（签署日 2026-08-27，COVIARA 军方住房建设公司干预令）；刊出日 28/08/2026；公报页 4–6。→ doc_type `DECREE`，文件 `01_raw/bora/2026/D20260828/346512/detalle.html`。
4. **一条带附件的决议**：Jefe de Gabinete 的 `Resolución 247/2026`（标识 `RESOL-2026-247-APN-SCLYA#JGM`），页面自带 2 个附件（附件 id 7752776，序号 1 与 2）→ 2 个 `bora_anexo` 任务各取回一份 PDF（97,475 字节，实测 GET 与 POST 同为 130,353 字节 JSON 内 base64）。
5. **多附件规模**：同窗另有一条 12 附件的条目（附件 id 7756488 ×12）——全部落盘，meta 预声明 12 个文件名逐一对上。
6. **扫描壳样本**（早年）：`GET /detalleAviso/primera/7147902/19950104` → 989,836 字节——无正文块，页面内嵌整份扫描 PDF（base64）提取为 `aviso.pdf`；1940-01-02 的列表亦实测可达（62 条）。
7. **对账**（2026-09-03）：①**通道对账**——账本逐日 ID 集合 ≡ 分部页独立走查（08-28：43 条同 ID；08-31：78 条同 ID）；②**三方对账**——磁盘文件 ≡ 账本 file_hash/字节数（121/121 逐一相同），附件盘上 42 = meta 预声明 42；③**源站字节**——直连重取与磁盘存在 ±3 字节差：页面装饰件（版头日期显示、日历脚本变量）按**取页时的会话日期**渲染，正文内容逐字节稳定——属"源站字节不稳定"的已预期情形（账本 file_hash 为落盘字节校验和）。
8. **幂等**：同窗口重跑 0 种子 0 请求（游标钳制 + 任务确定性身份）；`sync=1` 从游标次日续链。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country arg --source bora window=2026-08-28:2026-08-31 --dry-run

# 小窗口真实抓取（§5 的四日窗口；Windows 系统代理在位时须设 NO_PROXY 直连，见 §2）
NO_PROXY=www.boletinoficial.gob.ar python cli.py collect --country arg --source bora window=2026-08-28:2026-08-31 --delay 1.5:3

# 每日增量（从上次游标的次日追到昨天）
NO_PROXY=www.boletinoficial.gob.ar python cli.py collect --country arg --source bora sync=1 --delay 1.5:3

# 状态 / 快照 / 修复
python cli.py status --country arg --source bora
python cli.py export --country arg
python cli.py requeue --country arg
```

## 7. 更新与增量

- **游标**：`bora_last_date`。一个 `bora_seccion` 链完整消费自己那一天（翻页片段答 `hay_mas_datos=false`，或无刊日主页判型通过）才把游标推到该日；中途崩溃该日不推，下次自愈（运行戳保证设日期请求重放）。
- **播种链纪律**：种子只播游标之后的首日，其余日子由链登记（§3）——服务端会话同一时刻只激活一天，任务依赖保证顺序；页 1 的 `fechaSeleccionadaYMD` 自证与逐行日期校验为第二、三道保险。
- **sync 终点取昨天、不取今天**：当日版晨间出刊（2026-09-02 实测当日门户已是当日版），但"尚未生成"与"当日无刊"在分部页上同形（都重定向主页）——为杜绝误判，增量默认只到昨天。确需当天数据：显式跑 `window=…:今天` 并自行承担时点风险。
- **重刷旧窗口**：游标已覆盖的窗口不产生种子（游标 = "已确认消费到"水位线）；确需重抓走修复通道（requeue/reset），不是重扫。
- 公报刊出即定，同窗口重复运行安全（任务确定性去重）。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **检索端点有索引窟窿** | 站内高级检索漏收机关公告类条目（2026-08-28..31 窗实测 8/121，宽窗检索亦不可见）——只作对账工具，不作采集通道（§1.3） |
| **页面装饰随会话日期漂移** | 详情页版头日期与日历脚本按取页时会话渲染，直连重取与落盘字节有 ±3 字节差；正文内容稳定，账本哈希以落盘字节为准（§5.7③） |
| **特刊（suplemento）不抓** | 特刊是独立 PDF（挂 CDN：`s3.arsat.com.ar/cdn-bo-001/suplementos/…`），其条目不进常规列表（2026-08-14 特刊日实测：常规列表 17 条 + 版头"下载特刊"直链）。当年特刊日清单在门户首页脚本里（2026 年至 9 月共 8 天）。特刊多载付费公告；DNU 70/2023 实测为常规条目不受影响。将来需要时按 CDN URL 模式直构补抓 |
| **无结构化制定日/生效日** | 日期只有刊出日是结构化字段；签署日在正文文本、登记行在正文尾（§4 说明），结构化抽取留清洗阶段 |
| **扫描壳年代** | 早年条目（实测 1940/1950/1975/1995）正文无文本，唯一内容是页面内嵌的扫描 PDF——已按形状自动分支提取，但文本可得性以此边界为准（现代/扫描的精确年代分界未逐年探明，按页面形状而非年份判断） |
| **只收第一部** | 第二部人事（robots 禁抓）、第三部采购、第四部 .ar 域名公告均不在目标内 |
| **服务器偏慢** | 中位 4.7 秒/请求；全量回填（1940 年至今约 21,500 个出刊日、百万级条目请求）的排期须按此节奏估时 |
| **海外访问** | 国家门户对境外直连友好（本表全部实测自境外直连）；**本机系统代理出境路径会被掐 TLS**（§2 代理行）。省级公报的访问情况完全不同，见 [overview-zh.md](./overview-zh.md) §3 |

## 9. 端点速查表

**在用**：

| 用途 | URL 模式 |
|---|---|
| 设日期（枚举链头） | `GET https://www.boletinoficial.gob.ar/edicion/actualizar/{DD-MM-YYYY}`（须带 `X-Requested-With: XMLHttpRequest`；把日期写进服务端会话） |
| 当日列表页 1 | `GET https://www.boletinoficial.gob.ar/seccion/primera`（读会话日期；页面内嵌 `fechaSeleccionadaYMD` 自证；无刊日重定向主页） |
| 列表翻页 | `GET https://www.boletinoficial.gob.ar/seccion/actualizar/primera?pag={N}&ult_rubro={上页末类目}`（JSON 片段，`hay_mas_datos=false` 即日完成） |
| 条目详情 | `GET https://www.boletinoficial.gob.ar/detalleAviso/{部}/{条目id}/{YYYYMMDD}` |
| 附件 PDF | `GET https://www.boletinoficial.gob.ar/pdf/download_anexo?seccion=…&nroAnexo=…&idAnexo=…&fechaPublicacion=YYYYMMDD` |

**已确认存在、本源未用**（各自一句话研究价值）：

| 端点 | 价值 |
|---|---|
| `GET /busquedaAvanzada/realizarBusqueda?params={JSON}` | 站内高级检索（**有索引窟窿**，§1.3）——交叉对账工具；也是"提前入库的未来条目"的观察窗 |
| `GET /calendario/dias_publicacion/{年}/{部}` | 官方出版日历（1940–2026 各年实测应答，每年约 250–280 天）——出刊日的权威清单，可用于排期与无刊日交叉核对 |
| `GET /busquedaAvanzada/{部}/rubros` | 部内类目官方词表（primera 25 项）——跨国类型学对齐时的权威对照 |
| `GET /pdf/aviso/{部}/{条目id}/{YYYYMMDD}` | 逐条目印刷版 PDF 直链（现代年代，免会话）——将来需要印刷版式时按 URL 直构补抓 |
| `POST /pdf/download_section`（会话日期绑定） | 整期分部 PDF（base64 JSON，2 MB 级）——整期存档用 |
| `s3.arsat.com.ar/cdn-bo-001/suplementos/{年}/{月}/{日}/primera-seccion_{日-月-年}_suplemento-{序号}.pdf` | 特刊 PDF 直链（§8 缺口补抓用） |
| `GET /web/utils/pdfView?file=…` | 站内 PDF 查看器壳——采集不需要 |

**第一部类目词表**（官方 25 项，2026-09-02 自词表端点提取；源站数据的两处拼写瑕疵原样保留）：ACORDADAS / ASOCIACIONES SINDICALES / AUDIENCIAS PÚBLICAS / AVISOS OFICIALES / CON?CURSOS OFICIALES（源站破损重名）/ CONCURSOS OFICIALES / CONVENCIONES COLECTIVAS DE TRABAJO / DECISIONES ADMINISTRATIVAS / DECRETOS / DECRETOS DESCLASIFICADOS / DISPOSICIONES / DISPOSICIONES CONJUNTAS / DISPOSICIONES SINTETIZADAS / FALLOS / INSTRUCCIONES PRESIDENCIALES / INTRUCCIONES GENERALES（源站拼写）/ LEGISLACION / LEYES / REMATES OFICIALES / RESOLUCIONES / RESOLUCIONES CONJUNTAS / RESOLUCIONES GENERALES / RESOLUCIONES SINTETIZADAS / SENTENCIAS / TRATADOS Y CONVENIOS INTERNACIONALES。

---

*更新日期：2026-09-03；数据快照：2026-09-03；数据由 window=2026-08-28:2026-08-31 实跑背书（173 任务零失败 / 121 文档 163 文件 / 通道 ID 对账 + 磁盘≡账本逐字节一致 / 幂等重跑零请求）。*
