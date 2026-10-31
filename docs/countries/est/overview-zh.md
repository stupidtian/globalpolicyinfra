# 爱沙尼亚（EST）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `riigiteataja` | 官方公报刊出的全部法规类文档版本（法律、政府/部长条例、命令等；1991 年恢复独立至今，1995 年前极稀疏；2026-10-27 实测清单 164,757 行） | Riigi Teataja（国家公报，riigiteataja.ee，司法与数字部运营）站内免 key API：清单 `GET /api/oigusakt_otsing/1/otsi` + 正文 `GET /public-api/api/v1/akt/{id}/blob-xml` | [riigiteataja-zh.md](./riigiteataja-zh.md) |

## 1b. 三结构现状

- **时间序列**：本源主体——每份文档版本带官方出版标记日期（`publication_date`，四级回退链并记 `publication_date_basis` 溯源）；采纳日、颁布日、生效/失效日各字段独立入 meta。语料自 1991 年起（苏联时期无内容，更早年代无内容）。
- **决策过程**：记缺——议会过程（Riigikogu）与立法草案（Eelnõud）不在本源。
- **版本序列**：原生可得——清单即版本粒度（一行一版本），同一法规的组 id（`meta.group_id`）随行携带；源站还有版本谱系端点 `akt/{grupiId}/redaktsioonid`（暂未用，入口记在源文档 §9）。组关系未建实体表，建图留给分析阶段。

## 2. 共享访问准备

- 数据目录：`{data_root}/EST_policy/`（默认 `D:\Research_Data\PolicyInfra`）。
- **密钥：无**——源站免 key，`.env` 无需任何条目。
- 命令习惯：一切从仓库根 `python cli.py collect --country est --source riigiteataja …`（用法见源文档 §6）。
- 限速节奏：`--delay 0.2:0.5` 起步；无官方限额，礼貌速率即可。
- **防火墙坑**：站点在 Cloudflare 之后，按 User-Agent 黑名单拒绝旧式客户端（Python requests 默认标识与 curl 都会被整站 403）；本源包已内置现代浏览器 UA，自写脚本须自带。

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| 议会过程（Riigikogu 法案、Eelnõud 草案） | 未采集，记缺 |
| 法院判决（Kohtuteave / Riigi Kohus） | 出界不做 |
| 国际条约（Välislepingud 库；清单含 välisleping 类型行，入账为 OTHER） | 库本身未采集 |
| RT V 英译序列 | 跳过（说明性空产出） |
| 地方市政条例（KOV määrus） | 默认 scope=state 过滤；`scope=all` 即收 |
| 版本谱系深挖（redaktsioonid 端点） | 未开；组 id 已随行入账 |
| 正文清理（纯文本提取） | 未开（XML 结构化载体，raw 即结构层） |

---

*更新日期：2026-10-27；数据快照：2026-10-27；数据由 2026-10-27 的 `pages=1:1` 窗口与 `dokument=käskkiri` 窗口运行背书（389 任务全 done，385 份文档哈希对账一致，幂等重跑零请求）。*
