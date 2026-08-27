# 美国（USA）数据源说明——bills（国会法案）

> 文中数量为真实运行的实测参考值；你运行时的产出取决于所选届数与窗口。
> 阅读前提：了解仓库根目录 `python cli.py` 的用法即可，不需要读代码。
> 本文是 bills 单源的说明；美国全部源的总览见 [usa.md](./usa.md)。

## 1. 源概览

美国国会立法数据来自 **congress.gov 官方 API（v3）**——美国国会图书馆维护的官方接口，数据权威、结构化、免费。一个"届"（congress）两年，当前为第 119 届（2025-01 起）。法案 API 覆盖 **93 届（1973 年）至今**。

关键数字（数量级参考）：

- 119 届法案总量：**18,417 个**（每页 250 条，共 74 页枚举页）
- 每届国会约 1-2.5 万个法案；历史回填（93-119 届，27 届）估算 30-40 万个
- law（法律）不单独抓：法律 = 走完流程的法案，"成为公法"是它动作序列的最后一条

数据形态：纯 API（JSON），法案全文以 XML/HTML 文件形式另附下载链接。

## 2. 访问准备

| 项 | 说明 |
|---|---|
| API key | **必需**。免费注册：https://api.congress.gov/sign-up/ （一分钟） |
| 配置 | 仓库根 `.env` 文件写一行：`CONGRESS_API_KEY=你的key`（`.env` 不进 git） |
| 限额 | 正式 key 5,000 请求/小时；调试用的 DEMO_KEY 每天仅 50 次，不可用 |
| 限流行为 | 撞限额返回 429，框架自动指数退避放慢节奏，数据不丢 |
| 反爬 | 无。congress.gov 对 API 调用友好 |

## 3. 抓什么：任务类型清单

每种任务 = 一次 API 请求。当前在用 8 种：

| 任务类型 | 请求什么 | 产出什么 |
|---|---|---|
| `bill_list_page` | GET `/bill/119?offset=N&limit=250` | 台账行（每法案一条）+ 下一页任务 + 符合条件的深抓任务 |
| `bill_detail` | GET `/bill/119/{type}/{number}` | 台账补全（发起人/政策领域/文件夹） |
| `bill_actions` | GET `.../actions` | 生命周期大事记（整表重写）+ 终局判定 |
| `bill_summaries` | GET `.../summaries` | CRS 官方摘要全文 |
| `bill_text` | GET `.../text` | 登记各版本文档 + 每版本一个下载任务 |
| `bill_text_dl` | GET 版本文件 URL（congress.gov） | 法案文本 XML/HTML 落盘 |
| `vote_list_page` | GET `/house-vote/119/{session}?offset=N` | 投票行 + 下一页 + 详情任务 |
| `vote_detail` | GET `/house-vote/119/{session}/{roll}` | 投票头（议题/结果/政党汇总） |

命令行参数（key=value 形式）：

```
congress=119            必填，届数
deep=none|window|all    枚举时是否顺带深抓（默认 none 只登记）
window=FROM:TO          deep=window 时：引入或更新过在此区间的法案
cases=ID[,ID...]        指定深抓的法案（无论窗口）
max_pages=N             枚举链只翻 N 页（测试护栏）
sessions=1,2            要抓的投票会期
max_votes=N             每会期投票详情上限（测试护栏）
sync=1                  增量：只枚举自上次游标后有更新的法案
```

## 4. 数据落到哪

**三张领域表 + documents 表 + 每法案一个文件夹**：

| 位置 | 记什么 |
|---|---|
| `bills` 表 | 法案台账：编号、标题、发起人（姓名/党派/州/议员ID）、政策领域、最新动作、API更新时间、**终局状态**（enacted/vetoed/NULL=进行中）、摘要全文、文件夹路径 |
| `bill_actions` 表 | 大事记：日期、类型码、原文、涉及委员会编号（每法案整表重写） |
| `votes` 表 | 投票头：议题、结果、日期、所投法案（bill_id 回链）、政党汇总（如 R 208-0） |
| `documents` 表 | 法案文本版本：一版一档，`entity_ref` 指回法案（如 `bills:USA_119_S_98`） |
| `01_raw/policies/{届}/{类型}{号}/` | 该法案的全部材料（人读镜像，路径入账） |

文件夹布局（真实示例，S 98）：

```
01_raw/policies/119/S98/
├── detail.json          ← 详情页原始响应
├── actions.json         ← 动作页原始响应
├── summaries.json       ← 摘要页原始响应
├── votes/               ← 投到该法案的表决（原始响应）
└── text/
    ├── is.xml  8,314 B  ← 引入版（Introduced in Senate）
    ├── rs.xml  8,871 B  ← 委员会报告版
    ├── es.xml  8,272 B  ← 参院通过版
    ├── enr.xml  8,951 B ← 两院定稿版（Enrolled）
    └── version.html     ← 公法文本（成法后的正式文本）
```

## 5. 完整案例走查：S 98（Rural Broadband Protection Act of 2025）

一个法案从引入到成法的全程（真实数据实例）：

1. **引入**：2025-01-15，Sen. Capito, Shelley Moore [R-WV]（议员ID C001047），政策领域 Science, Technology, Communications；
2. **委员会**：2025-01-15 送商务委员会 → 2025-04-28 委员会报告、列入参院日程（大事记共 **23 条**）；
3. **表决**：（参议院表决不在 API 内，见第 8 节；众议院对该法案的表决会出现在 `votes` 表并回链此法案）；
4. **成法**：2026-05-11 动作 `BecameLaw`——"Became Public Law No: 119-89"，台账终局状态自动判为 **enacted**，此后增量同步不再重访；
5. **文本**：5 个版本全部落盘（见上文件夹图），documents 表 5 行，`entity_ref='bills:USA_119_S_98'`；
6. **摘要**：CRS 摘要 1,306 字符，存台账 `summary_text` 列。

对照案例 HR 204（ACRES Act）：同法流程走到中段（参院委员会已报告、列入日程），终局状态 NULL——增量同步会随国会进展自动补它的后续动作。

## 6. 怎么跑

```bash
# 演练（不抓任何东西，看会入队什么）
python cli.py collect --country usa --source bills congress=119 max_pages=3 \
    deep=window window=2026-08-10:2026-08-24 --dry-run

# 小规模试跑（约 300 次 API 请求）
python cli.py collect --country usa --source bills congress=119 max_pages=3 \
    deep=window window=2026-08-10:2026-08-24 \
    cases=USA_119_HR_204,USA_119_S_98 sessions=2 max_votes=20

# 全量登记（只建台账，不深抓：74 页 ≈ 3 分钟）
python cli.py collect --country usa --source bills congress=119 deep=none

# 深抓全部法案（分批进行，每批约 4 请求/法案）
python cli.py collect --country usa --source bills congress=119 deep=all

# 增量同步（只重访有更新的法案）
python cli.py collect --country usa --source bills congress=119 sync=1

# 状态 / 快照 / 修复
python cli.py status --country usa --source bills
python cli.py export --country usa
python cli.py requeue --country usa        # 失败任务复位
```

## 7. 更新与增量

- **重开规则**：每次枚举都携带每个法案的 `updateDate`（源站更新信号）。已完成过的深抓任务，只有当信号变新才会自动重开重抓；没变的跳过。所以重复运行同一命令是安全的、近零成本的。
- **同步游标**：`sync=1` 时，枚举只查"自 kv 里的 `bills_last_sync` 日期之后有更新"的法案，扫到最后一页时把游标推到今天。
- **终局判停**：动作序列出现"成为公法"→ enacted、"否决"→ vetoed；终局后源站基本不再更新，重开自然停止。
- **窗口双口径**：`deep=window` 的匹配 = 引入日期或更新日期落在窗口内（两者之一即可），量级差一个数量级，按需选。

## 8. 已知边界与缺口

| 缺口 | 说明 |
|---|---|
| **参议院投票** | API v3 **没有**参议院表决数据（只有众议院 house-vote，且标注 beta）。参议院官网有官方 XML 但反爬（Akamai 拦截脚本请求），需要浏览器传输方案（规划中），届时作为新任务类型接入 |
| 逐人投票明细 | 暂缓提供。数据源已验证可用（响应形状 `houseRollCallVoteMemberVotes.results[]`），补做 = 新增一种任务类型 |
| 空响应 | "该法案无摘要/无文本版本"是**合法空响应**，任务标记为"预期为空"，不告警不存档 |
| 公法文本文件名 | 成法版本的文件 URL 不匹配 `BILLS-*` 版本后缀规则，当前落名为 `version.html`（小瑕疵，待修为按 URL 推导后缀） |
| 文本打不开？ | 法案 XML 带 `<?xml-stylesheet?>` 样式表引用，浏览器打开显示空白属正常——用文本编辑器看，内容完整 |

## 9. 端点速查表

**在用（8 个）**：`/bill/{congress}`、`/bill/{c}/{type}/{n}`、`.../actions`、`.../text`、`.../summaries`、`/house-vote/{c}/{s}`、`/house-vote/{c}/{s}/{roll}`、版本文件直链（congress.gov 静态文件）。

**API 还有但暂未用**（每项 = 将来加一种任务类型）：共同提案人 `cosponsors`（提案联盟网络）、主题标签 `subjects`（领域细分）、全部标题史 `titles`、相关法案 `relatedbills`（政策扩散）、修正案 `amendments`（立法博弈）、委员会与议员主数据（行为者维度）、听证 `hearings`、委员会报告 `committee-report`、国会记录 `daily-congressional-record`、提名 `nominations`、条约 `treaties`、CRS 报告 `crsreport`。

**API 根本没有**：参议院逐次表决（见第 8 节）、已删除法案的正文（文本版本只有 API 列出的那些）。

---

*更新日期：2026-08-27*
