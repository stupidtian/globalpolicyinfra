# GlobalPolicyInfra

Open-source infrastructure for collecting, cleaning, and comparing public policy documents across countries — turning heterogeneous government sources into structured, source-grounded datasets.

Every collected document gets a stable identifier, provenance, and a per-stage status. Whatever the country, the pipeline leaves you with the same thing: an auditable ledger and one parquet table you can load with pandas.

> **Status: pre-alpha, under active development.** The collection engine and the first source — United States bills via the official [congress.gov API](https://api.congress.gov/) — are working end to end. Cleaning and extraction stages are designed but not yet built. Expect breaking changes.

## Requirements

- Python 3.11+
- An API key for each source you collect. Currently one: a free [congress.gov API key](https://api.congress.gov/sign-up/) (takes a minute).

## Quick start

GPI runs from a clone of this repository through a single entry point, `python cli.py`:

```bash
git clone https://github.com/yangzhaotian/globalpolicyinfra.git
cd globalpolicyinfra

# Python dependencies
python -m pip install "pydantic>=2.0" "pandas>=2.0" "pyarrow>=15.0" "requests>=2.31"

# API keys live in .env (gitignored); .env.example is the template
cp .env.example .env

# Tell GPI where collected data should live (writes ~/.globalpolicyinfra/config.toml)
python cli.py init --data-root /path/to/policy/data

# Preview a collection run: what would be enqueued, nothing fetched
python cli.py collect --country usa --source bills congress=119 max_pages=2 --dry-run

# Register the full 119th Congress bill inventory (ledger only, ~3 minutes)
python cli.py collect --country usa --source bills congress=119 deep=none

# ...or deep-crawl the bills introduced or updated in a date window
python cli.py collect --country usa --source bills congress=119 \
    deep=window window=2026-08-10:2026-08-24

# Check the ledger, then export the analytical snapshot
python cli.py status --country usa --source bills
python cli.py export --country usa
```

The data root can also be set via the `POLICY_DATA_ROOT` environment variable; `python cli.py config` prints the resolved value. Re-running any `collect` command is safe: completed work is skipped, and finished items are only re-visited when the source reports an update.

## The data you get

Each country is written under `{data_root}/{ISO3}_policy/`:

```
USA_policy/
├── state.db                          # SQLite ledger: tasks, documents, audit events,
│                                     #   plus country-specific tables (bills, votes, ...)
├── 01_raw/policies/119/S98/          # one folder per bill: raw API responses + text versions
└── 00_metadata/policy_index.parquet  # exported snapshot: one row per document
```

`state.db` is the operational ledger — resumable, incremental, auditable. The parquet snapshot is the research interface:

```python
import pandas as pd

df = pd.read_parquet("/path/to/policy/data/USA_policy/00_metadata/policy_index.parquet")
df[["doc_id", "title", "publication_date", "doc_type", "source_url"]].head()
```

For what the USA source collects, its domain tables (`bills`, `bill_actions`, `votes`), and every collection parameter, see [docs/countries/usa.md](docs/countries/usa.md).

## How it works

Every unit of work — fetch a list page, fetch a bill's detail, download a text version — is a **task** in the country's SQLite ledger. One loop engine repeatedly takes a due task, executes it, and commits the results, follow-up tasks, and cursor updates in a single transaction.

- **Resumable and idempotent** — task identity is deterministic (`sha256(type + params)`), so a crashed run picks up where it stopped and duplicate work de-duplicates itself.
- **Incremental** — items are re-visited only when their source-side update signal changes.
- **Three-way error handling** — transient failures retry with backoff, permanent failures are recorded as failed, and unknown failures are escalated (`needs_agent` / `needs_human`) instead of being silently dropped.
- **Country packs are pure functions** — a country declares its sources and, for each task type, a `build_request` and a `parse` function. All I/O (HTTP, retries, rate limits, key injection, storage, accounting) belongs to the framework, so every country inherits the same reliability for free.

## Adding a country

Country packs self-register under `adapters/{iso3}/`; adding one touches no framework code.

1. Read the per-country documentation template ([docs/countries/_template.md](docs/countries/_template.md)) and the reference pack: [USA](docs/countries/usa.md) (source: [`adapters/usa/`](adapters/usa/)).
2. Create `adapters/{iso3}/` declaring `COUNTRY_CODE` and its `SOURCES`.
3. For each source, write `start_tasks(params)` to turn CLI arguments into seed tasks, plus a `build_request` / `parse` pair per task type; declare domain tables if the source has them.

## CLI reference

| Command | Purpose |
|---|---|
| `init` | Record the data root in the global config |
| `config` | Print the resolved data root |
| `collect` | Run a country source's task pipeline (`--dry-run` previews without fetching) |
| `status` | Ledger counts for a country |
| `export` | Write the `policy_index.parquet` snapshot |
| `requeue` / `reset` | Repair channel for failed or escalated tasks |
| `events-archive` | Archive old audit events to `.jsonl.gz` |

Every command: `python cli.py <command> --help`.

## Development

```bash
python -m pip install "pydantic>=2.0" "pandas>=2.0" "pyarrow>=15.0" "requests>=2.31" \
    "pytest>=8.0" "ruff>=0.4.0" "mypy>=1.0" "pandas-stubs>=2.0" "types-requests>=2.31"

python -m pytest       # test suite
python -m ruff check   # lint
python -m mypy         # type check (strict)
```

Tests never touch the network or real data; adapters are tested against small synthetic fixtures.

## Roadmap

- **Collection** (current focus) — engine complete; USA bills is the working reference source; more US sources and a second pilot country are in progress.
- **Cleaning** — format normalization and body extraction over the collected raw documents.
- **Extraction & comparison** — structured extraction aligned to a shared cross-country ontology.

## License

[MIT](LICENSE)
