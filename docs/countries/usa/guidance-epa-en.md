# USA Guidance Layer Notes — Environmental Protection Agency (EPA)

> For the upstream overview see [guidance-en.md](./guidance-en.md). This document covers the EPA channel: site forensics, the three-stage classification funnel, and parsing details.
> The classification rules were reviewed and approved (2026-08-31); the measured distribution is at the end.

## 1. Site-structure forensics

The Environmental Protection Agency's (EPA) 2024-rebuilt "consolidated guidance documents website" (`epa.gov/guidance`) is a dynamic search interface — the static HyperText Markup Language (HTML) paginated by the 15 program offices **contains no document rows** — the guidance portal cannot be crawled directly.

The bypass (sitemap-first method): `epa.gov/sitemap.xml` is a standard **sitemap index** (`<sitemapindex>`, 38 child pages × 2,000 URLs each, ~75,000 site-wide). Candidate URLs containing "guidance" number **1,318** — but the precision is impure: a random 60-page sample checked page by page found ~85% genuine guidance document pages, with the remainder mixed among four noise classes (news about guidance, inspector-general reports, public comments, question-and-answer pages).

So the core of this channel is not fetching but **classification**: a three-stage funnel routes the 1,318 candidates, with negative classes recorded but not fetched deeply.

## 2. The three-stage classification funnel (full rules)

**Stage 1: URL level (before fetching)**

| Rule | Classifies as | Basis |
|---|---|---|
| path starts with `/newsreleases/` | `NEWS` | the news section holds no guidance originals |
| path contains `/learn-about`, `what-you-can-do`, `/faq` | `LEARN` | popular-science / navigation pages |
| URL last segment is a whole-sentence question (starting what/how/are/is/does…) | `FAQ_PAGE` | for example `are-schools-required-follow-…-guidance` |
| path contains `/web-policies-and-procedures/` | `SITE_POLICY` | the website's own management rules, not environmental policy |

**Stage 2: title level (negative exclusion after fetching the page)**

| Rule | Classifies as | Real sample |
|---|---|---|
| title starts with a news verb (EPA Announces / Proposes / Rescinds / Issues / Releases / Publishes / Finalizes) | `NEWS` | "EPA Rescinds Rule on Guidance Documents" |
| title starts with "Report:" | `REPORT` | "Report: CSB Did Not Follow Federal Guidance…" |
| title starts with "Comments from/of" | `COMMENT` | "Comments from State of Colorado - Draft…" |

**Stage 3: positive decision** — not excluded and (title contains Guidance/Memorandum/Directive or a PRN code [Pesticide Registration Notice number] **or** the page has PDF attachments **or** the body mentions "guidance") -> `GUIDANCE`, with full parsing (title, date, text extraction, PDF attachment downloads, a 10-attachment cap per page). Everything else falls back to `OTHER`.

**The recording principle**: every negative class also writes a slim row (agency, URL, title, `page_class`) without deep fetching — the ledger can answer "what was seen and why it was not fetched deeply". Negative classes always get `doc_type` OTHER (a channel label makes no semantic claim).

## 3. Parsing details and pitfalls

- the title comes from `<title>` with the "| US EPA" suffix stripped;
- dates match markers like "Last updated on August 14, 2025", normalized to ISO format;
- pages without a native number use the URL last segment (slug) as the primary key;
- pitfall 1: a stylesheet declaration and comment precede EPA's sitemap root node, pushing `<sitemapindex>` out of the sniffing window — the non-sitemap sniff window must widen to 1,000 bytes;
- pitfall 2: the root is a `<sitemapindex>` (child elements `<sitemap>`) while OFAC's and OCC's roots are `<urlset>` (child elements `<url>`) — the parser must recognize both;
- pitfall 3: the fetch quota is a **whole-chain budget**; every page in the sitemap chain inherits what is left, otherwise a per-page quota multiplies the budget tens of times over;
- pitfall 4 (important): **EPA's soft throttling manifests as hanging, not erroring** — after roughly 400 consecutive pages the server stops returning 429 and instead lets requests hang until the client times out (measured 2026-08-31: the previous 414 pages all normal; every request after that timed out; a resumed pass on 2026-09-01 hit the same wall after ~90 pages). The engine's minute-level retries keep grinding but short-term progress approaches zero. Remedies: slow the full crawl down, or resume in stages across time windows; the ledger guarantees lossless resumption.
- pitfall 5: **trickle endpoints among outbound attachment links** — not every PDF attachment sits on EPA's main site: `nepis.epa.gov` (the publications archive, old scans) measured at ~71KB/s with CGI streaming and no Content-Length; `gpo.gov` -> `govinfo.gov` (linked historical Federal Register PDFs, for example an 11MB full-day 1986 issue) is the same order. Byte intervals stay below the read-timeout threshold, so the framework timeout never fires — a single task "hangs" for minutes to over ten minutes while actually just transferring slowly. Such attachments are roughly 8% of the total; drain them patiently, no intervention needed.

## 4. Commands and measured distribution

```bash
python cli.py collect --country usa --source guidance agency=epa max_docs=25 max_pages=2   # small sample
python cli.py collect --country usa --source guidance agency=epa                          # full (1,318 pages + attachments)
```

First real run: 414 pages completed before the soft throttle engaged (see pitfall 4), distributed `GUIDANCE` 359 (87%) / `NEWS` 44 / `FAQ_PAGE` 5 / `REPORT` 4 / `SITE_POLICY` 2 — matching the 85% sample estimate.

As of 2026-09-01, after staged resumption: 543 page tasks spawned and processed (another 164 throttle-exhausted ones await the next requeue pass; 3 `/webguide/` 403s are out-of-scope terminal states), and ~600 candidate pages are not yet spawned (the chain holder awaits requeue); attachments 1,091/1,093 on disk (the remaining 2 are external-link terminal states: a CDC 403 and a UK research-host timeout). The updated distribution is `GUIDANCE` 457 (88%) / `NEWS` 46 / `REPORT` 6 / `FAQ_PAGE` 5 / `SITE_POLICY` 2. Completion steps are in section 4 of the batch E completion report.

---

*Updated: 2026-09-01; data snapshot: 2026-08-31 (live probing) + 2026-09-01 (two staged passes); the remainder progresses across days.*
