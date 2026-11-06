"""PRT country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The dre source (Diário
da República, the Portuguese state gazette) is a flat document-shaped
country path like ESP/boe, DEU/bgbl and FRA/jorf: zero domain tables,
documents only — issue-level gazette documents collected from the
portal's JSON data services, plus targeted single-diploma detail fetches
by portal key.
"""

from adapters.base import SourceDefinition
from adapters.prt.sources.dre import build_source

COUNTRY_CODE = "PRT"

SOURCES: dict[str, SourceDefinition] = {
    "dre": build_source(),
}
