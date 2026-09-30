# 智利(CHL)数据源说明——leychile(Ley Chile 法律数据库)

> 文中数量为真实运行的实测参考值;你运行时的产出取决于所选窗口。
> 阅读前提:了解仓库根目录 `python cli.py` 的用法即可,不需要读代码。

## 1. 源概览

### 1.1 制度背景:Ley Chile

**Ley Chile**([leychile.cl](https://www.leychile.cl) / [www.bcn.cl/leychile](https://www.bcn.cl/leychile))是智利**国会图书馆(Biblioteca del Congreso Nacional de Chile,BCN)** 运营的官方法律数据库,收录 1850 年至今智利全部规范性文件:宪法、法律(Ley)、准法律政令(Decreto Ley / Decreto con Fuerza de Ley)、政令(Decreto)、决议(Resolución)、通告(Circular)、自治规则(Auto Acordado)、条约等。全库 **415,344 部**(2026-09-20 实测接口计数)。

三个关键覆盖性质(均经接口实证,2026-09-20):

- **深历史**:年覆盖 1850:1 部 → 1900:105 部 → 1950:152 部 → 1990:5,188 部 → 2010:11,525 部 → 2024:9,348 部,19 世纪中叶起连续;
- **含已废止**:默认检索不过滤废止状态(2010 年窗 11,525 部中 430 部已废止,行级废止日期字段可辨);
- **版本化**:每部法规按修订版本管理,历史版本全文可取(见第 3 节)。

每部法规的元数据自带**公报出处**(`fuente='Diario Oficial'` + 期号 `numero_fuente`),可与官方公报对账。

### 1.2 技术形态:纯 JSON 接口

网页是动态界面,但背后是**三个免 key 的 JSON 查询接口**(无 cookie、无令牌、无浏览器需求;2026-09-20 实证,默认 HTTP 会话直连即通)。接口按法规(norma)组织:一部法规一个稳定身份 `idNorma`,每次修订产生一个新**版本**,版本身份 = `(idNorma, 有效期起始日 vigenteDesde)`。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**,`.env` 零条目 |
| 会话 | **不需要**——无 cookie 依赖 |
| 限额 | 未观察到(10 连发无拦截);保持默认礼貌间隔 |
| 反爬 | 仅 User-Agent 黑名单(如屏蔽 curl 默认标识);本仓库 HTTP 层默认浏览器标识天然通过,无需任何配置 |
| 响应格式 | 全部 UTF-8 JSON |
| 注意 | 年份过滤只接受年粒度(如 `2024 TO 2024`);日期粒度会得到服务器 500;`TO` 两侧的空格按查询串编码习惯送出即可 |

## 3. 抓什么:任务类型清单(3 种)

**一部法规一条完整生命周期**:名录发现 → 最新版全文 → (被修订过的法规)全部历史版本。

```
chl_list(年, 页) ──每行──> normas 实体表(登记行:名称/类型/四类日期/机构)
    └──每部法规──> chl_body(锚点 = 最新版全文)
                       ├─> documents 一行 + 原始 JSON 落盘
                       └─(曾被修订的法规)──> chl_versions(版本时间线)
                                               ├─> norma_versions 表(版本行 + 修订链原始字段)
                                               └──每个历史版本──> chl_body(历史版全文)
```

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `chl_list`(种子) | 名录接口 `buscarjson`,某年一页(50 行) | **全部 50 行入 `normas` 实体表**(登记不依赖后续深抓);每行派生一个锚点 `chl_body`;满页自动续抓下一页,空页自动停;`max_normas` 可限制每页深抓数(试跑护栏) |
| `chl_body` | 正文接口 `get_norma_json`,一部法规的一个版本 | 该版本全文 + 31 字段元数据 → documents 一行(挂靠 `normas:{idNorma}`)+ API 响应原字节落盘;锚点若来自"曾被修订"的行,派生 `chl_versions` |
| `chl_versions` | 时间线接口 `get_versiones` | 该法规**全部版本清单**(原文版 / 中间版×N / 最新版,各带有效期区间与**修订链**:哪部法规在何时修订了它)整组写入 `norma_versions`;每个历史版本派生 `chl_body` |

**单版法规的省略**:名录行自带版本类型标记——`Única`(单版,从未被修订)的法规**不发**时间线请求(实测时间线恒单条、无信息增量;2024 年一页 50 部中 47 部属此类),只抓其唯一版本全文;`Última Versión`(已被修订)的法规走完整版本链。

命令行参数(key=value):

```
years=2024 | 1990,2010 | 1850-2026 | all   必填:年窗(all = 1850 至当年,每年一个种子)
pages=1-2      选填:限每年的名录页数(缺省 = 该年全部页)
max_normas=5   选填:每页深抓法规数上限(试跑护栏;只限深抓,不限登记)
refresh=2026-09-21T09:00   选填:增量重跑,ISO 时间戳,详见第 7 节
```

## 4. 数据落到哪

**两张领域表 + documents 表 + 每部法规一个文件夹**:

| 位置 | 记什么 |
|---|---|
| `normas` 表 | 一部法规一行:`id_norma` 主键(修订不变的身份)、名称、标题、类型、发布机构、号码、制定日/公布日/废止日(ISO)、当前锚点指针(最新版有效期起)、版本类型标记 |
| `norma_versions` 表 | 一部法规一组版本行:`(id_norma, vigente_desde)` 主键、版本类型(原文版/中间版/最新版/单版)、有效期区间、**修订链原始 JSON**(哪部法规、何法、何时修订) |
| `documents` 表 | 一个版本一份全文文档,`entity_ref='normas:{id_norma}'` 挂靠所属法规 |
| `01_raw/leychile/{id 前 2 位}/{id_norma}/` | 该法规的全部版本材料(API 响应原字节,人读镜像,路径入账) |

documents 主要字段(版本全文文档):

| 列 | 值 |
|---|---|
| `title` | 法规标题(元数据 `titulo_norma`,空时回退类型+号码) |
| `publication_date` | 法规**公布日**(元数据 ISO 日期;同一法规各版本同日) |
| `source_url` | `https://www.bcn.cl/leychile/navegar?idNorma={id}&idVersion={有效期起}`(可重建的规范形式) |
| `doc_type` | 按类型缩写映射的受控值(见下);原生缩写整段存 `meta.type_abbr` |
| `meta` | `vigente_desde/hasta`(版本有效期)、`tipo_version`、`fecha_promulgacion`、`numero_fuente` 公报期号、`fuente`、`organismos`、`derogado`、`from_versions`(历史版标记)等 |

**类型映射**(原生缩写 → 受控值;原生值永存 meta):CTR 宪法→`CONSTITUTION`;LEY 法律 / DL 准法律政令 / COD 法典→`STATUTE`;DFL 授权政令 / DTO 政令→`DECREE`;RES 决议 / CIR 通告 / INS 指示→`SECONDARY_LEGISLATION`;AA 法院自治规则→`RULE`;其余→`OTHER`。

文件夹布局(真实示例):

```
01_raw/leychile/
└── 29/29708/                          ← 交通法 Ley 18290(1984,37 个版本)
    ├── norma_29708_2009-11-07.json    ← 最新版(2009 年最后一次修订后)
    ├── norma_29708_2005-03-12.json    ← 中间版(2005 年修订后)
    └── norma_29708_1985-01-01.json    ← 原文版(1984 年公布)
```

## 5. 完整案例走查:Resolución 78 EXENTA(2024,一部法规从名录到版本链)

以 2026-09-20 的小窗口实跑为例(`years=2024 pages=1 max_normas=4`):名录 2024 年窗第 1 页第 4 行是一部**已被修订**的法规——能源部第 78 号豁免决议(电价补贴分配)。全程四步,每个数字可从 state.db 复查:

1. **名录登记**:`chl_list` 抓回该页 50 行,每行各落一行 `normas`——本法规那行为:`id_norma=1209820`、名称 `Resolución 78 EXENTA`、类型缩写 `RES`(受控值 `SECONDARY_LEGISLATION`)、机构 `MINISTERIO DE ENERGÍA`、制定日 `2024-12-27`、公布日 `2024-12-31`(名录行原文是西语式 `31-DIC-2024`,入库时转 ISO)、当前锚点 `2025-01-06`、版本标记 `2`(已被修订);
2. **锚点全文**:`chl_body` 按锚点取最新版全文 → documents 一行 `CHL_20241231_e570e30d`(38,843 字节,公报期号 44037),文件落 `01_raw/leychile/12/1209820/norma_1209820_2025-01-06.json`;
3. **版本时间线**:因行标记"已被修订",锚点派生 `chl_versions` → 该法规共 **2 个版本**整组写入 `norma_versions`——最新版 `2025-01-06` 起(有效期开放)与原文版 `2024-12-31` 至 `2025-01-05`;原文版那行带 1 条修订链记录(2025 年第 6 号决议修改了它,原始 JSON 无损保存);
4. **历史版全文**:时间线为原文版派生 `chl_body` → documents 再一行 `CHL_20241231_67500d2f`(38,780 字节,同公布日、不同版本日期),文件与最新版同文件夹(`norma_1209820_2024-12-31.json`)。

**这部法规最终入库:1 行 normas + 2 行 norma_versions + 2 行 documents(全部挂靠 `normas:1209820`)**。把同一最新版从站点重新请求一次,响应与磁盘文件**逐字节一致**(38,843 字节,2026-09-20 对照);对整个窗口重跑同一命令,已完成的任务全部跳过、零请求重发;带 `refresh` 时间戳重跑,仅重读名录页、正文零重抓——增量语义实测成立。

同窗口其余产出:3 部 2024 年单版政令(3,755 / 4,098 / 4,240 字节)与 1990 年对照窗 2 部(法律 13,378 字节 + 政令 27,178 字节),合计 **100 行 normas 登记、7 份文档、11 个任务零失败**(2026-09-20 实跑)。

## 6. 怎么跑

```bash
# 演练(不抓任何东西,看会入队什么)
python cli.py collect --country chl --source leychile years=2024 pages=1 max_normas=3 --dry-run

# 小窗口全链(2024 年名录第 1 页、前 3 部法规的全文与版本链)
python cli.py collect --country chl --source leychile years=2024 pages=1 max_normas=3

# 某年全量(该年全部名录页 + 每部法规全链;2024 年 = 9,348 部)
python cli.py collect --country chl --source leychile years=2024

# 全库回填(1850 至当年;约 8,300 名录页 + 42 万级正文请求,建议分年分批)
python cli.py collect --country chl --source leychile years=all

# 增量重跑(只重读名录页,已入库内容零重抓;详见第 7 节)
python cli.py collect --country chl --source leychile years=2026 refresh=2026-09-21T09:00

# 状态 / 快照 / 修复
python cli.py status --country chl --source leychile
python cli.py export --country chl
python cli.py requeue --country chl        # 失败任务复位
```

## 7. 更新与增量

- **重跑安全**:任务身份确定性去重——重复运行同一命令,已完成部分直接跳过,近零成本;
- **增量 = refresh 重走名录**:`refresh=<比上次新的 ISO 时间戳>` 让已完成的名录页重开重读(每页一次请求),已完成的正文/时间线任务直接跳过。新公布的法规 = 名录新行 → 新任务;被修订的法规 = 行的"当前版本有效期"变化 → 新任务身份 → 新版本入库、版本时间线整组重写,`normas` 登记行随之更新;
- **版本谱系完整性**:每个"曾被修订"的法规自动回溯全部历史版本(原文版 + 每次修订后的中间版),新旧版本自动成链;
- **发现边界**:已废止法规默认在名录中(2026-09-20 实证),无需额外的废止发现层;唯一的边界是年份粒度——增量最小单位是"某年的全部名录页"(约当年 200 页)。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| 官方公报(Diario Oficial)原生流 | leychile 收录其规范性内容并带公报期号字段,但公报中的非规范性内容(人事任命、公告性通告等)与逐日原件不在其中——需要公报作为独立源 |
| 议会立法过程 | 法案(Proyecto de Ley)与审议记录不在本源;站点另有过程类接口(已探明:historias de ley、proyectos de ley),属后续源 |
| 市政法规 | 各市条例在另一登记系统,不在 Ley Chile |
| 多语言译本 | 站点部分提供英语等译本,未接入 |
| 年粒度过滤 | 接口只接受年份窗口;无按日窗口(日期粒度返回服务器 500,2026-09-20 实证) |
| 版本内嵌套(极少) | 个别法规存在条文级分节(doble articulado),按整版本快照收录,不拆条 |

## 9. 端点速查表

均在 `https://nuevo.leychile.cl/servicios/` 下(全部 GET、UTF-8 JSON、免 key;2026-09-20 实证):

| 用途 | 端点与参数 |
|---|---|
| 名录检索(50/页) | `buscarjson?itemsporpagina=50&npagina={N}&tipoviene=1&fc_de=&fc_ra=&seleccionado=0&fc_rp=&totalitems=&orden=2&fc_pb={YYYY}+TO+{YYYY}&fc_pr=&exacta=0&cadena=&fc_tn=` → `[行列表, 回显+totalitems, 分面计数]`;行字段:`IDNORMA`/`ID_VERSION`/`TIPOVERSION`(2=最新版 3=单版)/`FECHA_VIGENCIA`(=最新版有效期起)/`FECHA_PUBLICACION`(西语式日期)/`FECHA_PROMULGACION`(ISO)/`FECHA_DEROGACION`/`ABREVIACION`/`ORGANISMO` 等 |
| 版本全文+元数据 | `Navegar/get_norma_json?idNorma={id}&idVersion={有效期日期或版本号}&idLey=&tipoVersion={1\|2\|3\|空}&cve=&agrupa_partes=1&r=` → `metadatos`(31 字段)/`html`(正文片段数组)/`estructura`(结构索引) |
| 版本时间线 | `Consulta/get_versiones?idNorma={id}&formato=json&idParte=` → 每版 `tipoVersion`/`vigenteDesde`/`vigenteHasta` + `Modificatorias`(修订链:修订方类型/号码/公布日/生效日/机构) |
| 类型词表(未入管线) | `Consulta/getTiposNorma` → 全部法规类型(cod/abbr/valor) |
| 过程类(未启用,后续源) | `Navegar/get_historias_de_ley?idNorma=`、`Navegar/get_proyectos_de_ley?idNorma=`、`Consulta/getProyectosLey?idNorma=` |
| 版本对照(未启用) | `Navegar/get_textos_comparar_versiones?idNorma=&version1=&version2=&idParte=&idParte2=` |
| 整合关系(未启用) | `Consulta/getRefundidas?idNorma=`、`Navegar/get_cadena_refundidos?idNorma=`(refundición = 多法整合为一) |

**公开规范页**(source_url 基础):`https://www.bcn.cl/leychile/navegar?idNorma={id}&idVersion={YYYY-MM-DD}`。

---

*更新日期:2026-09-20;数据快照:2026-09-20;数据由 2026-09-20 小窗口实跑背书(2024 年窗首页 4 部 + 1990 年窗首页 2 部:11 任务零失败、7 文档三方逐字节一致、refresh 增量实测零重抓)。*
