# USA Guidance Layer Notes — Treasury

> For the upstream overview see [guidance-en.md](./guidance-en.md) (institutional background, scope, doc_type tagging rules, task shapes). This document covers only Treasury's three channels: site forensics, parsing details, known pitfalls, commands.
> Run figures below are real small-sample measurements (2026-08-31).

The agency-direct policy documents of the United States Department of the Treasury come mainly from three bureaus: the Internal Revenue Service (IRS), the Office of Foreign Assets Control (OFAC), and the Office of the Comptroller of the Currency (OCC). OFAC sanctions designations and general licenses are published in the Federal Register (FR) — covered by the regulations source, not this layer.

## 1. IRS: the weekly Internal Revenue Bulletin

**Site structure (forensics, 2026-08-31)**: the `irs.gov/irb` index page is server-rendered and lists the most recent ~10 issues; each issue URL looks like `/irb/{year}-{week}_irb`, and the whole-issue PDF lives at `irs.gov/pub/irs-irbs/irb{YY}-{WW}.pdf` (that directory is also directly browsable and serves as the historical index).

**Issue-page markup** — the key forensic finding of this channel:

- the table of contents has a **two-level structure**: outer entries `<a href="#idN" class="text-overflow xmlbc-link">Title</a>`, each followed by nested entries `<a href="#NOT-2026-48">Notice 2026-48</a>` carrying the official identifier and a **semantic anchor**;
- the body area separates documents with `<a name="semantic-anchor">`, so the text can be sliced by anchor;
- one pitfall: interim documents and Treasury Decisions (TD) use different numbering — TDs are **sequential** (for example T.D. 10026), everything else is **year-based** (Notice 2026-48). The parsing regular expressions must accept both forms.

**Parse output**: one row per document (the native identifier is the primary key; doc_type maps by identifier: TD -> REGULATION, Notice/Rul./Proc. -> GUIDANCE, Announcement -> OTHER); the text slice goes into the row's `text_extracted` column plus a per-document fragment file `docs/{native_id}.html`; the whole-issue PDF is additionally kept as the official artifact.

```bash
# recent issues of the current year (each issue: ~5-10 documents + 1 whole-issue PDF)
python cli.py collect --country usa --source guidance agency=irs max_docs=2
# by issue-number window
python cli.py collect --country usa --source guidance agency=irs window=2026-30:2026-35
```

Known blemish: some documents' outer table-of-contents entry is a container title ("Part III"), so the row title falls back to the container name — the native identifier is the primary-key identity, so retrieval is unaffected.

## 2. OFAC: the sanctions question-and-answer library

**Site structure (forensics, 2026-08-31)**: `ofac.treasury.gov/sitemap.xml` is a single file with ~4,277 URLs, of which **991** are `/faqs/{number}` pages — the whole library is enumerable via the sitemap, no dynamic search interface needed. The answer text is **server-rendered** (inside the `ofac-faq-item` view field in the `region-content` block; the page's `<main>` block is pure navigation — do not parse from there). Pages carry no date; the sitemap's `<lastmod>` is passed through as `revised_date`.

```bash
python cli.py collect --country usa --source guidance agency=ofac max_docs=20   # small sample
python cli.py collect --country usa --source guidance agency=ofac              # full library, 991 entries
```

Measured sample: 15 rows with topic area (for example "Entities Owned by Blocked Persons (50% Rule)"), revision dates, and 1.1k–3k characters of text all recorded.

## 3. OCC: bank-supervision bulletins

**Site structure (forensics, 2026-08-31)**: `occ.gov/sitemap.xml` is a **root-level inline sitemap** (a single file inlining ~15,000 URLs — bulletins, press releases, PDFs mixed). Filtering `/news-issuances/bulletins/{year}/bulletin-{year}-{number}.html` yields the bulletin library. Bulletin pages are full-text HyperText Markup Language (HTML); the title is in `<title>` (strip the trailing "| OCC"); date markup is inconsistent ("Date Issued: August 24, 2026" / `datetime` attributes and other forms — the parser matches leniently across patterns).

One pitfall: the sitemap mixes in **pseudo-sitemap URLs** (for example `topics-sitemap.html` — it returns an HTML page) — child-sitemap detection must require a `.xml` ending (including the `?page=` variant), and non-sitemap responses are skipped as expected-empty.

```bash
python cli.py collect --country usa --source guidance agency=occ max_docs=12
```

Measured sample: 12 rows with real titles and dates (for example "Bank Supervision: Interagency Guidance on Lending…", 2026-07-13) and 2k–5k characters of text.

---

*Updated: 2026-09-01; data snapshot: 2026-08-31 (live probing + sample runs); the "measured" figures above are real run counts (commands for full-history windows are in the text).*
