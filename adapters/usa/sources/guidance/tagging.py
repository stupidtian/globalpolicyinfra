"""doc_type tagging: the controlled vocabulary and its mappings (R1-R5).

Rules frozen in guidance-plan.md section 3:

- R1 source-native only — doc_type maps from the source's own official
  field/identifier; sources without a native taxonomy get OTHER, never a
  guess;
- R2 channel != semantics — at most a channel tag (NEWS_RELEASE, FAQ) for
  untyped sources; "is this a policy statement" is research-side judgment;
- R3 verbatim retention — the native type string always lands in
  raw_metadata/native_type, so re-tagging is a re-derivation, not a refetch;
- R4 mapping-as-code — pure functions, unit-tested;
- R5 controlled vocabulary — the value set below is the whole menu; adding
  a value is a deliberate act, and unstable classifications (EPA sitemap
  pages) live in page_class, not doc_type.
"""

from __future__ import annotations

__all__ = ["DOC_TYPES", "irb_doc_type"]

REGULATION = "REGULATION"
GUIDANCE = "GUIDANCE"
EXECUTIVE_ORDER = "EXECUTIVE_ORDER"
PRESIDENTIAL_DOCUMENT = "PRESIDENTIAL_DOCUMENT"
BILL_TEXT = "BILL_TEXT"
FAQ = "FAQ"
BULLETIN = "BULLETIN"
DIRECTIVE = "DIRECTIVE"
STANDARD = "STANDARD"
CIRCULAR = "CIRCULAR"
MEMORANDUM = "MEMORANDUM"
NEWS_RELEASE = "NEWS_RELEASE"
OTHER = "OTHER"

#: The complete doc_type menu (rule R5).
DOC_TYPES: tuple[str, ...] = (
    REGULATION,
    GUIDANCE,
    EXECUTIVE_ORDER,
    PRESIDENTIAL_DOCUMENT,
    BILL_TEXT,
    FAQ,
    BULLETIN,
    DIRECTIVE,
    STANDARD,
    CIRCULAR,
    MEMORANDUM,
    NEWS_RELEASE,
    OTHER,
)

#: IRB documents carry their own official identifier; map it verbatim (R1).
#: Treasury Decisions are binding regulation amendments -> REGULATION (the
#: cross-source duplicate with FR is accepted; doc_type filters it).
_IRB_TYPES: dict[str, str] = {
    "Treasury Decision": REGULATION,
    "T.D.": REGULATION,
    "Revenue Ruling": GUIDANCE,
    "Rev. Rul.": GUIDANCE,
    "Revenue Procedure": GUIDANCE,
    "Rev. Proc.": GUIDANCE,
    "Notice": GUIDANCE,
    "Announcement": OTHER,
}


def irb_doc_type(identifier: str) -> str:
    """doc_type for one IRB document identifier (e.g. ``Rev. Rul. 2026-14``,
    ``T.D. 10026`` — Treasury Decisions use sequential numbers)."""
    text = identifier.strip()
    # longest official prefix wins (Rev. Rul. before Rev.)
    for prefix in sorted(_IRB_TYPES, key=len, reverse=True):
        if text.startswith(prefix):
            return _IRB_TYPES[prefix]
    return OTHER
