# 克罗地亚（HRV）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `nn` | 官方公报 Narodne novine 官报正文系列（法律、条例、决定等法规刊出条目），1990 年起，约 96,000 条（2026-11-01 估计） | NN Tražilica 平台（narodne-novine.nn.hr），Narodne novine d.d.（国家为多数股东的出版公司）运营，免费无 key | [nn-zh.md](./nn-zh.md) |

## 1b. 三结构现状

- **时间序列**：本源主体——每个刊出条目一行 `documents`，发布日期 = 印刷版出版日（Datum tiskanog izdanja）。原生日期字段仅公布日一项（平台的条目元数据不含采纳日/生效日结构化字段，正文中日期属提取阶段）；缺项原因已如实记录。
- **决策过程**：无原生来源（议会过程在 Hrvatski sabor 自有系统，未开）——记缺。
- **版本序列**：无原生版本谱系（同一部法的多次刊出在平台上是不同条目，不同 ELI 地址）；整合文本以 `pročišćeni tekst` 类型作为独立条目刊出——记缺（无原生版本表）。

## 2. 共享访问准备

- 无 API key、无注册、无会话；默认 `python-requests` UA 直接可用（2026-11-01 实测）。
- 数据目录 `{data_root}/HRV_policy/`；命令习惯见 [nn-zh.md](./nn-zh.md) §6。
- 限速：框架全局限速闸门默认值即可；大跨度回填分年分批、批间长间隔（智利累计封锁先例）。
- robots.txt：广告系列（`/clanci/oglasi/`、`kategorija=3`）禁抓且不在采集范围；站方下架的个别条目 URL 按路径精确匹配跳过。

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| 国际条约（Međunarodni dio 系列） | 未采集；枚举通道已勘明（`getEditionMaxNumber?category=2` + `search.aspx?kategorija=2`），扩展约一个枚举任务类型 |
| 法院与司法委员会条目 | 默认不采集（`scope=policy`；机关名整词含 `sud`/`sudbeno`，约占 6–11%）；`scope=all` 可放开 |
| 现行法规整合库（ISAP，司法部 Informacijski sustav propisa） | 未接入（免费官方整合层候选；2026-11-01 时本环境 DNS 不可达，未经直接实证） |
| 条目附件（dodatni 附图 PDF）、整期合订 PDF | 未采集（条目级 PDF/HTML 已覆盖正文） |
| 议会过程（Hrvatski sabor） | 无来源，记缺 |

---

*更新日期：2026-11-01；数据快照：2026-11-01；数据由 2026-11-01 试运行窗口背书。*
