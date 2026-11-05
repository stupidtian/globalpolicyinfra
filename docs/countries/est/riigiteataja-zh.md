# 爱沙尼亚（EST）数据源说明：Riigi Teataja

> 读者定位为外部开源用户：本文说明 `est` 国家包的 `riigiteataja` 源——抓什么、怎么抓、数据长什么样。所有数字均为真实数据（附日期，可从 `state.db` 复查）。

## 1. 源概览

**Riigi Teataja**（国家公报，riigiteataja.ee）是爱沙尼亚唯一的法定官方公布媒介，由司法与数字部（Justiits- ja Digiministeerium）运营，自 2010 年 6 月 1 日起为纯电子出版——在网站上刊登即为法律意义上的公布。站点同时承载两层文本（2026-10-27 实测站点自述）：

- **algtekst**（原样文本）：法规按通过时原样公布的版本；
- **terviktekst**（全文本/编纂版）：官方维护的编纂现行版，与英国 legislation.gov.uk 的 revised 版同类，在爱沙尼亚具有官方地位。未修订过的法规两版合一（源站标 `algtekst-terviktekst`）。

站点另有独立板块：Välislepingud（国际条约库）、Kohtuteave（法院信息）、Eelnõud（立法草案）、Tõlked（英译本，公报刊于 RT V 系列）——法院、草案、条约库与翻译不在本源的采集范围。

**覆盖范围与关键数字**（2026-10-27 实测清单 API）：全量清单 164,757 行，一行 = 一个公报刊出的文档版本；按原生类型分：seadus（议会法律）17,032、määrus（政府/部长条例）139,471（含地方市政条例，默认 scope=state 过滤）、korraldus（命令）7,681、otsus（决定）568、käskkiri（指令）4。语料自 1991 年（恢复独立）起，更早年代（含 1940–1991 苏联时期）无内容——1995-01-01 仍生效的仅 59 件，早期稀疏。正文为 XML（源站自有 Juurakt 大纲），一请求一份，元数据内联齐全。

## 2. 访问准备

- **无需 API key**，无需注册，无会话，无浏览器。
- **防火墙注意**：站点位于 Cloudflare 防火墙之后，其 User-Agent 规则会整站拒绝一批旧式客户端标识并返回 403（2026-10-27 实测：Python requests 库的默认标识与 curl 命令行均被拒，现代 Chrome 标识通过）。本源包已在每个请求上声明现代浏览器 UA（`REQUEST_HEADERS` 常量），用本项目命令行不需要任何额外配置；自写脚本时请带一个现代 UA。
- 限速：无官方限额文档，建议 `--delay 0.2:0.5` 礼貌速率。
- `.env` 无需任何条目。

## 3. 抓什么：任务类型清单

| 任务类型 | 请求 | 产出 |
|---|---|---|
| `rt_sweep` | `GET /api/oigusakt_otsing/1/otsi?leht=N&limiit=500[&dokument=类型]` | 清单一页（500 行，服务器上限；超出响亮报错）：每行一个**曾生效的文档版本**（globaalID、发行机构、原生类型、生效窗口、`muudetud` 更新戳），产出一个 `rt_act` 种子；`scope=state` 在行级滤掉市政机构 |
| `rt_alglist` | `POST /public-api/api/v1/otsing/alg-tekst`（空查询 JSON 体，`general.searchAfter`=行偏移） | **发布版层走查**一页（30 行，服务器固定）：全语料 162,166 行（2026-11-05 实测），每行 = 一次采纳的原版文档，产出 `rt_act` 种子（meta 带 `channel=algtekst`）；法院行结构性剔除、市政行按 scope 滤除 |
| `rt_act` | `GET /public-api/api/v1/akt/{globaalID}/blob-xml` | 一请求 = 一份文档：Ju­rakt XML 原字节落盘为文档主文件，`metaandmed` 元数据块解析入账（出版标记/采纳日/颁布/生效/版本/修订标记）。两个枚举通道共用此处理器 |
| `rt_classifiers` | `GET /public-api/api/v1/avalik/klassifikaatorid/alg-tekstid` | 源站词表快照（648 个发行机构，529 个标记市政；25 个原生类型），存 `01_raw/riigiteataja/classifiers.json` 备查，一次即可 |

两个枚举通道互补而非二选一：**`layer=current`（默认）走 rt_sweep**，拿每部法规曾生效的各版本（现行文本 + 版本时间线）；**`layer=algtekst` 走 rt_alglist**，拿每次采纳时的原版文本（时间序列研究的主通道）。未修订过的法规两通道命中同一文档 id，引擎按身份层自动去重，跑两遍只算一遍。

## 4. 数据落到哪

零领域表（登记册型扁平路径，与冰岛 Stjórnartíðindi、拉脱维亚 Vestnesis 同构）：**documents 表一行 = 一个公报刊出的文档版本**；同一法规的多版本关系以 `meta.group_id`（源站 `terviktekstiGrupiID`）随行携带，不在库内建实体表。

文件夹布局（每份文档一个文件夹级条目，按出版年份分片；正文 gzip 压缩存储，`file_hash` 为压缩字节的校验和，`mtime=0` 保证重抓字节全同）：

```
EST_policy/
├── state.db
├── 01_raw/riigiteataja/
│   ├── classifiers.json          ← 词表快照（一次）
│   ├── 2002/110010.xml.gz        ← globaalID 110010（RT II 2002, 15, 65）
│   ├── 2013/110112018002.xml.gz  ← …以此类推，{出版年}/{globaalID}.xml.gz
│   └── …
├── 02_cleaned/ 03_extracted/ failures/
```

`meta` 溢出列字段（全部字符串）：`globaal_id`、`publication_date_basis`（时间轴日期取自哪里，见 §7）、`tekstiliik`（algtekst-terviktekst / terviktekst）、`dokument_liik`、`dokument_etapp`、`dokument_staatus`、`group_id`、`rt_part`/`rt_number`/`rt_article`/`akt_viide`（出版标记）、`adopted_date`（采纳）、`entry_into_force`（生效，旧档在 `vastuvoetud/joustumine`）、`promulgation`（总统颁布，法律类）、`validity_start`/`validity_end`（生效/失效窗口）、`document_version`/`document_version_date`（编纂版本号）、`meta_version*`（元数据版本）、`keywords`（marksona 关键词）、`amendment_marks`（修订标记逐条 JSON）、`native_type`、`scope_slice`。

## 5. 完整案例走查

以 globaalID **110010**（《1966. aasta rahvusvahelise laadungimärgi konventsiooni 1988. aasta protokolli ratifitseerimise seadus》，批准 1988 年 LA 议定书的法律，2026-10-27 实测）走一遍：

1. **清单行**（rt_sweep）：`globaalID=110010, liik=seadus, valjaandja=Riigikogu, tekst=algtekst-terviktekst, kehtivus.algus=2002-06-07, muudetud=1453907227160` → 产出 rt_act 种子（signal = muudetud）。
2. **文档请求**（rt_act）：`GET /public-api/api/v1/akt/110010/blob-xml` → 3,417 字节 XML。
3. **落账**：documents 一行——`publication_date=2002-05-27`（RT II 出版标记日）、`issuing_authority=Riigikogu`、`doc_type=STATUTE`、`language=est`、`source_url=https://www.riigiteataja.ee/akt/110010`；meta 带上 `rt_part=RT II, rt_number=15, rt_article=65, adopted_date=2002-04-24, validity_start=2002-06-07, group_id=129508, publication_date_basis=publication_mark`，以及总统颁布记录（`promulgation`：Vabariigi President 2002-05-13 第 158 号）与修订标记（RT I 2002, 57, 355）。
4. **落盘**：`01_raw/riigiteataja/2002/110010.xml`（XML 原字节，file_hash 即其 sha256）。

5. **落账核对**（2026-10-27 首次真实运行）：本例 3,417 字节 XML 落盘，`doc_id=EST_20020527_…`，`file_hash` 与磁盘 sha256 逐字节一致；全窗 389 任务（清单 2 页 + 文档请求 + 词表）零失败，385 份文档磁盘≡账本哈希全对。

该 XML 还展示一个真实形状：正文前有**两个** `metaandmed` 块（元数据版本 1 与 2，先后两次维护记录）——解析取第一个。

## 6. 怎么跑

```bash
# 小窗口试跑：全量清单第 1 页（500 行）
python cli.py collect --country est --source riigiteataja pages=1:1

# 指定页区间 / 从某页走到空尾
python cli.py collect --country est --source riigiteataja pages=2:5
python cli.py collect --country est --source riigiteataja pages=300

# 只收某类（原生类型自由文本；常用值见 §1）
python cli.py collect --country est --source riigiteataja pages=1:2 dokument=seadus

# 全量（清单约 330 页 + 每版本一请求；量大）
python cli.py collect --country est --source riigiteataja

# 增量同步（登记册型无日期游标：换身份重走清单，逐行 muudetud 信号只重开变过的文档）
python cli.py collect --country est --source riigiteataja refresh=2026-10-27T00:00:00Z

# 发布版层（时间序列主通道）：指定行偏移窗口 / 全量走查
python cli.py collect --country est --source riigiteataja layer=algtekst offsets=0:300
python cli.py collect --country est --source riigiteataja layer=algtekst
python cli.py collect --country est --source riigiteataja layer=algtekst refresh=2026-11-05T00:00:00Z

# 市政条例（scope=all 时 rt_act 种子含市政机构）
python cli.py collect --country est --source riigiteataja pages=1:1 scope=all

# 状态 / dry-run
python cli.py status --country est --source riigiteataja
python cli.py collect --country est --source riigiteataja pages=1:1 --dry-run
```

## 7. 更新与增量

- **无日期游标**（清单不分日期分区，登记册型）：增量 = `refresh=<时间戳>` 改变任务身份重走清单；下游 rt_act 已 done 即跳过，只有清单行 `muudetud` 时间戳比账上新的才重开重抓（框架的信号重开规则）。发布版通道（rt_alglist）的搜索行不带更新戳，原版文本一经采纳不变——其文档为一次抓取，元数据勘误靠 refresh 重走覆盖（偏移翻页在长跑中的漂移由文档身份层吸收，重跑补扫即闭合）。
- **时间轴日期口径**：`publication_date` 按四级回退链取自源站（`meta.publication_date_basis` 记明取自哪级，2026-10-27 首次真实运行确定四种形态）：① 现行出版标记 `avaldamismarge/avaldamineKuupaev`（现代条目，编纂再版即再版日）→ ② `vastuvoetud` 内的原始出版标记日期（2010 年前迁移件，RTL 系列）→ ③ 采纳日 `vastuvoetud/aktikuupaev` → ④ 生效日 `kehtivus/kehtivuseAlgus`（2002–2004 年迁移件中极少数完全无日期者）。采纳/颁布/生效/失效各字段永远独立入 meta，不与时间轴日期混写。首窗 385 份的实测分布：出版标记 311 / 采纳日 72 / 生效日 2。
- **两通道的时间序列语义**：发布版文档（`meta.channel=algtekst`）= 政策出台事件的原样文本，其出版/采纳日即"出台时间"；`tekstiliik` 区分纯原版（修订过的法规）与原样即现行（未修订法规）。现行通道文档（meta 无 channel 字段）= 曾生效的各版本（含编纂版），供版本时间线与"某一时刻文本是什么"的研究。检索行与清单行都不含出版日期——出版日一律从文档 XML 的元数据块解析。
- 政策"出台"研究建议筛 `tekstiliik=algtekst-terviktekst` 且 `publication_date_basis=publication_mark` 的行；编纂再版是版本事件，不是新政策。

## 8. 已知边界与缺口

- **范围**：法院判决（Kohtuteave）、议会草案（Eelnõud）、国际条约库、RT V 英译序列不在本源。RT V 出版标记的条目在文档层以说明性空产出跳过（清单里出现即跳，任务照常记 done）。
- **市政条例**：`scope=state`（默认）按机构名复合词规则过滤（volikogu/vallavalitsus/linnavalitsus，2026-10-27 对源站词表 84/84 抽样吻合；词表快照存 `classifiers.json` 备查）。放宽改 `scope=all` 即自动回补（scope 在任务参数里，改参数 = 新任务身份）。
- **2010 年前旧档**：公布标记可能缺失或无日期（§7 回退链的②③④形态）；个别只有生效日。另有重键迁移件：数字清单 id 的文档请求以 UUID 应答（同组，2026-10-27 实测 globaalID 103112010012 一例，账上记 `answered_globaal_id`）。清单行无出版日期字段，偏移分页在两次全量运行之间可能因清单增删而漂移——refresh 重走 + 文档身份层去重兜底，不丢不重。
- **批量通道未用**：源站每 x 年提供整年 XML zip（`/avaandmed/ERT/`，SHA256 校验齐全；2026-10-27 实测 2024 包 344MB、2025 包 2.6GB、2026 包 43GB，逐年重生成）。本源走 API 不走 zip；zip 的 43GB 量级之谜留给未来回填任务。
- **防火墙**：见 §2——自写脚本必须带现代 UA，否则整站 403。

## 9. 端点速查表

**在用：**

| 端点 | 用途 |
|---|---|
| `GET /api/oigusakt_otsing/1/otsi?leht=&limiit=500[&dokument=][&valjaandja=][&kehtiv=日期]` | 现行清单分页（layer=current 用 leht/limiit/dokument） |
| `POST /public-api/api/v1/otsing/alg-tekst`（空查询体，`general.searchAfter`=行偏移，30 行/页） | 发布版层全量走查（layer=algtekst） |
| `GET /public-api/api/v1/akt/{globaalID}/blob-xml` | 文档版本全文 XML（主载体，两通道共用） |
| `GET /public-api/api/v1/avalik/klassifikaatorid/alg-tekstid` | 发行机构/类型词表（快照备查） |

**源里还有、暂未用（研究价值备查）：**

| 端点 | 说明 |
|---|---|
| `GET /public-api/api/v1/akt/{globaalID}` | 文档元数据 JSON（无正文；正文已随 blob-xml 内联，暂无必要） |
| `GET /public-api/api/v1/akt/{grupiId}/redaktsioonid` | 同一法规组的全部版本谱系（版本序列深挖的入口；实测增值税法组 12 版） |
| `GET /public-api/api/v1/akt/{globaalID}/blob-html` | 正文 HTML 载体（与 XML 同内容另一格式） |
| `POST /public-api/api/v1/otsing/tervik-tekst`（alg-tekst 同族） | 编纂版全文检索（searchAfter 游标分页；暂无需求） |
| `/avaandmed/ERT/`（xml.{年}.zip + SHA256SUMS） | 按年批量 XML 包，周更，CC-BY-SA-4.0；回填备选通道 |

---

*更新日期：2026-10-27；数据快照：2026-10-27；数据由 2026-10-27 的 `pages=1:1` 窗口（383 任务 / 381 文档）与 `dokument=käskkiri` 窗口（6 任务 / 4 文档）运行背书：389 任务全 done 零失败，385 份文档磁盘≡账本哈希逐份一致，幂等重跑零请求。*
