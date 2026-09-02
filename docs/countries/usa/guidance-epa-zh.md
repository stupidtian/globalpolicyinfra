# 美国（USA）指引层说明——环境保护署（EPA）

> 上游总览见 [guidance-zh.md](./guidance-zh.md)。本文讲 EPA 渠道的站点取证、三级分类漏斗与解析细节。
> 分类规则经用户确认（2026-08-31），实测分布见文末。

## 1. 站点结构取证

环境保护署（Environmental Protection Agency，EPA）2024 年重建的"综合指引文件网站"（`epa.gov/guidance`）是动态搜索界面，15 个项目办公室分页的静态超文本标记语言（HTML）里**没有文档行**——指引门户不可直抓。

绕行路线（站点地图优先法）：`epa.gov/sitemap.xml` 是标准**站点地图索引**（`<sitemapindex>`，38 个子页 × 每页 2,000 个 URL，全站约 7.5 万）。含 "guidance" 字样的候选 URL 共 **1,318** 个——但精度不纯：60 页随机抽样逐页核验发现约 85% 是真指引文档页，其余混有四类噪音（关于指引的新闻、监察长报告、公众意见、常见问答页）。

由此本渠道的核心不是抓取而是**分类**：三级漏斗把 1,318 个候选分流，负类留痕不深抓。

## 2. 三级分类漏斗（规则全文）

**第一级：URL 层（抓取前）**

| 规则 | 判为 | 依据 |
|---|---|---|
| 路径以 `/newsreleases/` 开头 | `NEWS` | 新闻区无指引原件 |
| 路径含 `/learn-about`、`what-you-can-do`、`/faq` | `LEARN` | 科普/导航页 |
| URL 末段是整句疑问（what/how/are/is/does… 开头） | `FAQ_PAGE` | 如 `are-schools-required-follow-…-guidance` |
| 路径含 `/web-policies-and-procedures/` | `SITE_POLICY` | 网站自身管理规范，非环境政策 |

**第二级：标题层（抓到页面后的负向排除）**

| 规则 | 判为 | 真实样本 |
|---|---|---|
| 标题以新闻动词开头（EPA Announces / Proposes / Rescinds / Issues / Releases / Publishes / Finalizes） | `NEWS` | "EPA Rescinds Rule on Guidance Documents" |
| 标题以 "Report:" 开头 | `REPORT` | "Report: CSB Did Not Follow Federal Guidance…" |
| 标题以 "Comments from/of" 开头 | `COMMENT` | "Comments from State of Colorado - Draft…" |

**第三级：正向判定**——未被排除且（标题含 Guidance/Memorandum/Directive 或 PRN 编号〔农药登记通知代码〕**或**挂有 PDF 附件**或**正文含 "guidance"）→ `GUIDANCE`，做完整解析（标题、日期、正文抽取、PDF 附件下载，每页附件上限 10 份）。其余兜底 `OTHER`。

**留痕原则**：所有负类也写一行瘦记录（机构、URL、标题、`page_class`），不深抓——账本能回答"看到了什么、为什么没深抓"。负类的 `doc_type` 一律 OTHER（通道标签不作语义声明）。

## 3. 解析细节与坑

- 标题取 `<title>` 去掉 "| US EPA" 后缀；
- 日期匹配 "Last updated on August 14, 2025" 一类标记，标准化为 ISO 格式；
- 无原生编号的页面以 URL 末段（slug）为主键；
- 坑一：EPA 的站点地图根节点前有样式表声明与注释，`<sitemapindex>` 被推出嗅探窗口——非站点地图判定窗口须放宽到 1,000 字节；
- 坑二：根是 `<sitemapindex>`（子元素 `<sitemap>`），而 OFAC/OCC 的根是 `<urlset>`（子元素 `<url>`）——解析器两者都要认；
- 坑三：抓取配额是**整链预算**，站点地图链上每页继承剩余额度，否则每页各给一份配额会放大数十倍；
- 坑四（重要）：**EPA 的软限流表现为挂起而非报错**——连续抓取约 400 页后，服务器不再返回 429，而是让请求一直挂到客户端超时（实测 2026-08-31：此前 414 页全部正常，此后每个请求都超时；2026-09-01 隔日复跑约 90 页后再度触发——冷却不重置阈值，安全预算按"每突发约 90 页"计）。引擎的分钟级重试会继续磨但短期进度趋零。对策：全量抓取放慢节奏、或分段隔日续跑；账本保证续跑无损。
- 坑五：**附件外链的涓流端点**——指引页的 PDF 附件不全在 EPA 主站：`nepis.epa.gov`（出版物档案库，老扫描件）实测约 71KB/s 馈送且 CGI 流无 Content-Length；`gpo.gov`→`govinfo.gov`（外链的历史《联邦公报》PDF，如 11MB 的 1986 年整日刊）同量级。字节间隔低于读超时阈值，框架超时永不触发——表现为单任务"挂住"数分钟到十余分钟，实为慢传输。此类附件约占附件总量 8%，耐心排空即可，无需干预。

## 4. 命令与实测分布

```bash
python cli.py collect --country usa --source guidance agency=epa max_docs=25 max_pages=2   # 小样
python cli.py collect --country usa --source guidance agency=epa                          # 全量（1,318 页 + 附件）
```

首次真实运行：完成 414 页后遇软限流（见坑四），分布为 `GUIDANCE` 359（87%）/ `NEWS` 44 / `FAQ_PAGE` 5 / `REPORT` 4 / `SITE_POLICY` 2——与抽样预估的 85% 相符。

截至 2026-09-01 分段推进后：已生成并处理 543 个页面任务（另 164 个限流耗尽待下轮 requeue、3 个 `/webguide/` 403 为范围外终态），约 600 个候选页尚未生成（持有链页待 requeue 后续链）；附件 1,091/1,093 已落盘（余 2 个为外链终态：CDC 403、英国研究主机超时）。分布更新为 `GUIDANCE` 457（88%）/ `NEWS` 46 / `REPORT` 6 / `FAQ_PAGE` 5 / `SITE_POLICY` 2。完成操作步骤见批次 E 结题报告 §4。

---

*更新日期：2026-09-01；数据快照：2026-08-31（探查实测）+ 2026-09-01（两轮分段推进）；余量跨日多轮推进中。*
