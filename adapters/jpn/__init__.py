"""JPN country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The kanpo source (官報,
the Japanese government gazette run by the Cabinet Office / National
Printing Bureau) is a flat document-shaped country path like DEU/bgbl,
FRA/jorf and ESP/boe: zero domain tables, documents only - collected from
the gazette portal's static HTML indexes and directly-addressable PDFs
(see docs/countries/jpn/kanpo-zh.md).
"""

from adapters.base import SourceDefinition
from adapters.jpn.sources.kanpo import build_source as build_kanpo

COUNTRY_CODE = "JPN"

SOURCES: dict[str, SourceDefinition] = {
    "kanpo": build_kanpo(),
}
