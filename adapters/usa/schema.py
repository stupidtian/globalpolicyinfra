"""USA domain ledger: DDL and row-shape helpers.

Owned by the country pack (ARCHITECTURE.md section 6.2): table structure is
decided by this country's data. Migrations are additive-only; the schema
version lives in the ledger's kv under ``usa_schema_version``.

Tables:

- ``bills`` — one row per bill, merged from list pages (partial) and detail
  pages (full). ``folder`` records the bill's per-policy folder (every file
  of this bill lives there; the folder is the accounted path, §6.7).
- ``bill_actions`` — the lifecycle history; rewritten whole on every fetch
  (Congress may correct past records).
- ``votes`` — roll-call vote headers (question/result/party totals).
  Per-member votes are deferred (user decision 2026-08-25); when they come
  back they arrive as a new task type, no structural reservation needed.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "DOMAIN_KEYS",
    "DOMAIN_SCHEMA",
    "DOMAIN_TABLES",
    "SCHEMA_VERSION",
    "bill_folder",
    "bill_identity",
]

SCHEMA_VERSION = "1"

DOMAIN_SCHEMA = f"""
-- usa domain ledger, schema version {SCHEMA_VERSION} (additive migrations only)
CREATE TABLE IF NOT EXISTS bills (
    bill_id TEXT PRIMARY KEY,
    congress INTEGER NOT NULL,
    bill_type TEXT NOT NULL,
    number TEXT NOT NULL,
    title TEXT,
    introduced_date TEXT,
    sponsor_bioguide TEXT,
    sponsor_name TEXT,
    sponsor_party TEXT,
    sponsor_state TEXT,
    policy_area TEXT,
    latest_action_date TEXT,
    latest_action_text TEXT,
    api_update_date TEXT,
    terminal_status TEXT,
    summary_text TEXT,
    folder TEXT,
    raw_metadata TEXT NOT NULL DEFAULT '{{}}'
);
CREATE INDEX IF NOT EXISTS idx_bills_congress ON bills(congress, bill_type, number);

CREATE TABLE IF NOT EXISTS bill_actions (
    bill_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    action_date TEXT,
    action_type TEXT,
    action_code TEXT,
    action_text TEXT,
    committees TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (bill_id, seq)
);

CREATE TABLE IF NOT EXISTS votes (
    vote_id TEXT PRIMARY KEY,
    chamber TEXT NOT NULL,
    congress INTEGER NOT NULL,
    session INTEGER NOT NULL,
    roll_call_number INTEGER NOT NULL,
    vote_date TEXT,
    vote_question TEXT,
    vote_type TEXT,
    result TEXT,
    bill_id TEXT,
    legislation TEXT,
    party_totals TEXT NOT NULL DEFAULT '{{}}',
    source_url TEXT
);
"""

DOMAIN_TABLES: tuple[str, ...] = ("bills", "bill_actions", "votes")

#: Primary keys for the ledger's merge writes (UPDATE-first, section 6.2):
#: partial rows (e.g. a summary facet carrying only bill_id + summary_text)
#: merge into the existing record instead of tripping NOT NULL on insert.
DOMAIN_KEYS: dict[str, tuple[str, ...]] = {
    "bills": ("bill_id",),
    "bill_actions": ("bill_id", "seq"),
    "votes": ("vote_id",),
}


def bill_identity(congress: int, bill_type: str, number: str | int) -> tuple[str, str, str]:
    """Normalize to ``(bill_id, type_lower, number_str)``."""
    type_upper = str(bill_type).strip().upper()
    number_str = str(number)
    return f"USA_{int(congress)}_{type_upper}_{number_str}", type_upper.lower(), number_str


def bill_folder(congress: int, bill_type: str, number: str | int) -> str:
    """Per-policy folder (relative to the country root, §6.7): one folder
    per bill, sharded by congress so a single directory never holds
    hundreds of thousands of entries."""
    _, type_upper, number_str = bill_identity(congress, bill_type, number)
    return f"01_raw/policies/{int(congress)}/{type_upper.upper()}{number_str}"


def terminal_status_from_actions(actions: list[dict[str, Any]]) -> str | None:
    """Derive a bill's terminal state from its action history."""
    for action in actions:
        action_type = (action.get("action_type") or "").strip()
        text = (action.get("action_text") or "").lower()
        if action_type == "BecameLaw" or "became public law" in text:
            return "enacted"
        if "veto" in text and "override" not in text:
            return "vetoed"
    return None
