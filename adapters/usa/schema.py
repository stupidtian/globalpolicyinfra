"""USA domain ledger: DDL and row-shape helpers.

Owned by the country pack (ARCHITECTURE.md section 6.2): table structure is
decided by this country's data. Migrations are additive-only; the schema
version lives in the ledger's kv under ``usa_schema_version``.

bills source (v1):

- ``bills`` — one row per bill, merged from list pages (partial) and detail
  pages (full). ``folder`` records the bill's per-policy folder (every file
  of this bill lives there; the folder is the accounted path, §6.7).
- ``bill_actions`` — the lifecycle history; rewritten whole on every fetch
  (Congress may correct past records).
- ``votes`` — roll-call vote headers (question/result/party totals).
  Per-member votes are deferred (user decision 2026-08-25); when they come
  back they arrive as a new task type, no structural reservation needed.

regulations source (v2) — one RIN is the spine of a rulemaking's life:

- ``fr_documents`` — one row per Federal Register document (immutable once
  published; corrections are separate documents linked both ways).
- ``rulemakings`` — one row per RIN: the *latest* state of the project as
  seen by the newest agenda edition that mentions it (history lives in
  ``ua_entries``; first/last appearance = MIN/MAX over that table).
- ``ua_entries`` — RIN × agenda edition snapshots (stage evolution history).
- ``oira_reviews`` — one row per White House review (a RIN is typically
  reviewed once per draft: proposed, then final).
- ``source_snapshots`` — accounting for the raw agenda/OIRA XML files kept
  under 01_raw/regulations/ (every path must be in the ledger, §6.7).

guidance source (v3) — agency-direct policy documents (the layer that is
neither legislation nor FR rulemaking):

- ``guidance_documents`` — one row per document, keyed (agency, native_id)
  where native_id is the agency's own stable identifier (IRB document
  number, FAQ number, bulletin number, series number; URL-hash when the
  source has none). ``native_type`` keeps the source's own type string
  verbatim (re-tagging = re-derivation, never a refetch); ``doc_type``
  draws from the controlled vocabulary under tagging rules R1-R5;
  ``page_class`` (EPA-style sitemap classification) stays separate from
  doc_type by rule R5.
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
    "fr_doc_type",
    "fr_folder",
    "president_name",
    "yn_flag",
]

SCHEMA_VERSION = "4"

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

-- regulations source (schema v2) ------------------------------------------
CREATE TABLE IF NOT EXISTS fr_documents (
    document_number TEXT PRIMARY KEY,
    publication_date TEXT NOT NULL,
    title TEXT NOT NULL,
    type TEXT,
    subtype TEXT,
    action TEXT,
    abstract TEXT,
    citation TEXT,
    volume INTEGER,
    start_page INTEGER,
    end_page INTEGER,
    agencies TEXT NOT NULL DEFAULT '[]',
    president TEXT,
    executive_order_number TEXT,
    proclamation_number TEXT,
    effective_on TEXT,
    comments_close_on TEXT,
    dates_text TEXT,
    significant INTEGER,
    cfr_references TEXT NOT NULL DEFAULT '[]',
    rin TEXT,
    rins TEXT NOT NULL DEFAULT '[]',
    docket_ids TEXT NOT NULL DEFAULT '[]',
    topics TEXT NOT NULL DEFAULT '[]',
    correction_of TEXT,
    corrections TEXT NOT NULL DEFAULT '[]',
    regulations_gov_url TEXT,
    html_url TEXT,
    raw_text_url TEXT,
    full_text_xml_url TEXT,
    pdf_url TEXT,
    folder TEXT
);
CREATE INDEX IF NOT EXISTS idx_fr_documents_rin ON fr_documents(rin);
CREATE INDEX IF NOT EXISTS idx_fr_documents_pub ON fr_documents(publication_date);

CREATE TABLE IF NOT EXISTS rulemakings (
    rin TEXT PRIMARY KEY,
    title TEXT,
    lead_agency_code TEXT,
    lead_agency_name TEXT,
    parent_agency_name TEXT,
    agencies TEXT NOT NULL DEFAULT '[]',
    priority_category TEXT,
    current_stage TEXT,
    rin_status TEXT,
    is_plan_entry INTEGER,
    major INTEGER,
    abstract TEXT,
    timetable TEXT NOT NULL DEFAULT '[]',
    cfr TEXT NOT NULL DEFAULT '[]',
    legal_authority TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS ua_entries (
    rin TEXT NOT NULL,
    edition_id TEXT NOT NULL,
    rule_stage TEXT,
    rplan_entry INTEGER,
    priority_category TEXT,
    rin_status TEXT,
    title TEXT,
    timetable TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (rin, edition_id)
);

CREATE TABLE IF NOT EXISTS oira_reviews (
    rin TEXT NOT NULL,
    stage TEXT NOT NULL,
    date_received TEXT NOT NULL,
    date_completed TEXT,
    decision TEXT,
    agency_code TEXT,
    title TEXT,
    economically_significant INTEGER,
    major INTEGER,
    legal_deadline TEXT,
    source_file TEXT,
    PRIMARY KEY (rin, date_received, stage)
);

CREATE TABLE IF NOT EXISTS guidance_documents (
    agency TEXT NOT NULL,
    native_id TEXT NOT NULL,
    department TEXT,
    channel TEXT,
    native_type TEXT,
    doc_type TEXT,
    title TEXT,
    issued_date TEXT,
    revised_date TEXT,
    product_area TEXT,
    status TEXT,
    url TEXT,
    file_url TEXT,
    folder TEXT,
    page_class TEXT,
    text_extracted TEXT,
    PRIMARY KEY (agency, native_id)
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    source TEXT NOT NULL,
    edition TEXT NOT NULL,
    file_path TEXT,
    n_records INTEGER,
    run_date TEXT,
    PRIMARY KEY (source, edition)
);
"""

DOMAIN_TABLES: tuple[str, ...] = (
    "bills",
    "bill_actions",
    "votes",
    "fr_documents",
    "rulemakings",
    "ua_entries",
    "oira_reviews",
    "source_snapshots",
    "guidance_documents",
)

#: Primary keys for the ledger's merge writes (UPDATE-first, section 6.2):
#: partial rows (e.g. a summary facet carrying only bill_id + summary_text)
#: merge into the existing record instead of tripping NOT NULL on insert.
DOMAIN_KEYS: dict[str, tuple[str, ...]] = {
    "bills": ("bill_id",),
    "bill_actions": ("bill_id", "seq"),
    "votes": ("vote_id",),
    "fr_documents": ("document_number",),
    "rulemakings": ("rin",),
    "ua_entries": ("rin", "edition_id"),
    "oira_reviews": ("rin", "date_received", "stage"),
    "source_snapshots": ("source", "edition"),
    "guidance_documents": ("agency", "native_id"),
}


def bill_identity(congress: int, bill_type: str, number: str | int) -> tuple[str, str, str]:
    """Normalize to ``(bill_id, type_lower, number_str)``."""
    type_upper = str(bill_type).strip().upper()
    number_str = str(number)
    return f"USA_{int(congress)}_{type_upper}_{number_str}", type_upper.lower(), number_str


def bill_folder(congress: int, bill_type: str, number: str | int) -> str:
    """Per-policy folder (relative to the country root, §6.7): one folder
    per bill, sharded by congress so a single directory never holds
    hundreds of thousands of entries. Top level is the source name
    (``01_raw/bills/``), per the 2026-09-01 layout spec."""
    _, type_upper, number_str = bill_identity(congress, bill_type, number)
    return f"01_raw/bills/{int(congress)}/{type_upper.upper()}{number_str}"


def fr_folder(publication_date: str, document_number: str) -> str:
    """Per-policy folder for a Federal Register document: one folder per
    document, sharded by publication year (a modern year publishes ~28k
    documents), under the regulations source root (layout spec 2026-09-01)."""
    year = str(publication_date or "")[:4] or "undated"
    return f"01_raw/regulations/fr/{year}/{document_number}"


def fr_doc_type(
    fr_type: str | None,
    subtype: str | None = None,
    executive_order_number: str | int | None = None,
) -> str:
    """Map a Federal Register type to the cross-country doc_type vocabulary
    (soft per §5.1; the original type/subtype always travel in
    raw_metadata). Only a native executive_order_number makes a presidential
    document an EXECUTIVE_ORDER — proclamations, determinations and
    memoranda are PRESIDENTIAL_DOCUMENT (rule R1: never guess)."""
    kind = (fr_type or "").strip()
    if kind in ("Rule", "Proposed Rule"):
        return "REGULATION"
    if kind == "Presidential Document":
        if str(executive_order_number or "").strip():
            return "EXECUTIVE_ORDER"
        return "PRESIDENTIAL_DOCUMENT"
    return "OTHER"


def yn_flag(value: object) -> int | None:
    """reginfo yes/no fields → 1/0, None when absent."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("yes", "y", "true"):
        return 1
    if text in ("no", "n", "false"):
        return 0
    return None


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


def president_name(value: object) -> str | None:
    """FR carries ``president`` as ``{"identifier", "name"}``; older mirrors
    may use a plain string — accept both."""
    if isinstance(value, dict):
        name = value.get("name")
        return str(name) if name else None
    return str(value) if isinstance(value, str) and value else None
