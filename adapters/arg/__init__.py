"""ARG country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The bora source (Boletín
Oficial de la República Argentina, the national gazette's primera sección)
is a flat document-shaped country path like DEU/bgbl, FRA/jorf and ESP/boe:
zero domain tables, documents only — collected from the site's own advanced
search data endpoint (session-free GET pagination by day) plus URL-addressed
detail pages and attachment PDFs.
"""

from adapters.arg.sources.bora import build_source as build_bora
from adapters.base import SourceDefinition

COUNTRY_CODE = "ARG"

SOURCES: dict[str, SourceDefinition] = {
    "bora": build_bora(),
}
