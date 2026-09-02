# USA Guidance Layer Notes — Commerce

> For the upstream overview see [guidance-en.md](./guidance-en.md). This document covers the three Commerce channels: the Bureau of Industry and Security (BIS), the National Weather Service (NWS), and the National Institute of Standards and Technology (NIST).
> Run figures below are real measurements (2026-08-31; the NIST channel 2026-09-01).

The United States Department of Commerce publishes its export-control rule revisions and Entity List changes in the Federal Register (covered by the regulations source); this layer collects what the department publishes directly on its own websites.

## 1. BIS (Bureau of Industry and Security): export-control interpretive guidance

**Site structure (forensics, 2026-08-31)**: the BIS website (bis.doc.gov) has been rebuilt as a dynamic application (Next.js), and `sitemap.xml` returns a HyperText Markup Language (HTML) page — **unusable**. But the guidance PDFs hang off a handful of **server-rendered listing pages** (for example `/licensing/country-guidance` hosts "Guidance on Advanced Computing Items" and its question-and-answer document). One task per listing page: every direct PDF link is recorded.

Pitfall: listing pages mix in site-administration files (SORN privacy notices, information-quality guidelines) — skipped by filename during listing processing.

```bash
python cli.py collect --country usa --source guidance agency=bis
```

Measured: 2 listing pages, 4 rows, 2 PDFs on disk.

## 2. NWS (National Weather Service): the directives system

**Site structure (forensics, 2026-08-31)**: `weather.gov/directives/` is a numbered directive tree — the index page lists ~11 series (`/directives/010` and so on), and each series page hangs directive PDFs as an unordered list inside the `<div class="cms-content">` block: `<li><a href="/media/directives/010_pdfs/pd01001curr.pdf">NDS 10-1 Title…</a></li>`. The anchor text is the title; **rescinded directives carry a "rescinded" marker in the title** (a red span), parsed into `status='withdrawn'` — currently the only channel in the guidance layer with a real lifecycle status column. The native id prefers the "NDS 10-1" pattern in the title, falling back to the filename.

```bash
python cli.py collect --country usa --source guidance agency=nws series=010   # one series
python cli.py collect --country usa --source guidance agency=nws              # all 11 series
```

Measured: series 010 alone brought in all 321 directives — 241 active + 56 rescinded, every PDF on disk. **Note: a single series can run to hundreds of documents; a first run over all series is on the order of thousands of requests.**

## 3. NIST (National Institute of Standards and Technology): a bibliographic snapshot channel

**Forensics (first probe 2026-08-31, corrected and finalized 2026-09-01)**: the website's browse pages are incomplete — the SP (Special Publication) series actually has 600+ documents but exposes only 37, and the FIPS (Federal Information Processing Standard) page shows 0; the official API domain (ctp.nist.gov) is unreachable. Probing then moved to the official GitHub repository `usnistgov/NIST-Tech-Pubs`, with two corrections to the earlier reading:

1. The repository's **default branch `nist-pages` is the website source**; the `xml/` directory holds only the 2020 archived bulk file (`allrecords_march312020.xml`, 53MB, stale) and journal XML — the earlier impression of a "per-record XML corpus" came from the legacy `master` branch layout and no longer holds.
2. The real bulk lives on **GitHub Releases**: one release per month (tags like `July2026`), carrying three assets — `allrecords-MODS.xml` (~84MB; MODS is the Metadata Object Description Schema, the Library of Congress metadata schema), `allrecords.xml` (~174MB, MARCXML machine-readable cataloging), and `readme.txt`. The export is produced by the NIST Research Library's Alma catalog, quality-checked by a metadata librarian, and covers bibliographic metadata for the entire NIST/NBS (National Bureau of Standards, NIST's predecessor) technical series. **We take the MODS version** (directly readable fields, half the size).

**Record structure (sampled)**: `<modsCollection>` holds ~13,000 `<mods>` records (84MB ÷ ~6.4KB per record). Field mapping per record:

| MODS field | Database column |
|---|---|
| `titleInfo/title` (with `nonSort` article) | `title` |
| `identifier[@type='doi']` (for example `10.6028/NIST.IR.6027`) | `native_id`, `url`, `file_url` (DOI resolves to full text) |
| `relatedItem[@type='series']/titleInfo` | `native_type` (series short code, for example "NIST SP") |
| `originInfo/dateIssued` (prefer the precise non-marc form "1997-06.") | `issued_date` |
| `subject/topic` first topic | `product_area` |
| `recordInfo/recordIdentifier` (Alma catalogue id) | `native_id` fallback when no DOI |

**native_id rule (pure function)**: DOI suffix dots become spaces — `NIST.SP.800-53r5` -> `NIST SP 800-53r5`, `NBS.CS.62-59` -> `NBS CS 62-59`. This is mechanical normalization of the official citable number; no semantics are guessed. Records without a DOI fall back to series title + volume number, then to the catalogue id with a `rec-` prefix.

**Series census (three 1MB segment samples, 751 records)**: every DOI is in NIST's own `10.6028` prefix (no external-journal DOIs — this corpus contains no journal articles); series include NIST IR/SP/TN/GCR/AMS/HB/NCSTAR and the NBS-era CS/CSM/TN/LCIRC/MP/MONO/BH/CIRC — more than 15 in total.

**doc_type rule (rule R1, source-native only)**: only FIPS maps to `STANDARD` (the series name is literally "Federal Information Processing **Standard**", and federal agencies are required by law to adopt them); everything else is `OTHER` — NIST's own description of SP is "a mixed reports-and-guidelines series" and IR is "research reports", so the series cannot prove a document's character one by one, and nothing is guessed. The series short code is kept verbatim in `native_type`, so later filtering loses nothing.

**Task shapes (snapshot mode, same as the Unified Agenda XML)**:

- `nist_latest`: one GitHub API call to get the newest release tag, spawning the download task for it;
- `nist_release_dl`: a single task does download -> archive (`01_raw/guidance/commerce/nist/catalog/{tag}.xml`, verbatim) -> parse -> rows + a `source_snapshots` entry.

**Increment semantics**: the task id embeds the release tag — re-running the same tag dedups to a no-op; each monthly tag is a new task, and rows upsert on `(agency, native_id)` so catalogue revisions merge naturally. No extra watermark is needed.

Pitfalls: (1) DOI fields carry trailing spaces — strip them; (2) series titles are variant strings ("NISTIR; NIST IR; NIST interagency report; …") — never key on them, always use the DOI suffix; (3) a few records have no series volume number (~0.5% in segment samples) — they take the catalogue-id fallback; (4) an 84MB single response is parsed in memory with iterparse, clearing only at record boundaries — the lesson is recorded in the regulations notes (clearing too early eats the child elements).

```bash
python cli.py collect --country usa --source guidance agency=nist            # latest release
python cli.py collect --country usa --source guidance agency=nist release=July2026   # pinned release
```

Measured (2026-09-01, July2026 release): the snapshot (84,260,460 bytes) archived verbatim; 20,355 records parsed, deduplicated by primary key (agency + native id) to **19,947 rows** — FIPS -> STANDARD 338, everything else OTHER 19,609; leading series: NIST IR 4,568, NBS IR 3,376, NBS RPT 1,808, **NIST SP 1,645**, NBS TN 1,311 (the two NIST/NBS eras together span the 1900s to 2026-07). Two requests in total (1 tag lookup + 1 download).

---

*Updated: 2026-09-01; data snapshot: BIS/NWS 2026-08-31 (live probing), NIST 2026-09-01 (July2026 release, fully ingested).*
