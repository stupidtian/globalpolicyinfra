# USA Data Source Notes — guidance (agency-direct policy documents)

> The coverage and structural facts below are stable properties of the official sources (verified by live probing, 2026-08-31); real run counts per agency live in the "Measured" sections of the documents in §1.3.
> Prerequisite: familiarity with `python cli.py` usage only — no code reading needed. For the all-source USA overview see [overview-en.md](./overview-en.md).
> **One detail document per department** (site forensics, parsing notes, pitfalls, commands): see the pointer table in §1.3.

## 1. Source overview

### 1.1 What this layer is: the executive branch's third class of documents

United States federal policy output flows through three channels; the first two are already built:

```
Legislative   bills source        bills -> chamber votes -> law (congress.gov API)
Regulatory    regulations source  proposed rule -> White House review -> FR publication -> effective (FR API + reginfo.gov)
Agency-direct guidance source     policy documents agencies publish on their own websites  <- this source
```

**Agency-direct** means: an agency's official interpretation of how statutes or regulations apply (guidance), policy statements, procedure descriptions, official-voice question-and-answer pages (Frequently Asked Questions, FAQ), directives and bulletins to subordinate bodies, and government-wide circulars (Office of Management and Budget, OMB). These documents do not pass through Congress and do not follow the regulatory process in the Federal Register (FR). **There is no unified platform**: Executive Order (EO) 13891 of 2019 forced agencies to build central guidance repositories, but it was revoked in 2021 and the portals largely went offline. The current state is voluntary maintenance of uneven quality, with URLs drifting at each change of administration.

The legal character of this layer is **non-binding** (in theory it binds neither courts nor the public), yet its practical influence is enormous — one Food and Drug Administration (FDA) guidance decides how an industry files applications; one question-and-answer entry from the Office of Foreign Assets Control (OFAC) decides how sanctions are enforced.

### 1.2 Scope

**Collected**: official interpretations, policy statements, procedure guidance, question-and-answer pages, directives and bulletins, standards-type policy vehicles, OMB circulars and memoranda. **Binding regulatory instruments and data releases are also collected** (for example Treasury Decisions, TD, inside the Internal Revenue Bulletin, IRB) and separated by the `doc_type` tag for research-side filtering — missing a document costs more than over-collecting.
**Not collected**: Internal Revenue Service (IRS) letter rulings (outside the bulletin channel) and Financial Crimes Enforcement Network (FinCEN) advisories.

### 1.3 Agency list and department-document pointers

| Agency | Channel shape | Detail document |
|---|---|---|
| Treasury (IRS bulletin / OFAC FAQ / OCC bulletins) | gazette / sitemap / sitemap | [guidance-treasury-en.md](./guidance-treasury-en.md) |
| Commerce (BIS guidance / NWS directives / NIST bibliographic snapshot) | listing / numbered tree / snapshot | [guidance-commerce-en.md](./guidance-commerce-en.md) |
| Environmental Protection Agency (EPA guidance portal) | sitemap + three-stage classifier | [guidance-epa-en.md](./guidance-epa-en.md) |
| FDA / OMB / remaining 12 departments | method verified (FDA sitemap probe found 3,643 guidance pages) | later agencies |

The agency list is drawn by **policy salience** (not cabinet status): 15 departments plus cabinet-rank independent agencies to start; purely regulatory commissions are deferred. **When approaching any agency, the first action is to check `sitemap.xml`** — OFAC, EPA, and FDA successively verified that behind the "search wall" there is almost always a sitemap that enumerates the whole collection without a browser.

## 2. Access preparation

| Item | Notes |
|---|---|
| Keys | **None required**. All connected channels (irs.gov / ofac.treasury.gov / occ.gov / bis.doc.gov / weather.gov / epa.gov / github.com) are open access |
| Rate limits | None published; the framework throttles uniformly (0.5–1 s/request); EPA is the exception — it soft-throttles by hanging requests (see pitfall 4 in the EPA document) |
| Anti-scraping | None. Dynamic portals (FDA/EPA search interfaces) are bypassed via sitemaps, see §1.3 |

## 3. What gets fetched: task-shape table

One source, agencies as modules (the `agency=` parameter routes); eight task shapes cover every connected channel:

| Task type | Shape | Used by |
|---|---|---|
| `gz_index` / `gz_issue` | gazette index -> issues | IRS |
| `sitemap_page` | one sitemap page -> filter -> detail tasks | OFAC / OCC / EPA |
| `guid_page` | one document page -> row + attachment tasks | OFAC / OCC / EPA |
| `pdf_listing` | listing page with direct PDFs -> rows + downloads | BIS / NWS |
| `index_page` | index page -> child tasks | NWS series index |
| `guid_file_dl` | file download -> documents entry | all |
| `nist_latest` | GitHub API: newest release tag | NIST |
| `nist_release_dl` | one release snapshot: download + archive + rows | NIST |

Command-line parameters: `agency=irs|ofac|occ|bis|nws|epa|nist` (required), `window=FROM:TO` (IRS issue window), `year=YYYY`, `series=NNN` (one NWS series), `release=Tag` (pin one NIST release), `max_pages=N` / `max_docs=N` (test guardrails; `max_docs` is a whole-chain budget). Concrete commands live in the per-department documents.

## 4. Where the data lands

**One `guidance_documents` table** (primary key = agency + native id; `native_type` keeps the source string verbatim forever, `doc_type` uses the controlled vocabulary, `status` records draft/final/withdrawn, EPA adds `page_class`) + the `documents` table (one row per file format, `entity_ref` back-links) + one folder per document `01_raw/guidance/{department}/{agency}/{year}/{native_id}/` (standalone agencies like EPA have no department segment); a `department` column travels with every row.

**The five doc_type tagging rules**: map only source-native fields — with no native type the value is always OTHER, never guessed; channel labels are not semantic labels; the native type string is retained verbatim (re-tagging = re-derivation, never a refetch); the mapping is a pure function with unit tests; the vocabulary is controlled (`REGULATION / GUIDANCE / EXECUTIVE_ORDER / PRESIDENTIAL_DOCUMENT / BILL_TEXT / FAQ / BULLETIN / DIRECTIVE / STANDARD / CIRCULAR / MEMORANDUM / NEWS_RELEASE / OTHER`).

## 5. Updates and increments

- **Sitemap channels** (OFAC/OCC/EPA): rescanning the sitemap and diffing against the ledger is a natural increment;
- **Gazette channel** (IRS): each new issue is a new task; resume `window` from the last issue number;
- **Listing/tree channels** (BIS/NWS): rescan the listing pages; unchanged URLs are skipped;
- **Snapshot channel** (NIST): task ids embed the release tag — re-running the same tag is a no-op; each monthly tag is a new task;
- **Re-derivation**: when doc_type rules evolve, re-run the corresponding tasks (the native type string is already stored).

## 6. Known boundaries and gaps

| Gap | Notes |
|---|---|
| No unified platform | portal URLs drift between administrations; channel modules are written against the current layout and fixed when they break |
| Gray-zone items | press releases and policy statements carry no native type — channel-tagged, not force-labeled; research side filters |
| EPA soft throttling | after roughly 90–400 consecutive pages the server hangs requests (no 429 returned); run in slowed, staged passes — see pitfall 4 in the EPA document |
| Historical coverage | current administration's websites first; archives.gov for past administrations is deferred |

---

*Updated: 2026-09-01; data snapshot: 2026-08-31 (live probing) + 2026-09-01 (real runs across channels: 20,792 rows / 1,091 attachments total; EPA page remainder progressing in stages); details in each department document's "Measured" section.*
