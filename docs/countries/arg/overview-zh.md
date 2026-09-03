# 阿根廷（ARG）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。
> 文件命名规则：`{iso3}/{source}-{lang}.md`（国家文件夹 + 语言后缀，lang ∈ zh/en）；九节写作结构见 [_template-zh.md](../_template-zh.md)。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `bora` | 国家官方公报（BORA）第一部：法律、总统令（含 DNU 必要与紧迫性总统令）、决议、处令、行政决定、条约、集体劳动合同、官方公告——国家层级的全部成品规范与官方公告 | boletinoficial.gob.ar 分部页按日会话链（免 key：设日期 → 当日列表 → 翻页片段；详情页与附件 PDF 为 URL 编址的纯 GET） | [bora-zh.md](./bora-zh.md) |

## 1b. 三种数据结构现状

- **时间序列**：✅ 由 `bora` 源承担——按日公报全序列（档案在线覆盖 1940 年至今，2026-09-02 实测）；每条带刊出日（结构化）。制定日/生效日无结构化字段（签署日在正文文本内，如实记缺，抽取留清洗阶段）。
- **决策过程**：未收——国会两院（Congreso / Senado）的立法过程系统未开，记缺。
- **版本序列**：未收——现行法汇编（SAI，Sistema Argentino de Información Jurídica，argentina.gob.ar/normativa）是版本序列的官方载体，机器通道未探明，需要时另立源评估。

## 2. 共享访问准备

| 项 | 说明 |
|---|---|
| 数据目录 | `python cli.py init` 配置，或 `POLICY_DATA_ROOT` 环境变量；阿根廷数据落在 `{data_root}/ARG_policy/` |
| 密钥 | **无需任何 key**，`.env` 不需要条目 |
| 通用命令习惯 | `collect`（key=value 传参）/ `status` / `export` / `requeue` / `reset`，全部在仓库根目录 `python cli.py` 运行 |
| 节奏 | 国家公报服务器偏慢（中位约 4.7 秒/请求，2026-09-02 实测），建议 `--delay 1.5:3`；无反爬拦截。**本机配系统代理时须设 `NO_PROXY=www.boletinoficial.gob.ar` 直连**（代理出境路径会被掐 TLS，2026-09-03 实测；见 [bora-zh.md](./bora-zh.md) §2） |

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| 国会立法过程（法案、辩论、表决） | Congreso / Senado 两院系统，未开工 |
| 现行法汇编（SAI） | 版本序列的官方载体（argentina.gob.ar/normativa），未开工 |
| **省级官方公报**（23 省 + 布宜诺斯艾利斯市各自的公报系统） | **各省系统互不相同，无统一机器通道**。2026-09-02 抽查（境外直连）：布宜诺斯艾利斯**市**（boletinoficial.buenosaires.gob.ar）门户可访问、为传统表单式检索（`/buscar`，字段含日期区间/类目/发文字号——裸查询返回 500，需按表单完整参数探明后可用）；科尔多瓦省（boletinoficial.cba.gov.ar）对境外访问返回 **CloudFront 地域封锁 403**（响应体明言"block access from your country"）；布宜诺斯艾利斯**省**（boletinoficial.gba.gob.ar）连接超时（疑似同样限制境外访问）；"官方公报网络"（reddeboletines.gob.ar，各省公报的官方聚合门户）需浏览器执行脚本才能打开。**结论：省级扩展 = 每省一次独立探查 + 地域封锁是首要成本**（需代理或境内出口，属基础设施决策），与国家公报的友好度不可同日而语 |
| 公报特刊（suplemento） | 独立 PDF 挂 CDN、条目不进常规列表；补抓路径已留档（见 [bora-zh.md](./bora-zh.md) §8） |
| 公报第二 / 三 / 四部（人事、采购招标、.ar 域名公告） | 不在采集目标内（第二部且为门户 robots.txt 唯一禁抓的部） |

---

*更新日期：2026-09-03；数据快照：2026-09-03；数据由 bora 源 window=2026-08-28:2026-08-31 实跑背书（173 任务零失败 / 121 文档；另 sync 续收 2026-09-01 共 129 文档；计数见 [bora-zh.md](./bora-zh.md) §5）。*
