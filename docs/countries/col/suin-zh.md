# 哥伦比亚法规库（COL · suin）数据源说明

> **读者定位**：外部开源用户第一。`SUIN` = Sistema Único de Información Normativa（哥伦比亚全国唯一规范性信息系统，司法部运营的法规库，免费公开）；`tipo`（类型）= 法规的原生分类（法律 LEY / 法令 DECRETO / 决议 RESOLUCION 等）；`fecha`（日期）= 法规的**批准日**（sanción），是本源的时间轴。
> 一条法规一条记录：元数据来自检索索引，全文 HTML 来自文档接口，一次抓取取齐。

## 1. 源概览

- **官方机构**：SUIN-Juriscol，由司法部（Ministerio de Justicia y del Derecho）运营；2026 年改版后检索前端在 `lexis.minjusticia.gov.co`（Lexis 检索器），站点 `suin-juriscol.gov.co` 保留旧文档地址的跳转与门户页。
- **法律地位**：全国规范性信息的法定汇聚系统（免费向公众开放）；收录国会与总统及中央部委的法规现行文本。注意：**现行文本活视图**——一次抓取记录的是采集时点的文本与效力状态，不是刊登时的原样（原样定格见 `diario` 源）。
- **覆盖范围**：2026-10-19 实测全索引普查 **103,340 条**，其中法规类（宪法/修宪/法律/法典/法令/决议/通函/协议/指令/指示白名单）约 **8.97 万条**；历史深至 **1882 年**（实测最老样本 LEY 288 de 1882，刊于公报第 5,349 号）。判例类（宪法法院判决等约 1.03 万条）不在默认收录范围。
- **形态**：检索后端是公网免鉴权的 Elasticsearch 索引 `documents_pdn`（标准查询 DSL，`search_after` 可翻完全库）；全文接口按法规编号寻址，`data.textoHtml` 即现行全文 HTML（民法典实测 3.1MB，普通法令 4 万–20 万字节）。元数据与全文分离——索引无正文字段。

## 2. 访问准备

- **无需 API key**，`.env` 零条目；无注册、无会话要求。
- **网络可达性**：2026-10-19 实测，部分网络直连 `.gov.co` 段不可达；设置 `HTTPS_PROXY` 环境变量走代理即可（传输层原生识别）。
- **频率礼貌**：站点无公开限额与 robots 限制（robots.txt 为前端应用占位页）；建议 `--delay 1:2`。本源声明并行安全，`--workers ≥2` 可用。
- **204 空全文**（重要生产形状）：新批准的法规先入检索索引、后上全文——全文接口对"尚未上全文"的法规回答 **HTTP 204 空体**。框架按现行传输契约将其记为 `failed_permanent`（错误消息即 "HTTP 204"，一眼可辨）；待全文上线后重走同一窗口并用修复通道重开即可补抓（2026-10-19 实测：10 月上半月 32 条法规中 28 条处于此状态，9 月及更早全部有全文——正文上线滞后约一至数周）。

## 3. 抓什么：任务类型清单

| 任务类型 | 请求 | 每次产出 |
|---|---|---|
| `suin_window` | `POST /elasticsearch/documents_pdn/_search`——一个批准日历日的第 0 页（fecha 当日区间 + 类型白名单 + 按编号排序，每页 100 条） | 每条命中 → 一个 `suin_doc`；命中满 100 条 → 一个 `suin_page` 续页；空日 = 合法空产出，水位线照推 |
| `suin_page` | 同上（`search_after` 游标翻页） | 同上；首个不满页 = 当日穷尽，水位线照推 |
| `suin_doc` | `GET /suin-search/api/documentos/{id}`——一条法规的现行全文 JSON | 一行 documents + 全文 HTML 原样落盘 `doc.html`（主文件） |

**页面锚点**（2026-10-19 实测）：检索响应 `hits.hits[]. _source` 携带 `id / tipo / subtipo / titulo / epigrafe / numero / anio / fecha / numerodiariooficial / paginadiariooficial / documentofuente / estado / entidad / materia / sector / noart`；文档接口响应 `data` 携带 `textoHtml / vigencia / entidadEmisora / url（旧地址）/ updateTimestamp`。接口响应的 `data.id` 必须与请求编号一致（不一致即拒绝采信）。类型字段在索引边缘有脏值（表单残留如 "-- Seleccione --"、数字串）——类型白名单天然排除。

## 4. 数据落到哪

- **零领域表**（一法规一行），`documents` 表即全部台账：
  - `title`：`titulo`（如 "LEY 2638 2026"），缺失时用 `epigrafe`（全文标题）；
  - `publication_date`：批准日（fecha，时间序列主轴）；
  - `issuing_authority`：`entidad`（如 "CONGRESO DE LA REPUBLICA"）；
  - `doc_type`：受控映射（CONSTITUTION / STATUTE / DECREE / RESOLUTION / CIRCULAR / AGREEMENT / ORDER，未知一律 OTHER）；原生 `tipo`/`subtipo` 永存 meta；
  - `source_url`：`https://lexis.minjusticia.gov.co/suin-search/api/documentos/{id}`（字节实际来源，可重建）；
  - `meta`：`suin_id`、`subtipo`、`epigrafe`、`numero`、`anio`、`materia`、`sector`、`noart`（条数）、`numero_diario`（公报期号）、`pagina_diario`（公报页码）、`documentofuente`（公报引用原文）、`estado`（效力状态原词，采集时点快照）、`vigencia`、`entidad_emisora`、`viewer_url`（现行查看页）、`legacy_url`（旧站地址）、`update_timestamp`、`files`。
- **文件布局**（一个文档一个文件夹）：

```
{data_root}/COL_policy/
├── state.db
└── 01_raw/suin/{年}/D{YYYYMMDD}/{法规编号}/doc.html
```

## 5. 完整案例走查

以 **RESOLUCION 614 de 2026**（经济部决议，2026-10-02 批准）为例（2026-10-19 实测）：`suin_window` 任务请求 2026-10-02 的检索页，命中该法规（编号 30058365，无公报期号字段——元数据缺口随源照收）；`suin_doc` 任务请求文档接口，得 39,394 字节现行全文 HTML，落盘 `01_raw/suin/2026/D20261002/30058365/doc.html`，账本落一行 `doc_id = COL_20261002_e2a22ef1`（`title = RESOLUCION 614 2026`，`doc_type = RESOLUTION`）。

**窗口背书（2026-10-19 采集，`state.db` 可逐项复查）**：窗口 `window=2026-10-01:2026-10-19` 枚举 **32 条法规**（19 个 `suin_window` 任务 + 32 个 `suin_doc` 任务），其中 **4 份全文入账**（RESOLUCION 614 / CIRCULAR 24 / RESOLUCION 2332 / DECRETO 1488，39–113KB），28 条为 204 空全文（正文未上库，见 §2）；随后重跑同窗口：0 新任务执行、0 重复抓取（幂等跳过）；`sync=1` 从水位线次日走到昨天，已同步时零动作。

## 6. 怎么跑

```bash
# 首次采集（闭区间批准日窗口，每日一个种子）
python cli.py collect --country col --source suin window=2026-10-01:2026-10-19

# 小规模试跑单日
python cli.py collect --country col --source suin window=2026-10-01:2026-10-01

# 增量同步（水位线 suin_last_date 走到昨天为止）
python cli.py collect --country col --source suin sync=1

# 扩大类型范围（白名单进任务参数——放宽后新任务自动补抓，零清库）
python cli.py collect --country col --source suin window=2026-10-01:2026-10-19 tipos=LEY,DECRETO

# 只列计划不抓取 / 状态查询 / 断点修复
python cli.py collect --country col --source suin window=2026-10-01:2026-10-05 --dry-run
python cli.py status --country col --source suin
python cli.py requeue --country col --source suin --task <task_id>
```

网络受限环境加代理：`HTTPS_PROXY=http://host:port python cli.py collect …`。

## 7. 更新与增量

- **水位线**：kv 键 `suin_last_date`（批准日轴）。每个日历日的检索被完整消费（无论空日还是有货）后推进；`sync=1` 从水位线+1 走到**昨天**——批准与索引收录存在时滞，提前抓"今天"得到的空日与真空日同形。
- **批准-收录时滞的补齐**：法规可能在批准数日后才入索引、再数日后才上全文。跟踪手段 = 周期性用 `window=` 重走近期窗口（任务身份随窗口参数变化，已完成的文档任务自动跳过，仅新增/补抓）；204 的全文补抓再配合 `requeue` 重开。
- **终局语义**：现行文本活视图——一次抓取即一个时点快照，完成任务不重访；跟踪文本演进属版本序列议题（记缺）。
- **范围参数化**：`tipos` 白名单进任务参数——放宽范围 = 新任务身份自动补抓、零清库。

## 8. 已知边界与缺口

- **204 空全文**：新法规正文上线滞后约一至数周（§2）——任务记 `failed_permanent`，属例行形状而非故障；补抓流程见 §7。
- **生效日无结构化字段**：三日期中"生效日"记缺（部分法规文本内可见，未结构化）。
- **元数据可缺字段**：部分条目公报期号/页码为空（如实照收）；类型字段有脏值（白名单排除）。
- **判例出界**：宪法法院判决（CC-SENTENCIA 等）与 AUTO 类（实测为表单残留垃圾数据）不在默认范围。
- **现行文本 ≠ 刊登原样**：需要 as-published 原样时用 `diario` 源（公报整期 PDF）。
- **网络环境**：直连不稳时必须走代理（§2）。

## 9. 端点速查表

在用：

| 端点 | 用途 |
|---|---|
| `POST /elasticsearch/documents_pdn/_search` | 元数据检索（日期窗 + 类型过滤 + search_after 翻页） |
| `GET /suin-search/api/documentos/{id}` | 单条法规现行全文（`data.textoHtml`；204 = 未上库） |

已知存在、暂未使用（每项一句话研究价值）：

| 端点 | 价值 |
|---|---|
| `GET /elasticsearch/_cat/indices` | 索引清单（`documents`/`documents_stg`/`biblioteca_juridica` 等姊妹库）——全库体检与对账基准 |
| `GET /minjusticia/viewDocument/{id}` | 人类查看页（正文经 iframe 注入，采集走接口不走此页）——人工核对入口 |
| `https://www.suin-juriscol.gov.co/viewDocument.asp?id={id}` | 旧站文档地址（接口响应自带）——与旧引用体系互查 |
| Lexis 检索器 Jurisprudencia 区（索引 CC-SENTENCIA 等） | 判例素材（出界，政策终止研究若需判例可另立源） |
| `utu.minjusticia.gov.co`（gov.co CMS 后端） | 门户内容管理，无法规数据 |

---

*更新日期：2026-10-19；数据快照：2026-10-19；数据由 2026-10-01→2026-10-19 批准日窗口背书（32 条法规枚举、4 份全文入账、28 条 204 空全文如实记录，三方对账一致），计数可从 `state.db` 复查。*
