# 土耳其（TUR）数据源说明——mevzuat（法规信息系统 MBS）

> 数据快照日期：2026-09-27。文中实体计数、字节数与状态码均为当日对源站直连实测的真实值（可重放复核）；账本内计数在首次真实运行后补记（§5 末行）。
> 阅读前提：了解 `python cli.py` 用法即可，不需要读代码。土耳其全部源总览见 [overview-zh.md](./overview-zh.md)。

## 1. 源概览

### 1.1 制度背景：MBS 是什么、与公报的分工

**Mevzuat Bilgi Sistemi**（法规信息系统，简称 **MBS**；mevzuat 为土耳其语"法规/规范体系"之意）是土耳其的**整编现行法规库**，网址 www.mevzuat.gov.tr，1995-06-01 上线（2003-07-29 起免费，后取消注册制），由**总统府总秘书处法务与立法总局**运营。设立依据：Cumhurbaşkanlığı Kararnamesi No. 10 与《Resmî Gazete Hakkında Yönetmelik》（关于官方公报的规章）——职责为"将公报公布的法律、总统令、规章、通告及其他规性行政行为**整编为单一文本并保持现行**"。

**"整编"（kodifiye，即 codification/合并编纂）释义**：把一部法规的历次修正案并入原文，维护一份**现行有效版的单一合并文本**。例：宪法（Kanun No. 2709）1982-10-18 通过、其后多次修宪，MBS 库里存的是合并后的最新版全文（2026-09-27 实取 668,119 字节），各修正处标 `[1] [2]` 脚注、页脚列来源修宪法号。**它与公报存的是两种口径**：公报答"当年公布的是什么"（as-published 原文，见 [resmigazete-zh.md](./resmigazete-zh.md)），MBS 答"现在有效的是什么"。整编底本为 1985–1988 年委员会建立的 Mevzuat Külliyatı（法规汇编：11,200 部共和国时期法律 + 仍在施行的奥斯曼时期法令 + 244 部 KHK + 1,060 部规程 + 1,230 部规章）。

**收录范围**（分类型，2026-09-27 名录接口逐类计数）。**为什么大学与机构的规章算政策性文件、默认全收**：土耳其宪法第 124 条授权部长会议、各部及"具有公法人资格的机构"制定 Yönetmelik，第 130 条明定**大学是公法人**——大学与部委出自同一宪法授权条款；3011 号法律（1984）要求**一切规章必须在官方公报公布**（公报不登纯内部文件，判据是对外一般效力——大学考试/学籍/纪律规章约束的是学生，机构规章约束被监管方）。本库默认按通道完整性全收（含大学规章），语义筛选（"算不算政策声明"）属研究端判断，按类型码过滤即可、零损失：

| 类型码 | 土耳其语名 | 中文 | 条数 |
|---|---|---|---|
| 1 | Kanun | 法律（现行） | 916 |
| 2 | Tüzük | 规程（依法律授权由部长会议制定的行政法规） | 107 |
| 4 | KHK（Kanun Hükmünde Kararname） | 法律效力令 | 63 |
| 5 | Mülga Kanun | **已废止的法律**（废止库） | 185 |
| 9 | Tebliğ | 通告（部委通知性规范文件） | 4,476 |
| 19 | Cumhurbaşkanlığı Kararnamesi | 总统令 | 33 |
| 20 | Cumhurbaşkanı Kararı | 总统决定 | 4,321 |
| 21 | Cumhurbaşkanlığı Yönetmeliği | 总统府规章 | 179 |
| 3 | Yönetmelik | 规章/实施细则（合计） | 8,843 |
| 7 / 8 / 10 | （Yönetmelik 的三个发布者子类） | 机构与组织规章 3,657 / 大学规章 5,038 / 部长会议规章 148（三者和 = 8,843，实测加和相等，与类型 3 同一集合） | — |
| 其余（0 奥斯曼旧法 / 6 / 16 / 17 / 18） | 边角类型 | 全库合计 ≈ 19,095 实体 | — |

**实体身份 = 三元组 `(MevzuatTur, MevzuatNo, MevzuatTertip)`**：类型码 + 编号 + 卷次代。编号两种形态：法律/总统令为序列号（2709 = 宪法），规章为日期式（"201811296" = 2018 年第 11296 号）。**Tertip**（卷次代）源自土耳其传统的 **Düstür**（法规汇编卷册）：第 3 代 ≈ 1960 年前后时期、第 5 代 = 现行时期（1982 起）——同一编号在不同卷次代是不同文本，故身份必须含 tertip。

**不在本源里的东西**：公布原件（公报职责）、版本历史时间线（MBS 只存现行合并文本 + 废止标记，**无原生版本谱系**——历史各版需回公报取）、议会过程、地方法规。

### 1.2 数据通道：站内数据接口（免 key、无会话、无浏览器）

**① 名录接口（枚举的唯一入口）**：

```
POST https://www.mevzuat.gov.tr/anasayfa/MevzuatDatatable
Content-Type: application/json; charset=utf-8
```

请求体 = DataTables 风格信封（`draw/columns/order/start/length/search`）+ `parameters` 对象（PascalCase）：`AranacakIfade`（检索词，空 = 全列）、`AranacakYer`（检索位置，1 = 全部）、`TamCumle`（整句匹配，false）、`MevzuatTur`（类型码）、`GenelArama`（false）。`start/length` 分页（length=100 实测稳定；返回按编号降序）。每记录字段：`mevzuatNo`、`mevAdi`（标题）、**`kabulTarih`（通过日）**、`resmiGazeteTarihi`（公报日）、`resmiGazeteSayisi`（公报期号）、`mevzuatTertip`、`mukerrer`、`mevzuatTur`、`url`（详情页相对地址）、`hasDoc` 等。

**② 整编正文（文本型实体的文档本体，一次请求 = 元数据 + 全文）**：

```
GET https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur={t}&MevzuatNo={n}&MevzuatTertip={r}
```

详情页把整编正文放在一个 **iframe**（网页内嵌框架）里加载，直接请求该框架 URL 即得完整正文 HTML。响应结构：顶部元数据块（法规号 / 通过日〔规章为批准决定日+号〕/ 公报日期+期号〔含 Mükerrer 注记〕/ Düstür 卷次代+卷+页 / 规章的**依据法律** dayandığı kanun）+ 全文（条文 MADDE 逐条、脚注式修正注记）。实例：宪法 668,119 字节；一部规章 63,809 字节（2026-09-27 实测）。

**元数据块的五种方言**（2026-09-28 逐型实测，标签拼写随文书族变化）：法律/废止法律（`Kanun Numarası`/`Kabul Tarihi`/`Sayı:`，废止法开头一句"Bu Kanun … yürürlükten kaldırılmıştır"点名废止它的法律）；规程/规章族（`Bakanlar Kurulu Kararının Tarihi … No :`/`Dayandığı Kanunun`/`Cildi`）；KHK（`Kanun Hükmünde Kararnamenin Tarihi`/`Yetki Kanununun` 授权法/Mükerrer 可带序号"(3. Mükerrer)"）；总统令（`Cumhurbaşkanlığı Kararnamesinin Sayısı`/公报行连字符式"`Tarihi - Sayısı : 8/1/2025 - 32776`"）；通告（**全无头部块**，编号在标题里"(TEBLİĞ NO: 2026/29)"，日期全靠名录行）。解析对五式全容、对未知形状响亮失败。

**③ 文件端点（仅文件型实体的文档本体）**：`GET /MevzuatMetin/{t}.{r}.{n}.pdf`。名录行的 fileType 字段是结构判别：**fileType=1 = 有 iframe 文本；fileType=2 = 详情页无 iframe、PDF 是唯一正文**（CB Kararı 类整类如此，2026-09-28 实测：iframe 端点返回空页，详情页只挂 pdf/doc 直链）。注意假页陷阱（§2）。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **不需要**，`.env` 无需任何条目（站点有登录/收藏功能，均与数据读取无关） |
| 会话 | 无（名录 POST 与正文 GET 均裸直连实测；页面表单里的防伪令牌字段对数据接口不生效——2026-09-27 无 cookie 无令牌请求实证） |
| 请求头 | 名录请求须 `Content-Type: application/json`；普通浏览器 User-Agent |
| 限额 | 无公开限额；站内脚本有客户端节流（连续搜索需间隔数秒），服务端未见限制。框架统一限速（0.5–1 秒/请求）足够安全 |
| 反爬 | 无 |
| 响应格式 | 名录 JSON；正文 HTML（UTF-8） |
| **假页警告** | `MevzuatMetin/{t}.{r}.{n}.pdf` 等文件端点对不存在的编号返回 **HTTP 200 + HTML 错误页**（非 404，2026-09-27 实测）——任何文件下载必须校验响应类别/魔数，本源因此不采文件（§8） |
| robots | 只含 Noindex 提示，无 Disallow（2026-09-27 实测） |

## 3. 抓什么：任务类型清单

每种任务 = 一次下载 + 一次解析。共 **3 种**：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `mev_list`（种子，类型 × 页） | POST 名录接口（§1.2 ①） | 每记录 upsert 一行 `mevzuat` 实体表（§4）+ 每实体生成一个正文种子——**文本型记录（fileType=1）→ `mev_metin`；仅文件型记录（fileType=2，详情页无 iframe 正文，PDF 是唯一文本）→ `mev_pdf`**（2026-09-28 实跑发现：整个 CB Kararı 类即此形态）；未到尾页生成 `mev_list(同类型, 下一页)`；返回的 recordsTotal 与累计条数对不上 → 响亮失败 |
| `mev_metin`（逐文本型实体一个） | GET 整编正文框架（§1.2 ②） | 响应字节原样落盘为 `metin.html` 主文件；从顶部元数据块解析法规号/通过日/公报期号/Düstur 卷次补齐实体行；一个文档记录入账（entity_ref 挂靠实体） |
| `mev_pdf`（逐仅文件型实体一个） | GET `/MevzuatMetin/{t}.{r}.{n}.pdf` | 响应字节原样落盘为 `metin.pdf` 主文件；书目字段全部来自名录种子（PDF 无机读头部）；**魔数校验强制**（该端点对不存在的编号返回 200+HTML 假页，2026-09-27 实测） |

任务链：`mev_list × 每类型每页 → mev_metin / mev_pdf × 每实体`。

命令行参数（key=value 形式）：

```
turs=1,2,3,4,5,9,19,20,21   收哪些类型码（默认 = 立法核心类 + 全部规章；逗号分隔，见 §1.1 表）
pages=N                     每类型最多抓多少页（试跑限量；默认不限）
refresh=2026-10-01T09:00:00 参数化重开：带新时间戳重走全部名录页（§7）
```

## 4. 数据落到哪

**一张领域表 `mevzuat`**（实体登记库，同韩国 laws 先例——一部法规是跨文档持久实体：名录行、整编正文、将来的文件都挂同一身份；"法规退役"〔转入废止库〕也是实体状态）：

```sql
CREATE TABLE mevzuat (
  mevzuat_tur     INTEGER NOT NULL,   -- 类型码（§1.1 表）
  mevzuat_no      TEXT    NOT NULL,   -- 序列号或日期式编号（"2709" / "201811296"）
  mevzuat_tertip  INTEGER NOT NULL,   -- Düstür 卷次代（3 / 5）
  mevzuat_adi     TEXT,               -- 原生标题
  kabul_tarihi    TEXT,               -- 通过日（ISO）
  rg_tarihi       TEXT,               -- 公布日（ISO）
  rg_sayisi       TEXT,               -- 公报期号
  mukerrer        TEXT,               -- 同日增刊注记（源生值）
  PRIMARY KEY (mevzuat_tur, mevzuat_no, mevzuat_tertip)
);
```

`documents` 表承担文档本体（每实体一个文档 = 整编正文）：

| 列 | 内容 |
|---|---|
| `doc_id` | `TUR_{公报日YYYYMMDD}_{hash8(source_url)}`（公报日缺失回退通过日，再缺 00000000） |
| `title` | mevAdi 原生标题（正文化标题以正文元数据块为准） |
| `publication_date` | 公布日（名录记录的 resmiGazeteTarihi） |
| `issuing_authority` | 规章类可从正文元数据块的批准机关行取得；法律类无独立字段（机关 = 立法机关），留空 |
| `source_url` | `https://www.mevzuat.gov.tr/mevzuat?MevzuatNo={n}&MevzuatTur={t}&MevzuatTertip={r}`（详情页规范 URL，参数序固定；正文框架 URL 为内部地址，不作文档身份） |
| `raw_format` / `language` | `html` / `tur` |
| `doc_type` | 类型码映射（下表）；土耳其语原词永存 meta |
| `entity_ref` | `mevzuat:{tur}:{no}:{tertip}` |
| `meta` | 见下 |

**meta 字段**：`mevzuat_tur/mevzuat_tertip`、`kanun_no`（法律号）/`kararname_no`（总统令号）/`karar_no`（批准决定号，如 2018/11296）、`kabul_tarihi`（通过/批准日）、`rg_sayisi`（公报期号）、`mukerrer`（EVET，含序号注记）、`dustur_tertip/cilt/sayfa`（Düstür 卷次代/卷/页）、`dayandigi_kanun_tarihi/no`（依据/授权法律，KHK 取第一组）、`yururlukten_kaldirildi`（废止法前言原句——点名废止它的法律，政策终止研究的原生字段）、`pdf_url` / `doc_url`（规范地址）、`text_channel`（html/file，仅文件型实体带）。

**doc_type 映射**（原生优先）：

| 类型 | doc_type |
|---|---|
| 1 Kanun / 0 奥斯曼旧法 | STATUTE |
| 4 KHK / 19 总统令 / 20 总统决定 / 18 BKK | DECREE |
| 2 Tüzük / 3、7、8、10、21 Yönetmelik 族 | REGULATION |
| 9 Tebliğ | ORDER |
| 其余 | OTHER |

文件落点（一实体一夹，类型码分层）：

```
{data_root}/TUR_policy/
└── 01_raw/mevzuat/
    ├── 1/                      ← 类型码
    │   └── 2709/
    │       └── metin.html      ← 整编正文原样字节（文档主文件）
    ├── 3/
│   └── 201811296/
│       └── metin.html
└── 20/                        ← 仅文件型实体（fileType=2）
    └── 11804/
        └── metin.pdf          ← PDF 即唯一正文
```

## 5. 完整案例走查（宪法与一部规章，源站直连实值）

1. **名录页**：`POST /anasayfa/MevzuatDatatable`（MevzuatTur=1, start=0, length=10）→ 200，首记录 = Kanun 7595（Millî Dayanışma ve Toplumsal Bütünleşmenin Güçlendirilmesine Dair Kanun，通过 10.08.2026，公报 18.08.2026 第 33344 期，tertip 5）。翻页 start=100 → 200，100 条（降序至 Kanun 6735），recordsTotal=916 与分页一致（2026-09-27 复核）。
2. **整编正文**：`GET …/MevzuatFihristDetayIframe?MevzuatTur=1&MevzuatNo=2709&MevzuatTertip=5` → 200，668,119 字节。元数据块：Kanun Numarası 2709 / Kabul Tarihi 18/10/1982 / 公报 9/11/1982 第 17863 期（**Mükerrer**）/ Düstür 5.卷 22 册 3 页；正文 = 合并历次修宪后的现行宪法全文，带脚注注记。
3. **规章实例**：KVKK Teşkilat Yönetmeliği（个人数据保护局组织规章，编号 201811296，类型 3）→ 名录记录批准决定 2018/11296（2018-01-17）、公报 2018-04-26 第 30403 期；正文元数据块另含**依据法律**（24/3/2016-6698 号 KVKK）——规章-法律挂钩字段。
4. **跨源核对**：Kanun 7595 的公报日期/期号与 resmigazete 源 2026-08-18 期（第 33344 期）条目 3 逐字一致（2026-09-27 双向核对）——两源互为对账基准。
5. **窗口合计**（2026-09-28 三次真实运行，账本实值）：总统令全类 `turs=19` = 1 名录请求 + 33 正文，33 文档 33 实体行，首轮 33 个正文任务因未探明的连字符方言全部升级、探明后零损失重排补跑（修复通道 33→pending→33 done）；CB Kararı 首页 `turs=20 pages=1` = 1 名录 + 100 个 `mev_pdf`，100 文档（正文全为 PDF，`metin.pdf`，魔数校验零假页）；Kanun 首页 `turs=1 pages=1` = 1 名录 + 100 正文，100 文档。**合计 233 文档 / 233 实体行 / 磁盘 233 文件，实体联挂 233/233，抽样三方逐字节对账 3/3 一致，重跑零请求**。

## 6. 怎么跑

```bash
# 演练（不入队执行，看会抓什么）
python cli.py collect --country tur --source mevzuat turs=19 --dry-run

# 小窗口真实抓取（总统令全套 33 部，含名录 + 正文全链）
python cli.py collect --country tur --source mevzuat turs=19

# 法律前 2 页（200 部）
python cli.py collect --country tur --source mevzuat turs=1 pages=2

# 全量名录走查（默认类型集 = 核心类 + 全部规章，约 1.9 万实体）
python cli.py collect --country tur --source mevzuat

# 周期性重走名录（发现新增实体；已抓正文跳过，见 §7）
python cli.py collect --country tur --source mevzuat refresh=2026-10-01T09:00:00

# 状态 / 快照 / 修复
python cli.py status --country tur --source mevzuat
python cli.py export --country tur
python cli.py requeue --country tur
```

## 7. 更新与增量

- **无日期游标**（名录不是按日期分区的），增量 = **参数化重开（refresh 模式）**：带新时间戳的 `mev_list` 种子改变任务身份、重走全部名录页（代价 = 类型数 × 页数，约 20–100 请求）；新发现的实体自动生成 `mev_metin` 补抓；已有实体的名录行 upsert 更新（如法律被废止后标题/状态字段变化）。
- **已知边界：整编正文静默更新不重抓**——源站无逐实体的"更新时间"信号，已完成正文任务照跳过。持续跟踪文本变化 = 将来把 refresh 参数延伸到正文层（另立任务身份重抓），本期不做。
- **发现即可判定的两个状态信号**：实体从现行类型（1/2/3…）转入废止库（5）时，refresh 重走会发现一条 tur=5 的新实体行——"法规退役"由此可得（政策终止研究的发现层）。
- 与 resmigazete 源互补：新法规先出现在公报（日更），MBS 整编入库略有滞后（数日到数周不等，未系统实测）。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **无版本时间线** | MBS 只存现行合并文本 + 废止标记，不存历史各版——版本序列研究需回 resmigazete 源取公布原件（修订链 = 公报原件天然构成）；修正脚注注记存在正文字节里，本期不解析 |
| **文件（pdf/doc）不重复抓** | 文本型实体（fileType=1）：正文收 iframe HTML，pdf/doc 与其同一内容，规范地址入 meta（pdf_url/doc_url），需要时按地址补抓；仅文件型实体（fileType=2，如 CB Kararı 整类）：PDF 是唯一正文，作为主文件 `metin.pdf` 收取（§3）。假页陷阱（§2）由魔数校验兜底 |
| 废止库只含法律 | Mülga 类型只有 Kanun（185 部）；规章/通告的废止状态在名录行与正文注记里，无独立废止库 |
| 类型码 0/6/16/17/18 等边角 | 奥斯曼旧法、宪法法院、议会内规等——默认类型集未含，`turs=` 参数可加（对未知类型码名录回落为全库，需按实类型清单传参） |
| 编号不唯一 | 同一编号可存在于不同类型/卷次代（身份必须三元组）；法律 7354 在现行库（tur=1）与废止库（tur=5）各有一行是合法现象 |
| 整编滞后 | 公报公布到 MBS 入库之间的延迟未系统实测（§7） |
| 生效日无独立字段 | 同公报源（§8）；"yürürlüğe girecek hükümler"（将来生效条款）按源站规则于生效日才并入整编文本 |

## 9. 端点速查表

**在用**：

| 用途 | URL 模式 |
|---|---|
| 名录（枚举唯一入口） | `POST https://www.mevzuat.gov.tr/anasayfa/MevzuatDatatable`（JSON；parameters.MevzuatTur 分类型 + start/length 分页） |
| 整编正文（文档本体） | `GET https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur={t}&MevzuatNo={n}&MevzuatTertip={r}` |
| 详情页（source_url 基底） | `https://www.mevzuat.gov.tr/mevzuat?MevzuatNo={n}&MevzuatTur={t}&MevzuatTertip={r}`（浏览器可开；采集不走此通道） |

**已确认存在、本源未用**（各自一句话研究价值）：

| 端点 | 价值 |
|---|---|
| `GET /MevzuatMetin/{t}.{r}.{n}.doc` | Word 版排版文件——需要编辑友好的版式时补抓 |
| `GET /anasayfa/MevzuatFihristDatatable` | 名录索引（fihrist）视图的数据接口——另一检索入口 |
| `POST /anasayfa/altkurum/{机构码}` | 机构层级下拉的数据接口（名录按子机构过滤）——机构维度统计素材 |
| `POST /aramasonuc`（站内检索） | 关键词全文检索——补漏/对账工具 |
| 名录参数 `BaslangicTarihi`/`BitisTarihi` | 名录的日期窗口过滤（表单存在，机器形状未实测）——按公报日切片名录的潜在捷径 |

---

*更新日期：2026-09-28；数据快照：2026-09-28；数据由 turs=19 全链（33 文档）+ turs=20 pages=1（100 文档 PDF 通道）+ turs=1 pages=1（100 文档）三窗实跑背书（233 文档零失败，抽样三方逐字节一致）。*
