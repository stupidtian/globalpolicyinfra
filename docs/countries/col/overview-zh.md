# 哥伦比亚（COL）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。
> 文件命名规则：`{iso3}/{source}-{lang}.md`（国家文件夹 + 语言后缀，lang ∈ zh/en）。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `suin` | 国家级法规的**现行文本与效力状态**（宪法修正/法律/法令/决议/通函/协议/指令/指示，1882 年起，约 8.97 万条法规量级，2026-10-19 实测普查） | SUIN-Juriscol（Sistema Único de Información Normativa，哥伦比亚全国唯一规范性信息系统，司法部 Ministerio de Justicia y del Derecho 运营）的检索后端：lexis.minjusticia.gov.co 的公网 Elasticsearch 元数据检索 + 全文 API | [suin-zh.md](./suin-zh.md) |
| `diario` | **Diario Oficial de Colombia**（官方日报，1864-04-30 创刊，国家印刷局 Imprenta Nacional de Colombia 出版，ISSN 0122-2112）的整期 PDF，按刊出日一条记录；数字 PDF 自 2001-01 起可得 | Imprenta Nacional 公报检索器：svrpubindc.imprenta.gov.co/diario（会话链：建会话 → 逐日检索 → 逐期查看 → 动态资源下载） | [diario-zh.md](./diario-zh.md) |

两源互补：`suin` 给法规级结构化元数据与现行全文（活视图快照），`diario` 给公报级 as-published 原样定格（一次刊登 = 一条数据）。SUIN 的每条法规自带公报期号引用（`documentofuente` 字段，如 "DIARIO OFICIAL. AÑO XVII. N. 5349. 09, MAYO, 1882. PÁG. 1."），两库可交叉核对——2026-10-19 实测互证一致（SUIN 称 2026-10-01 法规刊于第 53,645 号，公报检索器同日实测 53.645）。

## 1b. 三结构现状

- **时间序列**：两源共同承担。`suin` 按**批准日（fecha de sanción）**轴逐日枚举（日期字段齐备；生效日无结构化字段——记缺；公报公布日以期号+引用原文随行，日期经 `diario` 源可推导）；`diario` 按**刊出日**轴逐日枚举（as-published 权威锚点）。
- **决策过程**：记缺——议会过程（Congreso）源不在收录范围。
- **版本序列**：记缺——`suin` 是现行文本活视图（一次抓取 = 采集时点的一个状态，无历史版本通道）；`diario` 是 as-published 定格（更正以新刊登出，天然新行）。

## 2. 共享访问准备

- 数据目录：`{data_root}/COL_policy/`（`state.db` + `01_raw/`）。
- **无需 API key**，`.env` 零条目；两源均免注册、免会话密钥（`diario` 的 JSF 会话 cookie 与视图状态由框架传输层自动管理）。
- **网络可达性**（重要）：2026-10-19 实测，本机网络对 `suin-juriscol.gov.co` 直连不可达（域名解析正常、TCP 不通）；`svrpubindc.imprenta.gov.co`、`lexis.minjusticia.gov.co`、`utu.minjusticia.gov.co` 直连亦不稳。经 `HTTPS_PROXY` 代理环境变量全部可达（传输层原生识别该变量，零代码改动；与墨西哥 DOF 同款网络环境问题）。
- 限速节奏：`suin` 无公开限额，建议 `--delay 1:2`；`diario` 为政府自营 JSF 应用，建议 `--delay 1:2` 且**同国台账一次跑一个源**。`suin` 声明了并行安全（`--workers` 可用）；`diario` 会话绑定，框架自动封顶单 worker。

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| 判例（Constitucional Court 判决 CC-SENTENCIA 7,598 条等） | 不做（出界）；SUIN 检索器 Jurisprudencia 区含此素材 |
| 2001 年前的公报整期 PDF | 记缺——检索器无数字档案（点击落投稿表单页）；不 OCR |
| 生效日期（fecha de vigencia）结构化字段 | 记缺——SUIN 无此字段（部分文本内可见，未结构化） |
| 历史版本的版本谱系 | 记缺——SUIN 为现行文本活视图 |
| 地方政府/大区公报 | 不做 |
| 公开数据门户 datos.gov.co | 评估结论：无公报/法规数据集，不可用（2026-10-19 实测检索） |

---

*更新日期：2026-10-19；数据快照：2026-10-19；数据由 2026-10-01→2026-10-19 法规窗（32 条枚举 / 4 份全文入账）与 2026-10-14→16 公报窗（3 期整刊 PDF 入账）背书，计数可从 `state.db` 复查。*
