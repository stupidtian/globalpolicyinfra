# United States (USA) — Source Guide: bills (Congressional Legislation)

> Counts in this file are measured reference values from real runs; your own output depends on the congress and window you choose.
> Prerequisite: familiarity with `python cli.py` at the repository root — no code reading required.
> This file covers the bills source alone; see [overview-en.md](./overview-en.md) for the USA source overview.
> This is the English edition of [bills-zh.md](./bills-zh.md); the Chinese original is authoritative.

## 1. Source Overview

US congressional legislation comes from the **official congress.gov API (v3)** — maintained by the Library of Congress, authoritative, structured, and free. A "congress" lasts two years; the current one is the 119th (since 2025-01). The bill API covers **the 93rd congress (1973) to the present**.

Key numbers (order-of-magnitude reference):

- Total bills in the 119th congress: **18,417** (250 per page, 74 enumeration pages)
- Each congress produces roughly 10–25 thousand bills; backfilling history (93rd–119th, 27 congresses) is an estimated 300–400 thousand
- Laws are not crawled separately: a law *is* a bill that finished the process — "Became Public Law" is simply the last entry of its action sequence

Data shape: pure API (JSON); full bill texts come as separately downloadable XML/HTML files.

## 2. Access Preparation

| Item | Notes |
|---|---|
| API key | **Required.** Free sign-up: https://api.congress.gov/sign-up/ (one minute) |
| Configuration | One line in the repo-root `.env` file: `CONGRESS_API_KEY=your-key` (`.env` is gitignored) |
| Rate limit | A production key allows 5,000 requests/hour; the DEMO_KEY used for debugging allows only 50/day and is not usable |
| Rate-limit behavior | Exceeding the limit returns 429; the framework backs off exponentially and slows down automatically — no data is lost |
| Anti-scraping | None. congress.gov is friendly to API calls |

## 3. What Gets Crawled: Task Types

Each task = one API request. Eight types are in use:

| Task type | Requests | Produces |
|---|---|---|
| `bill_list_page` | GET `/bill/119?offset=N&limit=250` | Ledger rows (one per bill) + the next-page task + qualifying deep-crawl tasks |
| `bill_detail` | GET `/bill/119/{type}/{number}` | Ledger enrichment (sponsor/policy area/folder) |
| `bill_actions` | GET `.../actions` | Lifecycle history (whole-list rewrite) + terminal-status derivation |
| `bill_summaries` | GET `.../summaries` | Full text of the official CRS summary |
| `bill_text` | GET `.../text` | Registers every text version as a document + one download task per version |
| `bill_text_dl` | GET version file URL (congress.gov) | Bill text XML/HTML written to disk |
| `vote_list_page` | GET `/house-vote/119/{session}?offset=N` | Vote rows + next page + detail tasks |
| `vote_detail` | GET `/house-vote/119/{session}/{roll}` | Vote header (question/result/party breakdown) |

Command-line parameters (key=value form):

```
congress=119            required, the congress number
deep=none|window|all    whether enumeration also deep-crawls (default none = register only)
window=FROM:TO          with deep=window: bills introduced or updated in the range
cases=ID[,ID...]        bills to deep-crawl regardless of the window
max_pages=N             cap the enumeration chain at N pages (test guardrail)
sessions=1,2            vote sessions to crawl
max_votes=N             cap vote-detail tasks per session (test guardrail)
sync=1                  incremental: enumerate only bills updated since the last cursor
```

## 4. Where the Data Lands

**Three domain tables + the documents table + one folder per bill**:

| Location | What it records |
|---|---|
| `bills` table | Bill ledger: number, title, sponsor (name/party/state/member ID), policy area, latest action, API update time, **terminal status** (enacted/vetoed/NULL = in progress), full summary text, folder path |
| `bill_actions` table | History: date, action code, original text, committee codes involved (rewritten whole per bill) |
| `votes` table | Vote headers: question, result, date, the bill voted on (bill_id backlink), party totals (e.g. R 208-0) |
| `documents` table | Bill text versions: one row per version, `entity_ref` pointing back to the bill (e.g. `bills:USA_119_S_98`) |
| `01_raw/policies/{congress}/{TYPE}{number}/` | All material of that bill (human-readable mirror; every path is accounted for in the ledger) |

Folder layout (real example, S 98):

```
01_raw/policies/119/S98/
├── detail.json          ← raw detail-endpoint response
├── actions.json         ← raw actions-endpoint response
├── summaries.json       ← raw summaries-endpoint response
├── votes/               ← votes held on this bill (raw responses)
└── text/
    ├── is.xml  8,314 B  ← introduced version (Introduced in Senate)
    ├── rs.xml  8,871 B  ← reported version
    ├── es.xml  8,272 B  ← Senate-passed version
    ├── enr.xml 8,951 B  ← enrolled version (both chambers agreed)
    └── version.html     ← public-law text (the official text after enactment)
```

## 5. Full Case Walkthrough: S 98 (Rural Broadband Protection Act of 2025)

One bill's journey from introduction to law (real-data example):

1. **Introduced**: 2025-01-15 by Sen. Capito, Shelley Moore [R-WV] (member ID C001047), policy area Science, Technology, Communications;
2. **Committee**: referred to the Commerce Committee on 2025-01-15 → committee report and Senate calendar placement on 2025-04-28 (**23 entries** in the action history);
3. **Votes**: (Senate votes are not in the API — see section 8; House votes on this bill appear in the `votes` table and backlink to it);
4. **Enacted**: the 2026-05-11 action `BecameLaw` — "Became Public Law No: 119-89"; the ledger's terminal status is automatically set to **enacted**, after which incremental sync stops revisiting it;
5. **Texts**: all 5 versions on disk (see the folder diagram above), 5 rows in documents, `entity_ref='bills:USA_119_S_98'`;
6. **Summary**: the CRS summary (1,306 characters) is stored in the ledger's `summary_text` column.

Contrast case HR 204 (ACRES Act): the same process caught mid-flight (Senate committee reported, placed on calendar), terminal status NULL — incremental sync will keep filling in its later actions as Congress progresses.

## 6. How to Run

```bash
# Dry run (fetches nothing; shows what would be enqueued)
python cli.py collect --country usa --source bills congress=119 max_pages=3 \
    deep=window window=2026-08-10:2026-08-24 --dry-run

# Small-scale run (~300 API requests)
python cli.py collect --country usa --source bills congress=119 max_pages=3 \
    deep=window window=2026-08-10:2026-08-24 \
    cases=USA_119_HR_204,USA_119_S_98 sessions=2 max_votes=20

# Full registration (ledger only, no deep crawl: 74 pages ≈ 3 minutes)
python cli.py collect --country usa --source bills congress=119 deep=none

# Deep-crawl all bills (in batches; ~4 requests per bill)
python cli.py collect --country usa --source bills congress=119 deep=all

# Incremental sync (revisits only bills with updates)
python cli.py collect --country usa --source bills congress=119 sync=1

# Status / snapshot / repair
python cli.py status --country usa --source bills
python cli.py export --country usa
python cli.py requeue --country usa        # un-fail failed tasks
```

## 7. Updates and Incremental Sync

- **Reopen rule**: every enumeration carries each bill's `updateDate` (the source-side freshness signal). A completed deep-crawl task is only reopened when the signal is newer than the recorded one; otherwise it is skipped. Re-running the same command is therefore safe and nearly free.
- **Sync cursor**: with `sync=1`, enumeration queries only bills updated after the `bills_last_sync` date in kv; the cursor advances to today when the last page is swept.
- **Terminal stop**: an action sequence containing "became public law" → enacted, a veto → vetoed; after a terminal state the source barely updates, so reopening naturally stops.
- **Two window semantics**: a `deep=window` match means the introduction date *or* the update date falls inside the window (either one); the two readings differ by an order of magnitude — choose deliberately.

## 8. Known Boundaries and Gaps

| Gap | Notes |
|---|---|
| **Senate votes** | API v3 has **no** Senate roll-call data (only House `house-vote`, marked beta). The Senate's official site publishes XML but blocks scripted requests (Akamai); a browser transport is planned, and the data will arrive as a new task type when it exists |
| Per-member vote detail | Deferred. The source is verified usable (response shape `houseRollCallVoteMemberVotes.results[]`); adding it = one new task type |
| Empty responses | "This bill has no summary / no text versions" is a **legitimate empty response**; the task is marked expected-empty — no warning, no failure archive |
| Public-law file name | The enacted version's file URL does not match the `BILLS-*` version-suffix rule, so it currently lands as `version.html` (cosmetic flaw; the fix is deriving the suffix from the URL) |
| Text opens blank? | Bill XML carries an `<?xml-stylesheet?>` reference; browsers render a blank page — the content is intact, use a text editor |

## 9. Endpoint Quick Reference

**In use (8)**: `/bill/{congress}`, `/bill/{c}/{type}/{n}`, `.../actions`, `.../text`, `.../summaries`, `/house-vote/{c}/{s}`, `/house-vote/{c}/{s}/{roll}`, and version-file direct links (congress.gov static files).

**Available but unused** (each = a future task type): cosponsors `cosponsors` (coalition networks), subject tags `subjects` (domain granularity), full title history `titles`, related bills `relatedbills` (policy diffusion), amendments `amendments` (legislative bargaining), committee and member master data (actor dimension), hearings `hearings`, committee reports `committee-report`, the Congressional Record `daily-congressional-record`, nominations `nominations`, treaties `treaties`, CRS reports `crsreport`.

**Not in the API at all**: per-vote Senate roll calls (see section 8), and texts of withdrawn bills (only the versions the API lists exist).

---

*Last updated: 2026-08-27*
