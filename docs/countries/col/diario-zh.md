# 哥伦比亚官方日报（COL · diario）数据源说明

> **读者定位**：外部开源用户第一。`Diario Oficial` = 哥伦比亚官方日报（国家印刷局 Imprenta Nacional de Colombia 出版的法定公布媒介，1864-04-30 创刊，ISSN 0122-2112）；`刊号`（Número de Diario，如 53.659）= 日报的连续期号；`期`（issue）= 一个出版日的一期（可能多册——同日多篇时检索表出现多行）。
> 一期一条记录：整期 PDF 原样落盘，一次刊登 = 一次定格（as-published）。

## 1. 源概览

- **官方机构**：Imprenta Nacional de Colombia（国家印刷局，国家所有商工企业）；公报自 1864 年 4 月 30 日由总统 Manuel Murillo Toro 创办至今，是哥伦比亚国家法规的法定公布媒介（法律、法令等自刊出起产生公示效力）。
- **法律地位**：官方公布媒介原件——整期 PDF 即 as-published 权威快照（与法规库的现行文本互补，见 `suin-zh.md`）。
- **覆盖范围**：检索器的**数字 PDF 自 2001-01 起可得**（2026-10-19 实测边界：2000-12-15 无 PDF、2001-01-15 有）；2001 年前的期次在检索器中元数据稀疏且无 PDF（点击查看落投稿表单页）——记缺。2026 年实测日出一期（周日刊为 1 页封面形），每期 1–108 页、0.3–66MB 不等。**2001 起全部采样刊本为数字原生（自带文字层），无扫描件年代**。
- **形态**：Imprenta 公报检索器 `svrpubindc.imprenta.gov.co/diario`（PrimeFaces/JSF 应用），**没有逐期静态地址**——每期经"建会话 → 逐日检索 → 逐期查看 → 动态资源下载"的会话链取得（cookie + 视图状态 + 下载令牌由框架传输层与会话任务管理，对使用者透明）。

## 2. 访问准备

- **无需 API key**，`.env` 零条目；无注册。
- **会话语义**（使用者无需操作，了解即可）：每次采集运行开始时一个会话任务取回首页（cookie 入传输层 cookie 罐、JSF 视图状态随任务参数传递）；该应用的视图状态全会话稳定，且**逐日检索与行点击必须严格相邻执行**（检索会刷新服务端共享表格模型——框架的任务链已保证此顺序，勿手动拆跑单个任务）。
- **网络可达性**：2026-10-19 实测部分网络直连不稳，设置 `HTTPS_PROXY` 走代理即可。
- **频率礼貌**：政府自营应用，无公开限额；建议 `--delay 1:2`，单源单进程（本源会话绑定，框架自动封顶并发为 1）。
- **单期体积**：工作日整期 PDF 可达数十 MB（实测最大 66MB），批量回填前预留磁盘与带宽。

## 3. 抓什么：任务类型清单

| 任务类型 | 请求 | 每次产出 |
|---|---|---|
| `diario_session` | `GET /diario/`——检索器首页 | 解析视图状态，为窗口**第一天**发一个逐日任务（链式走日） |
| `diario_day` | `POST /diario/index.xhtml`——一个日历日的检索表单（起=止=当日） | 表格每行（刊号/刊种/日期回显）→ 一个 `diario_issue`；空表（"Registro 0 a 0 de 0"）= 合法空产出；无论空否，当日水位线照推 |
| `diario_issue` | `POST` 该行"Ver Diario"按钮 | 查看页解析：动态下载地址（会话令牌）+ 刊号/日期回显互证 → 一个 `diario_pdf`；**无下载对象 + 投稿表单形状 = 该期无数字档案**（合法空产出，2001 前签名）；当日最后一期顺链发次日的检索任务 |
| `diario_pdf` | `GET` 动态资源地址（同会话） | 整期 PDF 字节原样落盘 `diario.pdf`（主文件）+ 一行 documents；`%PDF-` 魔数校验 |

**页面锚点**（2026-10-19 实测）：检索表单字段 `fechaInicial_input`/`fechaFinal_input`（dd/MM/yyyy）、`numeroDiarioOf`（按刊号检索，备用）；结果表行 `dtbDiariosOficiales:{行}:{numeroDiario|tipoEdicion|fechaDiario}`；行按钮 `dtbDiariosOficiales:{行}:j_idt34`；查看页回显标签 `Número de Diario`/`Tipo Edición`/`Fecha de Publicación`（回显与请求不符即拒绝采信——这是防"共享表格模型过期"的守卫）与 `<object type="application/pdf" data="…dynamiccontent.properties.xhtml?pfdrid=…">`。

## 4. 数据落到哪

- **零领域表**（一期一行），`documents` 表即全部台账：
  - `title`：`Diario Oficial No. {刊号} de {日期}`（按刊头自述形状构造，站点无逐期标题元素）；
  - `publication_date`：刊出日（时间序列锚点，与查看页回显互证）；
  - `issuing_authority`：`Imprenta Nacional de Colombia`（整期的发布方即出版方）；
  - `doc_type`：OTHER（刊本无文档类原生类型；刊种 Ordinaria 等原词入 meta）；
  - `source_url`：`https://svrpubindc.imprenta.gov.co/diario/?numero={刊号}`（规范参数形，逐期可重建——站点本身无静态地址）；
  - `meta`：`numero_diario`（原串含点）、`tipo_edicion`、`dynamic_query`（下载令牌串，事后溯源）、`files`。
- **文件布局**（一期一个文件夹）：

```
{data_root}/COL_policy/
├── state.db
└── 01_raw/diario/{年}/D{YYYYMMDD}/{刊号去点}/diario.pdf
```

## 5. 完整案例走查

以 **第 53.659 号（2026-10-15，周四刊）** 为例（2026-10-19 实测）：`diario_day` 检索 15/10/2026 得一行（53.659 / Ordinaria）；`diario_issue` 点击该行，查看页回显 `Número de Diario: 53.659` 与 `Fecha de Publicación: 15/10/2026`（互证一致）；`diario_pdf` 取回 **66,231,948 字节**整期 PDF（96 页，自带文字层），落盘 `01_raw/diario/2026/D20261015/53659/diario.pdf`，账本落一行 `doc_id = COL_20261015_b48dd2c9`。

**窗口背书（2026-10-19 采集，`state.db` 可逐项复查）**：窗口 `window=2026-10-14:2026-10-16` 入账 **3 期**（53.658 = 10,321,582 字节 / 53.659 = 66,231,948 / 53.660 = 2,183,712，三期合计 78.7MB），10 任务零失败；随后 `sync=1` 从水位线次日走到昨天，已同步时零动作。

## 6. 怎么跑

```bash
# 首次采集（闭区间日期窗口；会话链自动逐日走）
python cli.py collect --country col --source diario window=2026-10-14:2026-10-16

# 小规模试跑单日
python cli.py collect --country col --source diario window=2026-10-16:2026-10-16

# 增量同步（水位线 diario_last_date 走到昨天为止）
python cli.py collect --country col --source diario sync=1

# 只列计划不抓取 / 状态查询 / 断点修复
python cli.py collect --country col --source diario window=2026-10-14:2026-10-15 --dry-run
python cli.py status --country col --source diario
python cli.py requeue --country col --source diario --task <task_id>
```

网络受限环境加代理：`HTTPS_PROXY=http://host:port python cli.py collect …`。注意：窗口中间断跑后**重跑整个窗口**即可（已完成任务自动跳过，会话任务每次运行重建）。

## 7. 更新与增量

- **水位线**：kv 键 `diario_last_date`（刊出日轴）。每个日历日的检索被完整消费（无论空日还是有刊）后推进；`sync=1` 从水位线+1 走到**昨天**——当日刊可能晚出，提前抓"今天"得到的空表与真空日同形。
- **终局语义**：一次刊登即定格（更正/废止以新刊登出，天然新行）；完成任务不重访。
- **回填边界**：2001-01 起可全量（逐年约 300–365 期）；2001 年前检索器无数字档案，记缺（见 §8）。

## 8. 已知边界与缺口

- **2001 年前无数字档案**：检索行可存在但点击落投稿表单页（如实记为合法空产出）；1950 年代部分日期甚至无检索行（元数据本身稀疏）。整期 PDF 的历史覆盖以 2001 年为界。
- **周日刊是 1 页封面形**：如 2026-10-18（53.662）整期仅 1 页（511 字符）——周日确有出版，照收（跳过即篡改时间序列）。
- **会话链的顺序约束**：逐日检索与行点击共享服务端表格模型——框架任务链已保证顺序；手动对单任务做修复（requeue/reset）时，重跑整个窗口比单点重开更稳。
- **一期多行**：同日多册时检索表出现多行，每行一期、各自入账（历史年代实测存在）。
- **单期体积大**：工作日整期可达 66MB+（含内嵌影像页），限速与磁盘预留见 §2。
- **网络环境**：直连不稳时必须走代理（§2）。

## 9. 端点速查表

在用：

| 端点 | 用途 |
|---|---|
| `GET /diario/` | 建会话 + 取视图状态（每次运行一个） |
| `POST /diario/index.xhtml`（检索表单） | 逐日刊次列表（采集入口） |
| `POST /diario/index.xhtml`（行按钮） | 逐期查看页（下载地址 + 回显互证） |
| `GET /diario/javax.faces.resource/dynamiccontent.properties.xhtml?…` | 整期 PDF 下载（会话令牌） |

已知存在、暂未使用（每项一句话研究价值）：

| 端点 | 用途 |
|---|---|
| 检索表单 `numeroDiarioOf`（按刊号） | 期号→日期互查（法规库引用的公报期号反查刊出日） |
| 检索表单投稿流程（"solicita tu publicación"） | 投稿入口，与采集无关 |
| `imprenta.gov.co/repositorio`（数字 repository） | 印刷局历史出版物仓库——2001 前公报影像的潜在替代源（另立项评估） |

---

*更新日期：2026-10-19；数据快照：2026-10-19；数据由 2026-10-14→16 窗口背书（3 期整刊 PDF 共 78.7MB 入账、10 任务零失败、三方对账一致），计数可从 `state.db` 复查。*
