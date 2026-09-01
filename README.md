# GlobalPolicyInfra

> Policies. Lots of policies.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Purpose

Every person, every business, and every organization lives under formal governance. Because what
states legislate, regulate, and decide shapes economies and lives, knowing what each country's
government is actually doing matters to researchers and decision-makers alike.

Policy making and policy change, however, are evolving processes rather than single acts. A
proposal is first drafted, amended, and enacted, and the resulting law is then implemented
through regulation before it is corrected, extended, superseded, or repealed. Every step of
this evolution leaves a trace in an official document. Each country layers its own
differences on top of this complexity, because its institutions shape how the policy process
unfolds, its publication traditions decide where the evidence appears, and its languages and
legal concepts decide how it reads. What counts as one policy in one country may therefore
appear as a dozen documents in another, which is what makes cross-country comparison genuinely
hard. Yet no shared infrastructure exists that lays out the policy processes and policy
systems of different countries side by side, so every study has to build its own document
collection from scratch.

GlobalPolicyInfra (GPInfra) is an open infrastructure for doing this work once and together,
and it turns the policy documents that states officially publish, whatever the country,
portal, or format, into one comparable and traceable dataset. It watches the state through
what the state writes down.

## Background

### History

| Time | Milestone |
|---|---|
| 2025-06 | Project started |
| 2025-10 | First working prototype |
| 2026-04 | Scope had outgrown the prototype, so a redesign was planned |
| 2026-07 | Migration to the new architecture began |
| 2026-08 | First public release of the US bills and regulations collection |
| now | Open-sourcing more country sources, one at a time |

### Design

- **Documents are the unit.** Every document keeps a stable identity, its source, and its
  processing status, so anything derived from it can be traced back to the original.
- **Countries are plugins.** Each country is a self-contained pack that knows its own sources,
  while the framework does all fetching, storing, and accounting.
- **One engine, every stage.** The same engine that collects documents today will clean and
  structure them next.
- **A ledger per country, a table for research.** Each country's data lands in a local ledger,
  and one command exports a single analysis-ready table.
- **Resumable and repeatable.** An interrupted run picks up where it stopped, and finished work
  is never redone unless the source has changed.

## Requirements

- Python 3.11+
- An API key for sources that require one, usually free. Each source's guide
  (in [`docs/countries/`](docs/countries/)) states what it needs. Keys live in a local
  `.env` file, for which `.env.example` is the template, and they never enter the data or
  the repository.

## Quick start

Everything runs from a clone of the repository through one entry point, `python cli.py`.
The example below uses the bundled United States source, and the same commands work for every
country GPInfra supports.

```bash
git clone https://github.com/stupidtian/globalpolicyinfra.git
cd globalpolicyinfra

python -m pip install "pydantic>=2.0" "pandas>=2.0" "pyarrow>=15.0" "requests>=2.31"

python cli.py init --data-root /path/to/policy/data

# one month of the US Federal Register index, no API key needed
python cli.py collect --country usa --source regulations window=2026-07-01:2026-07-31

python cli.py status --country usa --source regulations
python cli.py export --country usa
```

`export` writes `policy_index.parquet`, which holds one row per document and is ready for
pandas or any other tool.

Each check confirms one more layer, so where the sequence stops tells you what is wrong.

| Check | Confirms | Command |
|---|---|---|
| Version prints | Python and dependencies are in place | `python cli.py --version` |
| Config resolves | GPInfra knows where your data lives | `python cli.py config` |
| Dry-run plans a collection | Source and parameters resolve, with nothing fetched | `python cli.py collect --country usa --source regulations window=2026-07-01:2026-07-31 --dry-run` |

> [!NOTE]
> Running the same `collect` command again is safe because completed work is skipped and
> documents are re-fetched only when the source reports a change.

## Roadmap

| Phase | Status |
|---|---|
| Collection, with more country sources open-sourced one by one | now |
| Cleaning, normalizing formats and extracting document text | next |
| Extraction, structuring policy content from documents | planned |
| Comparison, aligning content across countries into shared vocabularies | planned |

## License

[MIT](LICENSE)
