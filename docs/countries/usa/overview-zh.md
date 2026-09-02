# 美国（USA）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。
> 文件命名规则：`{iso3}/{source}-{lang}.md`（国家文件夹 + 语言后缀，lang ∈ zh/en）；九节写作结构见 [_template-zh.md](../_template-zh.md)。英文版：[overview-en.md](./overview-en.md)。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `bills` | 国会立法全流程：法案引入 → 委员会 → 表决 → 成法（含动作史、投票头、各版本文本） | congress.gov 官方 API v3（需免费 key） | [bills-zh.md](./bills-zh.md) |
| `regulations` | 行政系统规制全生命周期：规制计划（统一议程）→ 白宫审查（OIRA）→ FR 出版（提案/终稿/纠错）→ 生效 | Federal Register API + reginfo.gov（均无需 key） | [regulations-zh.md](./regulations-zh.md) |
| `guidance` | 机构直发政策文件：指引、政策声明、官方问答、指令（财政部/商务部/EPA 起步，逐机构铺开） | 各机构官网（站点地图优先，均无需 key） | [guidance-zh.md](./guidance-zh.md) |

两个源各自独立运行（`--source bills` / `--source regulations`），共用同一个 `state.db`：框架账（tasks/documents/kv/events）全体共享，领域表（bills 三表 + regulations 五表）由美国包统一建。

## 2. 共享访问准备

| 项 | 说明 |
|---|---|
| 数据目录 | `python cli.py init` 配置，或 `POLICY_DATA_ROOT` 环境变量；美国数据落在 `{data_root}/USA_policy/` |
| 密钥 | 只 bills 需要：`.env` 写 `CONGRESS_API_KEY=…`（见 usa-bills.md 第 2 节）。regulations 全程无需 key |
| 通用命令习惯 | `collect`（key=value 传参）/ `status` / `export` / `requeue` / `reset`，全部在仓库根目录 `python cli.py` 运行 |
| 节奏 | 框架统一限速（请求间隔 0.5–1 秒随机）+ 错误三分法重试，撞限流自动放慢，数据不丢 |
| **一次只跑一个源** | 同一国家的台账按到期时间取任务，而任务处理器按源注册——**切换 `--source` 前先确认上一源的队列已清空**（`python cli.py status` 看非 done 任务数），否则另一源的待办任务会被误判为无处理器的永久失败（可经 `requeue` 全量恢复，但应避免） |

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| 规制评论 / 听证记录 | regulations.gov（需 api.data.gov key），数据路已探明（FR 详情带 docket 与跳转 URL），列为后续扩展 |
| 指引层其余机构（FDA/OMB 等） | 方法已验证（FDA 站点地图实测 3,643 指引页），后续批次；财政部/商务部/EPA 已开工见 [guidance-zh.md](./guidance-zh.md) |
| CFR（法规典成品） | 未开工（终稿生效后的汇编层） |

---

*更新日期：2026-09-01（补 guidance 源行）；数据快照：2026-08-27；数据由 bills 119 届全量基线与 regulations 三链实跑背书（见各源文件）。*
