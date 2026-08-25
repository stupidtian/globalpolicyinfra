# GlobalPolicyInfra

An open-source infrastructure for cross-country public policy document collection, cleaning, extraction, and comparison.

## Vision

Turn heterogeneous government policy documents from around the world into structured, comparable, and source-grounded knowledge graphs.

## Status

Pre-alpha. The project is under active design and development.

## Getting Started

GPI is a **clone-and-run application**: you run it from a checkout of this
repository — it is never installed as a package and never imported as a
library.

```bash
git clone https://github.com/yangzhaotian/globalpolicyinfra.git
cd globalpolicyinfra

# Python >= 3.11 with the runtime dependencies available, e.g.:
python -m pip install "pydantic>=2.0" "pandas>=2.0" "pyarrow>=15.0"

# Secrets (no consumers yet in v1): copy the template and fill in your keys.
cp .env.example .env

# Everything runs through the repository-root CLI:
python cli.py --version
python cli.py init --data-root /path/to/policy/data
python cli.py config
```

`gpi init` records your data root in `~/.globalpolicyinfra/config.toml` (or set
the `POLICY_DATA_ROOT` environment variable); `gpi config` shows the resolved
value. See [ARCHITECTURE.md](./ARCHITECTURE.md) for the design and
[ARCHITECTURE.md §7](./ARCHITECTURE.md) for how to add an adapter for your own
country.

## Development

```bash
python -m pip install "pydantic>=2.0" "pandas>=2.0" "pyarrow>=15.0" \
    "pytest>=8.0" "ruff>=0.4.0" "mypy>=1.0" "pandas-stubs>=2.0"

python -m pytest     # test suite
python -m ruff check # lint
python -m mypy       # type check
```

## License

MIT
