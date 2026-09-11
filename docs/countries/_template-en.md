# {Country Name} ({ISO3}) — Data Source Guide

> Seven style rules (follow them while writing): narrate in plain prose and keep code identifiers verbatim; define a term in everyday language the first time it appears, and expand every abbreviation at first occurrence (full name + abbreviation), abbreviating only afterwards; use only real data in examples (look numbers/dates/byte sizes up in the ledger and write them down — never invent); tables carry enumerable facts only, processes go as numbered steps; date-stamp every count (e.g. "measured 2026-08-25"); **no internal process vocabulary or internal paths in the body** (task briefs, phase codenames, adjudication language, agent session terms, links to non-published folders); assume a reader who only knows the command line and nothing about this project.
> **Audience (fixed 2026-08-30)**: the first reader is an outside open-source user; internal construction reuses the same file — remove internal traces, not technical depth.
> **File set (acceptance items)**: every country ships `overview-en.md` plus one file per source; no section may be dropped (write why if not applicable); a mandatory closing block: `*Updated: YYYY-MM-DD; data snapshot: YYYY-MM-DD; figures backed by {which run/window}.*`
> This is the English edition of [_template-zh.md](./_template-zh.md); the Chinese original is authoritative.

## 1. Source Overview

(Where this country's data comes from: the official institution, URLs, the legal status of the data; coverage and key numbers — how many policies, spanning which years; whether the source is an API or web pages, and whether full text is inline.)

## 2. Access Preparation

(Whether an API key is needed: if yes — where to register (with link), the quota (requests per hour), which `.env` variable to set; if no — say "no key needed". Any anti-scraping, which transport is required.)

## 3. What Gets Crawled: Task Types

(The direct answer to "how is the API used, which endpoints exist". One table: task type → what it requests (endpoint/page) → what each run produces.)

| Task type | Requests | Produces |
|---|---|---|
| … | … | … |

## 4. Where the Data Lands

(Column-by-column account of the domain tables (which tables exist, what each records); what the documents table carries; a folder-layout diagram — what one policy's folder looks like.)

## 5. Full Case Walkthrough

(Walk one real policy through every part of the dataset end to end: the ledger row, the history, the text versions, the linked votes — every number verifiable from state.db. After reading this section the reader has "seen" the whole dataset.)

## 6. How to Run

(Commands that can be copied and run as-is: first collection / small-scale trial / incremental sync / dry run / status / repair channel.)

## 7. Updates and Incremental Sync

(How the sync cursor advances and under which key; when a policy counts as "terminal" and is no longer revisited; the reopen rule — how a source-side freshness signal triggers re-fetching.)

## 8. Known Boundaries and Gaps

(Put the pitfalls in plain sight: which data the source does not have, what was deferred, which empty responses are normal, anti-scraping conditions.)

## 9. Endpoint Quick Reference

(Appendix one: every endpoint in use. Appendix two: the menu of endpoints/information the source offers but we do not yet use — one sentence of research value per item.)
