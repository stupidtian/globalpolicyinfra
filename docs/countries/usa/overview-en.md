# United States (USA) — Data Source Overview

> One file per source: this overview carries only shared information; each source has its own file.
> Naming rule: `{iso3}-{source}.md`; the nine-section writing structure is defined in [_template-en.md](../_template-en.md).
> This is the English edition of [overview-zh.md](./overview-zh.md); the Chinese original is authoritative.

## 1. Source Inventory

| Source | What it covers | Where the data comes from | Documentation |
|---|---|---|---|
| `bills` | The full congressional legislative process: introduction → committee → votes → enactment (action history, vote headers, all text versions) | Official congress.gov API v3 (free key required) | [bills-en.md](./bills-en.md) |
| `regulations` | The full executive-branch rulemaking lifecycle: planning (Unified Agenda) → White House review (OIRA) → publication in the Federal Register (proposed/final rules, corrections) → effective date | Federal Register API + reginfo.gov (neither needs a key) | [regulations-en.md](./regulations-en.md) |

The two sources run independently (`--source bills` / `--source regulations`) and share one `state.db`: the framework ledger (tasks/documents/kv/events) is common to both, while the domain tables (three for bills + five for regulations) are created by the USA country pack as a whole.

## 2. Shared Access Notes

| Item | Notes |
|---|---|
| Data directory | Configured via `python cli.py init` or the `POLICY_DATA_ROOT` environment variable; USA data lands in `{data_root}/USA_policy/` |
| API keys | Only bills needs one: put `CONGRESS_API_KEY=…` in `.env` (see section 2 of usa-bills.md). regulations needs no key at all |
| Common commands | `collect` (key=value params) / `status` / `export` / `requeue` / `reset` — all run from the repository root as `python cli.py …` |
| Pacing | The framework throttles uniformly (0.5–1 s random delay between requests) with triage-based retries; hitting a rate limit just slows things down, no data is lost |
| **Run one source at a time** | The country ledger hands out tasks by due time, while task handlers are registered per source — **before switching `--source`, confirm the previous source's queue is drained** (check the non-done task count with `python cli.py status`). Otherwise the other source's pending tasks are misjudged as handler-less permanent failures (fully recoverable via `requeue`, but best avoided) |

## 3. Policy Layers Not Yet Covered

| Layer | Status |
|---|---|
| Rulemaking comments / hearing records | regulations.gov (needs an api.data.gov key); the data path is already scouted (FR detail carries docket IDs and jump URLs) — listed as a future extension |
| Agency guidance | Not started (FDA and other agency portals; web-scraping type) |
| CFR (the codified end product) | Not started (the compilation layer after final rules take effect) |

---

*Last updated: 2026-08-27*
