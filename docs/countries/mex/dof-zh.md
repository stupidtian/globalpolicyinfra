# 墨西哥联邦公报（MEX · DOF）数据源说明

> **读者定位**：外部开源用户第一。`DOF` = Diario Oficial de la Federación（联邦公报，墨西哥联邦政府的官方公报，法律/法令/部委协议的法定公布媒介）；`edición`（刊次）= 同一日期可有的多个刊本（晨版 Matutina / 晚版 Vespertina）；`nota`（条目）= 公报刊登的一条记录（一项法令、一份协议、一则通知）。

## 1. 源概览

- **官方机构**：联邦政府官方公报，由内政部（Secretaría de Gobernación, SEGOB）运营，站点 `https://dof.gob.mx`（宿于政府自有 Telmex 地址段 `187.218.29.0/24`）。
- **法律地位**：联邦法律与法令自刊出之日起生效力公示（部分法律条文本身以"自刊出于DOF起…"为生效条款），是联邦政策时间序列的权威来源。
- **覆盖范围**：数字年代自 1994 年前后起正文可全文获取（此前为扫描影像）；当前活跃条目号约 579 万号段（2026-09 实测）。一个工作日通常一个晨版，周五/月末偶有晚版；节假日无刊（2026-09-14 实测周三–周五单版各 16–18 条）。
- **形态**：无 JSON API——站点曾有的机器接口（`WS_*` 族）已在改版中删除（2026-09-14 实测 404）。**按日期+刊次寻址的版面页（HTML）就是采集界面**；每条 nota 另有按条目号寻址的正文页（HTML，全文内联）。正文页无签发机关名，机关信息只在全国版面页。

## 2. 访问准备

- **无需 API key**，`.env` 零条目；无注册、无会话要求（站点会发会话 cookie，传输层自动管理）。
- **网络可达性**（重要）：2026-09-14 实测，站点本身健康（美/欧多地点访问 HTTP 200、0.5–2.7 秒），但**部分网络到 `187.218.29.0/24` 整段不可路由**，且这些网络的本地 UDP DNS 对该域名应答不可信（被污染）。判别方法：`curl --resolve dof.gob.mx:443:187.218.29.164 https://dof.gob.mx/ --max-time 20`——超时即所在网络到该段不通，此时设置 `HTTPS_PROXY` 走代理即可（传输层原生识别该环境变量，零代码改动）。
- **编码**：页面声明 ISO-8859-1；个别页面 HTTP 头与页内声明不一致（实测 2012 年样本），解析器以页内 meta 声明为准、latin-1 兜底。
- **频率礼貌**：站点无公开限额；建议 `--delay 1:2`，同国台账一次跑一个源。

## 3. 抓什么：任务类型清单

| 任务类型 | 请求 | 每次产出 |
|---|---|---|
| `dof_index` | `GET /index.php?year={Y}&month={M}&day={D}&edicion={MAT\|VES}`——一个日历日的一个刊次的版面页 | 版面页每条 `a.enlaces` 条目 → 一个 `dof_nota`（机关/栏目/机构条/标题随参数携带）；空日（"No hay datos para la fecha seleccionada"）= 合法空产出，该刊次水位线照推 |
| `dof_nota` | `GET /nota_detalle.php?codigo={N}&fecha={DD/MM/YYYY}`——一条 nota 的正文页 | 响应字节原样存为 `nota.html`（主文件）；一行 documents（标题/刊出日/签发机关/类型/语言 spa + 溢出字段） |

**页面锚点**（2026-09-14 实测）：版面页表头 `Fecha: 11/09/2026 - Edición Matutina`（日期与刊次回显，与请求不符即拒绝采信）；层级 `txt_blanco`（栏目，如 `UNICA SECCION`）→ `txt_blanco2`（机构条，如 `PODER EJECUTIVO`）→ `subtitle_azul`（机关，如 `PRESIDENCIA DE LA REPUBLICA`）→ `a.enlaces`（条目链接+全标题）。注意页面另带访问跟踪链接 `class="enlaces_leido"`，其 `fecha` 参数年份错写（如 2026 年页面出现 1926）——按精确 class 名排除。正文页锚点：`DOF: 16/03/2020` 日期行 + `div#DivDetalleNota`（全文内联，内嵌文档的 `<title>` 载规范标题）。

## 4. 数据落到哪

- **零领域表**（公报型：一次刊登=一条数据，条目即文档本体），`documents` 表即全部台账：
  - `title`：条目全标题（版面页 `a.enlaces` 文本）；
  - `publication_date`：刊出日（版面页表头日期，与条目 URL 的 fecha 参数互证）；
  - `issuing_authority`：签发机关（版面页 `subtitle_azul` 行）；
  - `doc_type`：受控映射（标题首词 → STATUTE/DECREE/RESOLUTION/REGULATION/CIRCULAR/ORDER/NOTICE/AGREEMENT，其余 OTHER）；原生首词永存 `meta.tipo`；
  - `source_url`：`https://dof.gob.mx/nota_detalle.php?codigo={N}&fecha={DD/MM/YYYY}`（站点自身链接形态，可重建）；
  - `meta`：`codigo`（条目号）、`edicion`（刊次）、`seccion`/`organismo`（栏目/机构条）、`titulo_interno`（正文内嵌文档标题）、`files`（兄弟文件清单，当前仅 nota.html）。
- **文件布局**（一项政策一个文件夹）：

```
{data_root}/MEX_policy/
├── state.db
└── 01_raw/dof/2026/D20260911/MAT/N5798657/nota.html
```

## 5. 完整案例走查

以 2026-09-11 晨版头条为例（2026-09-14 实测版面页）：条目号 `5798657`，机关 `PRESIDENCIA DE LA REPUBLICA`（机构条 `PODER EJECUTIVO`，栏目 `UNICA SECCION`），标题"Decreto por el que se concede autorización a la persona titular del Poder Ejecutivo Federal…"（允许武装力量部队出境参加国际军事竞赛的总统授权令）。采集流：`dof_index` 请求 `index.php?year=2026&month=9&day=11&edicion=MAT`，表头回显 `Fecha: 11/09/2026 - Edición Matutina` 与请求一致 → 产出 `dof_nota` 种子；`dof_nota` 请求 `nota_detalle.php?codigo=5798657&fecha=11/09/2026`，页面 `DOF: 11/09/2026` 行互证一致 → documents 落一行（`doc_id = MEX_20260911_{sha256(source_url)前8位}`，框架计算），正文页字节存为 `01_raw/dof/2026/D20260911/MAT/N5798657/nota.html`（55,773 字节）。

**窗口背书（2026-09-14 采集，`state.db` 可逐项复查）**：晨版三日窗口 `window=2026-09-09:2026-09-11` 入账 **51 份文档**（09-09 周三 16 条 / 09-10 周四 17 条 / 09-11 周五 18 条），字节总量 23,003,550（单条最小 49,008 / 最大 5,255,401——大文件为内嵌影像的印刷形态页）；随后重跑同窗口：0 新任务执行、0 重复抓取（幂等跳过）；周六 09-12 单日采集回执"该日无数据"并照常推进水位线。

**全量回填（2026-09-14 启动、09-17 收官，`tipos=normativo` 法规核范围）**：**66,551 份文档**，覆盖 2000-01-01 → 2026-09-17 晨版全部出版日（9,746 个版面页）；总量 20.02 GB；账本 = 磁盘文件 = parquet 快照逐条一致，零重复 doc_id；年度分布 1,652–3,809 条/年（2000–2025 全年完整，2026 至 9 月）。类型分布：RESOLUTION 43,952（含反倾销等贸易救济序列）/ CIRCULAR 11,086 / DECREE 8,669 / 其他 2,844 / REGULATION 443 / STATUTE 58（多数联邦法律以"DECRETO por el que se expide la Ley…"标题刊出，归在 DECREE 名下）。

## 6. 怎么跑

```bash
# 首次采集（闭区间日期窗口，每个日历日×每个刊次一个种子）
python cli.py collect --country mex --source dof window=2026-09-09:2026-09-11

# 小规模试跑单日
python cli.py collect --country mex --source dof window=2026-09-11:2026-09-11

# 增量同步（水位线 dof_last_mat 推进到昨天为止；晚版另立水位线）
python cli.py collect --country mex --source dof sync=1

# 扩展晚版（各刊次独立水位线，互不干扰）
python cli.py collect --country mex --source dof window=2026-09-09:2026-09-11 ediciones=MAT,VES

# 只列计划不抓取 / 状态查询 / 断点修复
python cli.py collect --country mex --source dof window=2026-09-09:2026-09-11 --dry-run
python cli.py status --country mex --source dof
python cli.py requeue --country mex --source dof --task <task_id>
```

网络受限环境加代理：`HTTPS_PROXY=http://host:port python cli.py collect …`。

## 7. 更新与增量

- **水位线按刊次各立**（kv 键 `dof_last_mat` / `dof_last_ves`）：每个日历日的该刊次版面页被完整消费（无论有刊还是"无数据"回执）后推进；`sync=1` 从 `水位线+1` 走到**昨天**——晨版墨西哥城时间上午发布，提前抓"今天"得到的"无数据"回执与真空日同形，永不认领当天。
- **终局语义**：公报条目刊出即定（不可变快照）；更正/废止以新条目形式再刊登，天然是新行。done 任务不重访；整段历史重抓属于回填工程，非增量路径。
- **范围参数化**：`ediciones`（刊次集合）进入任务参数——将来开通晚版只增新任务、零清库。

## 8. 已知边界与缺口

- **电子化边界**：1994 年前为扫描影像年代，正文页无 `DivDetalleNota` 全文（如需，影像经 `nota_to_imagen_fs.php` 逐页 JPG 另立通路）。
- **晚版/特刊**：晚版（VES）未默认开启；特刊（Extraordinaria）刊次代码未实测（罕见刊本）。
- **PDF**：逐条 PDF（`nota_to_pdf.php`）与整机关 Word（`nota_to_doc.php`）未接入；正文以 HTML 页为原件。
- **机关名只在全国版面页**：正文页不含签发机关——若单条 nota 的机关字段缺失，说明其种子并非来自版面页通道。
- **网络环境**：所在网络到源站段不通时必须走代理（见 §2）；站点偶发慢响应（实测一次中继抓取 12 秒），传输层重试可覆盖。
- **条目号≠顺序语义**：codigo 是全局发放的行号，跨日期单调但不保证连续，不可用作完整性断言。

## 9. 端点速查表

在用：

| 端点 | 用途 |
|---|---|
| `GET /index.php?year={Y}&month={M}&day={D}&edicion={MAT\|VES}` | 按日+刊次版面页（采集入口） |
| `GET /nota_detalle.php?codigo={N}&fecha={DD/MM/YYYY}` | 条目正文页（文档本体） |

已知存在、暂未使用（每项一句话研究价值）：

| 端点 | 价值 |
|---|---|
| `GET /nota_to_pdf.php`（参数随正文页图标） | 逐条 PDF 印刷形态，版式保真需要时接 |
| `GET /nota_to_imagen_fs.php?codnota&fecha&cod_diario[&pagina]` | 逐条/逐页 JPG——1994 年前扫描年代的唯一正文通路 |
| `GET /nota_to_doc.php?codnota={N}` | 整机关当日打包 Word |
| `GET /ejemplaresDisponibles.php` | 纸本库存/刊本目录 |
| `GET /busqueda_avanzada.php` / `busqueda_detalle.php` | 站内检索（检索索引≠公报实况，只作对账辅助不作采集入口） |
| `GET /filtroRss.php` | RSS 通道（最新条目提醒用途） |

---

*更新日期：2026-09-17；数据快照：2026-09-17；数据由 2000-01-01 → 2026-09-17 晨版全量回填背书（66,551 份文档 / 20.02 GB / 9,746 个版面页，三方对账一致），计数可从 `state.db` 复查。*
