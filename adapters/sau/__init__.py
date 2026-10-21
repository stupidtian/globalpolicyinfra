"""SAU country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``.

The uqn source collects Umm al-Qura (أم القرى), the official gazette of
Saudi Arabia, from its editorial site uqn.gov.sa: item-level pages for the
gazette's official section (قرارات وأنظمة — royal decrees/orders, council
of ministers and ministerial decisions, rules and regulations; full Arabic
text inline since the 2026 site rebuild) plus the per-issue PDFs (the only
full-text carrier before 2026). Flat document path like ESP/boe and
FRA/jorf: zero domain tables, ``documents`` is the whole ledger.
"""

from adapters.base import SourceDefinition
from adapters.sau.sources.uqn import build_source as build_uqn

COUNTRY_CODE = "SAU"

SOURCES: dict[str, SourceDefinition] = {
    "uqn": build_uqn(),
}
