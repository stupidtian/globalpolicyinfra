# 荷兰（NLD）数据源总览

> 一个源一个文件：本文件只做总览与共享信息，各源细节见对应文件。
> 文件命名规则：`{iso3}/{source}-{lang}.md`（国家文件夹 + 语言后缀）。

## 1. 源清单

| 源 | 覆盖什么 | 数据从哪来 | 说明文件 |
|---|---|---|---|
| `bekendmakingen` | 荷兰官方公布渠道——**Staatsblad**（国家公报，法律与王国法令的法定公布媒介）的公布事件流（时间序列） | KOOP 官方 SRU API（`repository.overheid.nl/sru`，免 key）+ 仓库直链的全文 XML | [bekendmakingen-zh.md](./bekendmakingen-zh.md) |

**运营方**：KOOP（*Koöperatie Overheidsportalen* 体系下的政府出版局，Stichting Officiële Publicaties）。官方公布门户 www.officielebekendmakingen.nl 汇聚 Staatsblad / Staatscourant / Tractatenblad / Gemeentebladen / Provinciale bladen 等一切官方公布物；该门户背后即 KOOP 的官方检索 API（SRU，Search/Retrieve via URL——一种带查询语法的图书馆标准检索接口），本源直接走 API，不爬网页。

## 1b. 三结构现状

- **时间序列**：本源（bekendmakingen）承担，Staatsblad 刊出即一条公布事件，发布日期（dt.issued）与签署日期（datumOndertekening）分开收齐。
- **决策过程**：记缺——议会过程（Tweede Kamer 文件库、Kamervragen 等）不在本源采集范围。
- **版本序列**：记缺——现行法编纂库 wetten.overheid.nl（BWB，*Basiswetgevingbestand*，基础法文件库）是原生版本序列层，未采集（深链对直连请求不开放，2026-09-29 实测主页 200 而法规页 404）。

## 2. 共享访问准备

| 项 | 说明 |
|---|---|
| 数据目录 | 与框架统一：`{data_root}/NLD_policy/`，账本 `state.db` |
| 密钥 | **无需任何 key**（SRU API 免 key、无注册；`.env` 无需条目） |
| 命令习惯 | 一律从仓库根运行 `python cli.py collect --country nld --source bekendmakingen …` |
| 限速节奏 | API 无公开限额；连续数十请求实测零拦截（2026-09-29）。框架默认限速（0.5–1 秒/请求）已足够礼貌，批量取数走 API 而非网页也是源站明示的立场（robots.txt 只禁 HTML 搜索结果页） |
| 许可 | 荷兰《著作权法》（Auteurswet）第 11 条：法律、法令与条例不受著作权保护（除公布物自身另有声明） |

## 3. 尚未覆盖的政策层

| 层 | 现状 |
|---|---|
| 现行编纂文本（版本序列） | 未采——wetten.overheid.nl（BWB），暂无稳定机器通道，留待另立 |
| Staatscourant（政府公报另一主力，部委决定/人事/招标公告为主） | 端点已验通（2026 年约 3.2 万条），`blad=` 参数即可开启；默认不采（量大且政策文书密度低） |
| Tractatenblad（条约公报）/ Gemeente- 与 Provinciale bladen（地方公报） | 同一 API 内各自 content-area，未采（地方规章明确不在范围） |
| 议会过程（Kamerstukken、Kamervragen、Handelingen） | 未采——过程数据另属决策过程结构 |
| 1951 年前 Staatsblad 纸质年代 | SRU 索引内不存在（索引下限实测 1951） |

---

*更新日期：2026-09-30；数据快照：2026-09-29；数据由 2000–2026 全量回填（16,465 文档 / 0.99 GB，26 个年份标识符集合对账全等）背书，详见各源说明文件文末。*
