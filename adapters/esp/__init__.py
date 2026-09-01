"""ESP country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The boe source (Boletín
Oficial del Estado, the Spanish state gazette) is a flat document-shaped
country path like DEU/bgbl and FRA/jorf: zero domain tables, documents
only — collected from BOE's on-site open-data API (date-addressed daily
summary + one-XML-per-item detail carrying metadata, analysis and full
text in a single response).
"""

from adapters.base import SourceDefinition
from adapters.esp.sources.boe import build_source as build_boe

COUNTRY_CODE = "ESP"

SOURCES: dict[str, SourceDefinition] = {
    "boe": build_boe(),
}
