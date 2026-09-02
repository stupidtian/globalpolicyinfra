# United States (USA) — Source Guide: regulations (Executive-Branch Rulemaking)

> Coverage ranges and counts in this file are stable characteristics of the official data sources; all cases are real-data examples.
> Prerequisite: familiarity with `python cli.py` — no code reading required. See [overview-en.md](./overview-en.md) for the USA source overview.
> This is the English edition of [regulations-zh.md](./regulations-zh.md); the Chinese original is authoritative.

## 1. Source Overview

### 1.1 Institutional Background: The Complete Life of a Federal Regulation

Understanding this source starts with the institution. US federal rulemaking is governed by the Administrative Procedure Act (APA, 1946) and a series of presidential executive orders. Three parties play the core roles: the **executive agencies** (departments and independent agencies that draft and publish rules), the **Office of Information and Regulatory Affairs** (OIRA, part of the White House's Office of Management and Budget, exercising review on the President's behalf), and the **public** (participating in the comment period). Historical arc: Reagan's EO 12291 (1981) created the presidential-review and regulatory-planning system (the first complete Regulatory Plan followed in 1983); Clinton's EO 12866 (1993) set the framework still in force today.

A rulemaking typically passes through seven stages. **For each stage: who does what, what information it leaves behind, and whether we can get it:**

**Stage 0: Entering the regulatory plan (one snapshot each spring and fall).** Agencies report "what rules I intend to make" to OIRA, compiled into the **Unified Agenda** (two editions per year; the fall edition additionally carries the **Regulatory Plan** — each agency's statement of regulatory priorities). From this moment a rulemaking receives its lifetime identifier, the **RIN**. Each agenda entry carries: title, abstract, lead agency, priority category (economically significant / other significant / routine), current stage (pre-rule / proposed / final / completed / long-term), a **timetable of planned milestones** (e.g. "NPRM targeted for November 2026", month-granularity plan values), legal authority, and the CFR parts to be amended. The agenda has no notion of "review comments" — it is OMB's official compilation of plans, and the agencies' own abstracts are the entire explanation. Electronic editions exist since fall 1995.

**Stage 1: White House review (before a draft is published).** Once an agency finishes drafting a rule (proposed or final), it **must go through OIRA review before publication in the FR**. Mind the rhythm: the twice-yearly event is the *agenda publication*; review itself is a pipeline — any agency may submit on any day. In 2025 OIRA completed 449 reviews (610 in 2005), averaging 1–2 new reviews per working day, with a hundred-plus rules queued at the White House at any moment. Each review leaves: the RIN, which draft it was, date received, date completed, the **decision** (Consistent without Change / Consistent with Change / Withdrawn, etc.), and whether it is economically significant. Review records are complete since 1981. **What is public about review comments comes in three layers**: line-by-line edits are not public (FOIA only); return letters (the formal letter when OIRA sends a draft back for reconsideration) are public but rare (a few dozen PDFs since 2001); the **meeting logs** of outside groups meeting OIRA about a rule are public (XML since 2024, web pages earlier).

**Stage 2: Publication of the proposed rule in the FR.** A cleared draft is published in the Federal Register (FR), the official daily gazette. An FR document contains: a document number (unique for life), title, type, publication date, the **comment closing date**, RIN, docket ID, the CFR parts to be amended, abstract, and full text. The body is the agency's "case for the rule": rationale, a summary of cost-benefit analysis, and clause-by-clause provisions.

**Stage 3: Public comment period (usually 30–60 days) + the agency's response.** Anyone may submit comments (text + attachments) to the docket on regulations.gov; agencies may hold hearings. Comments are fully public and grouped by docket — this is the process's largest body of "opinions", and **it needs a separate API key, which this source does not yet crawl** (the path is paved: FR detail carries docket IDs and jump URLs). The agency's response has no separate document — it is written into the preamble of the final rule ("Response to Comments"), so capturing the final rule's full text captures the response.

**Stage 4: Second White House review (final draft).** The final draft goes through OIRA once more, leaving a second review record. A RIN therefore typically has ≥2 review records (one for the proposal, one for the final; more if interim drafts exist).

**Stage 5: Publication of the final rule + effective date.** The final rule is published with an **effective date** (`effective_on`, usually 30–60 days after publication) and is then incorporated into the Code of Federal Regulations (CFR) — the compilation layer is outside this source's scope.

**Stage 6: Aftermath.** Mistakes are fixed by separate **correction documents** (linked both ways with the original, which itself is never altered); proposals can be withdrawn (a withdrawal notice in the FR); and some projects die quietly (marked Withdrawn in the agenda, or simply stop appearing — telling "dead or done" apart requires comparing several agenda snapshots, which is exactly what the ua_entries table is for).

Two institutional caveats (the data design already accounts for them):

- **The agenda does not guarantee whole-of-life coverage**: a rule may enter the agenda very late (the RIN in section 5, case 1, first appeared when it was already at the final-rule stage, after its interim rule had been published), and some rules never appear at all. For studying "all regulation", the OIRA review record (complete since 1981) is the floor; the agenda supplements it with the planning dimension. Across full history the agenda has accumulated roughly 47k RINs, of which about 26k were ever reviewed by OIRA — the two sets do not coincide (many agenda items are never submitted for review, and some reviewed rules never appear in the archived agenda).
- Not every regulatory document walks the full path: presidential documents (executive orders, proclamations) skip the comment period, and many Notices carry no RIN; the seven-stage journey belongs to the Rule/Proposed Rule types.

### 1.2 What This Source Crawls

Following the stages above, this source covers six of the seven stages (everything except the comment period), drawing on three datasets:

```
Stage 0 Plan      Stage 1 Review (prop.) Stage 2 Publish prop. Stage 3 Comments  Stage 4 Review (final) Stage 5 Publish final  Stage 6 Aftermath
Unified     ──→   OIRA White    ──→      FR Proposed     ──→   regulations  ──→  OIRA White       ──→   FR Final Rule   ──→      corrections /
Agenda            House review           Rule                  .gov docket      House review           (effective_on)          withdrawals
(semiannual)      (dates+decision)                              (not crawled)   (dates+decision)
```

Three datasets, three entrances, **none requiring an API key**:

| Dataset | Coverage | Scale |
|---|---|---|
| Unified Agenda (fall edition includes the Regulatory Plan) | Fall 1995 → present, semiannual, **60 editions** | Latest edition 3,954 rulemaking projects (RINs); full history accumulates to over a hundred thousand entries |
| OIRA review records (EO 12866 reviews) | **Since 1981**, 45 per-year files + 3 rolling files (under review / last 30 days / YTD) | ~400–600 reviews per year (449 in 2025); ~150 under review at any moment |
| Federal Register documents | Complete since **1994-01-03** | ~2,300–2,800 documents per month |

**The key threading the whole process is the RIN** (Regulation Identifier Number, e.g. `0331-AA10`): planning, review, and publication all carry it, so one rulemaking keeps the same identifier from plan to final rule. The auxiliary thread is the docket ID (on the FR side), because Notice-type documents often lack a RIN.

The three-way convergence has been verified against a real rule (see the cases in section 5).

## 2. Access Preparation

| Item | Notes |
|---|---|
| API key | **Not needed.** Both federalregister.gov and reginfo.gov are open; no new `.env` entry required |
| Rate limit | Neither site publishes a limit; sustained requests are not blocked. The framework's uniform throttling (0.5–1 s per request) is safely within bounds |
| Anti-scraping | None. reginfo.gov's web search uses a CSRF form, but the direct XML links (all we use) are unimpeded |
| Response formats | FR is JSON; reginfo is XML (largest single agenda file 17.6MB; review files ~400KB) |

## 3. What Gets Crawled: Task Types

Each task = one download + one parse. **Five types** in total:

| Task type | Requests | Produces |
|---|---|---|
| `fr_list_page` | One page of the FR document listing (`per_page=1000`, filtered by publication-date window) | Document ledger rows (one per document) + one detail task per document (when deep=all) + the next-page task |
| `fr_detail` | One document's detail endpoint | Ledger enrichment (RIN/docket/effective date/comment deadline/correction links…) + the document folder + text-download tasks |
| `fr_text_dl` | One text file's direct link | txt/xml text written to disk + registered in documents (one row per format) |
| `ua_edition` | One Unified Agenda edition XML | rulemakings project rows (merged across editions) + ua_entries per-edition snapshots + the raw XML archived and accounted |
| `oira_file` | One review XML (a calendar year, or a rolling "currently under review" file) | oira_reviews rows + the raw XML archived and accounted |

Command-line parameters (key=value form):

```
window=FROM:TO          FR chain: documents published in the range (e.g. 2026-08-17:2026-08-19)
deep=none|all           FR chain: whether listing also fetches detail+text (default none = register only)
formats=txt,xml         text formats to download (default txt,xml; pdf not fetched)
max_pages=N             cap the listing chain at N pages (test guardrail)
cases=DOCNUM[,…]        documents to deep-crawl regardless of the window
agenda=all|edition list agenda chain: e.g. all or 202510,202504 (not started by default)
oira=all|year list      review chain: e.g. all or 2025,2024; all includes the rolling files
sync=1                  FR incremental: window starts at the kv cursor fr_last_pub_date and ends today
```

One key difference from bills: **an FR document barely changes once published** (mistakes become separate correction documents linked to the original), so the FR side needs no reopen-on-signal mechanism — incrementals simply chase "publication date > last cursor".

## 4. Where the Data Lands

**Five domain tables + the documents table + two kinds of file locations**:

| Location | What it records |
|---|---|
| `rulemakings` table | The **rulemaking master table**, one row per RIN (the counterpart of `bills`): title, lead agency, priority category, current stage, whether it is a Regulatory Plan entry, abstract, planned timetable (JSON), legal authority, target CFR parts, first/last edition seen |
| `ua_entries` table | RIN × edition snapshots: one row per project per half-year (stage/plan flag/priority/timetable); comparing across editions yields the project's stage history |
| `oira_reviews` table | One row per review: RIN, which draft was reviewed (proposed/final), date received, date completed, the **decision** (e.g. Consistent with Change), economically-significant flag |
| `fr_documents` table | FR document ledger: document number (primary key), type/subtype, publication date, **effective date**, **comment closing date**, RIN (primary link) plus all RINs (JSON), docket, agencies (JSON), executive-order number, citation and pages, correction links, format URLs, folder path |
| `source_snapshots` table | Accounting for the raw agenda/review XML files: which source, which edition, file path, record count |
| `documents` table | Text files: one row per format, `entity_ref` pointing back to the document (e.g. `fr_documents:2026-00178`) |

File locations (two kinds):

```
01_raw/regulations/
├── fr/{year}/{docnum}/         ← one folder per FR document (year-sharded against bloat)
│   ├── detail.json             ← detail-endpoint mirror (for human inspection)
│   └── text/{raw.txt, full.xml}  ← the text in two formats
├── agenda/{edition}.xml        ← 60 agenda bulk files (no re-download to re-parse; several hundred MB for full history)
└── oira/{year}.xml             ← 46+ review bulk files
```

The three top folders `bills/ regulations/ guidance/` map one-to-one to the three `--source` values (layout spec 2026-09-01). Agenda/review bulk files are not "one policy's material" and do not go under fr/; their paths are accounted for in `source_snapshots`.

## 5. Full Case Walkthroughs (two real rules, as recorded in the ledger)

### Case 1: Removal of the NEPA implementing regulations (RIN 0331-AA10) — a fast rule that entered the agenda late, all four stages present

One RIN's journey from plan to final text (real-data example, all four stages recorded):

| Stage | Record |
|---|---|
| Agenda | First appears in the 2025 spring edition (**first published directly at Final Rule Stage** — fast rules can enter the agenda late; its interim rule had already been published); the 2025 fall edition marks it Completed Actions |
| OIRA review ① | Received 2025-02-16 → completed 2025-02-19 (interim draft, 3 days, Consistent with Change) |
| FR publication ① | 2025-02-25, document `2025-03014`, "Interim final rule; request for comments" (90 FR 10610), comments close 2025-03-27, effective 2025-04-11 |
| Corrections ×2 | 2025-03-05 `C1-2025-03014` (the `correction_of` column normalizes to `2025-03014`) + 2025-03-19 `2025-04640` (substantive correction) |
| OIRA review ② | Received 2025-08-11 → completed 2025-12-02 (final draft, **Consistent with Change**) |
| FR publication ② | 2026-01-08, document `2026-00178`, "Final rule" (91 FR 618), **effective the same day** |

Review completion (12-02) to publication (01-08) lines up exactly; all four FR documents share docket `CEQ-2025-0002`. In the ledger: 1 rulemakings row + 2 ua_entries rows + 2 oira_reviews rows + 4 fr_documents rows + 8 text files (txt/xml × 4) in their respective yearly folders.

### Case 2: USDA equal-participation rule for faith-based organizations (RIN 0503-AA90) — the standard "planned" path

An entry in the 2025 fall agenda (one of 3,954):

- Stage: Proposed Rule Stage; RIN_STATUS "**First Time Published in The Unified Agenda**"
- Timetable: NPRM targeted for November 2026 (`11/00/2026`, a month-granularity plan value)
- Priority Other Significant; amends 7 CFR Part 16; legal authority 5 U.S.C. 301 among others

This is the rhythm of most rules: enter the agenda → advance along the planned timetable → each draft passes OIRA → publish stage by stage. Once finished, a project **drops out of later agendas** — so telling "dead or done" apart requires multi-edition snapshot comparison (the purpose of ua_entries) and the status at its last appearance (Completed / Withdrawn / long-term).

The two cases together show: the RIN thread holds on all three sides (planning, review, publication); but an agenda's entry timing cannot be relied upon (it can be late or absent), which is why the data strategy uses the OIRA review record as the floor and the agenda as the planning supplement (see the caveats in 1.1).

## 6. How to Run

```bash
# Dry run (fetches nothing; shows what tasks would be enqueued)
python cli.py collect --country usa --source regulations \
    window=2026-08-17:2026-08-19 deep=all --dry-run

# FR small window, full deep crawl (~240 documents and ~730 requests for a 3-day window)
python cli.py collect --country usa --source regulations \
    window=2026-08-17:2026-08-19 deep=all

# Register only, no deep crawl (full index for a month costs 3 requests)
python cli.py collect --country usa --source regulations window=2026-07-01:2026-07-31

# Full lifecycle history (107 requests, ~300k rows, ~1GB of raw archives)
python cli.py collect --country usa --source regulations agenda=all oira=all

# Daily incremental (FR from the last cursor to today + refresh the under-review list)
python cli.py collect --country usa --source regulations sync=1 oira=all

# Status / snapshot / repair
python cli.py status --country usa --source regulations
python cli.py export --country usa
python cli.py requeue --country usa
```

## 7. Updates and Incremental Sync

- **FR chain**: no reopen mechanism (documents are immutable). Any window that is **fully swept** (plain window runs included) advances the kv cursor `fr_last_pub_date` to the window's end — FR is partitioned by date, so a completed sweep is complete (unlike congress-enumerated bills). `sync=1` sweeps cursor → today (with no cursor present you are asked to run an initial window first). Re-running the same window is safe: deterministic task IDs deduplicate and skip what is done; backfilling earlier dates moves the cursor backwards, which merely makes the next sync re-sweep a stretch — idempotent and harmless.
- **Agenda**: a new semiannual edition = a new edition parameter = a new task, so increments come naturally; old edition files never change — fetch once and it is a historical archive.
- **Reviews**: per-year history files are immutable; **the current-year file keeps growing** (YTD adds daily) and carries `RUNDATE` as its freshness signal — re-running re-fetches automatically when the signal is newer. The daily under-review list (`EO_RULES_UNDER_REVIEW.xml`) changes daily and works the same way.
- **Corrections**: a correction document is itself an ordinary FR document; the corrected document's `corrections` field links back from the detail endpoint. No revisit of already-fetched documents is needed.

## 8. Known Boundaries and Gaps

| Gap | Notes |
|---|---|
| **Comments and hearing records** | The regulations.gov docket (full public comments, hearing material) needs an api.data.gov key (free, default 1,000 requests/hour). The data path is open: every FR detail carries `regulations_dot_gov_url` + docket IDs. Listed as a future extension |
| **Line-by-line White House comments** | OIRA's specific edits to draft text are **not public** — FOIA only. What is public: the review records (dates + decision — crawled here), return-letter PDFs (rare, a few dozen since 2001, on the reginfo website), and meeting logs (XML only since 2024, web pages earlier) |
| **Agenda before fall 1995** | The reginfo electronic archive starts 1995-10; earlier regulatory plans exist only in FR paper archives. Interestingly, OIRA review records cover 1981 onward completely |
| Agenda entry timing | See case 1: a rule may first enter the agenda at the final-rule stage (with publications already existing); the OIRA review record fills in the early history |
| Multiple RINs on one document | One publication can bundle several projects (2 of ~400 sampled, e.g. `2026-17366` rescinding 3 RINs at once). Handling: the first RIN goes in the `rin` primary-link column, all of them in the `rins` JSON column |
| Missing RIN | Notice-type documents often carry no RIN; they can only be grouped by docket and stay out of the rulemakings project view |
| Large files | The largest single agenda XML is 17.6MB; the current transport has no size guard (harmless so far; will be recorded as a deviation if it ever bites) |
| status scope | `status` shows only the current `--source`'s domain tables (existing framework behavior); use sqlite directly or `export` to see everything |

## 9. Endpoint Quick Reference

| Purpose | URL pattern |
|---|---|
| FR document listing | `federalregister.gov/api/v1/documents.json?conditions[publication_date][gte]=…&[lte]=…&per_page=1000&page=N&fields[]=…` |
| FR document detail | `federalregister.gov/api/v1/documents/{document_number}.json` |
| FR filtered by RIN | listing endpoint + `conditions[regulation_id_number]=…` (officially supported) |
| FR text direct links | `raw_text_url` (txt) / `full_text_xml_url` (xml) / `pdf_url` (govinfo) from the detail response |
| One agenda edition | `reginfo.gov/public/do/XMLViewFileAction?f=REGINFO_RIN_DATA_{YYYYMM}.xml` (since 199510; 10 = fall, 04 = spring) |
| OIRA reviews for a year | same host, `?f=EO_RULE_COMPLETED_{YYYY}.xml` (since 1981) |
| OIRA rolling files | same host, `?f=EO_RULES_UNDER_REVIEW.xml` / `EO_RULE_COMPLETED_30_DAYS.xml` / `EO_RULE_COMPLETED_YTD.xml` (updated daily) |

**FR type vocabulary** (the `type` column): Rule / Proposed Rule / Notice / Presidential Document / Correction; presidential documents additionally carry a `subtype` (Proclamation / Determination / Memorandum, etc.; the executive-order number lives in `executive_order_number`).

---

*Last updated: 2026-09-01 (layout paths migrated; content unchanged since 2026-08-27)*
