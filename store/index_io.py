"""Parquet analytical snapshot IO for the policy index.

Division of labor (ARCHITECTURE.md decision record 2026-08-19): SQLite holds
operational state; the parquet file at ``00_metadata/policy_index.parquet`` is
an **analytical snapshot** exported on demand (by the CLI) for cross-country
queries. The loop never reads it.

The snapshot's column definitions are deliberately deferred to Part 2
(ARCHITECTURE.md section 7). The only invariant enforced here is the spine:
every row must carry ``doc_id``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

__all__ = ["INDEX_KEY_COLUMN", "read_index", "write_index"]

INDEX_KEY_COLUMN = "doc_id"


def read_index(path: str | Path) -> pd.DataFrame:
    """Read the parquet snapshot. A missing file is an explicit error."""
    index_path = Path(path)
    if not index_path.is_file():
        raise FileNotFoundError(f"No policy index at {index_path}.")
    return pd.read_parquet(index_path)


def write_index(df: pd.DataFrame, path: str | Path) -> Path:
    """Write the parquet snapshot, enforcing the ``doc_id`` spine."""
    if INDEX_KEY_COLUMN not in df.columns:
        raise ValueError(
            f"A policy index must contain the spine column {INDEX_KEY_COLUMN!r}."
        )
    index_path = Path(path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(index_path, index=False)
    return index_path
