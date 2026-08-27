"""DEU country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The bgbl source
(Bundesgesetzblatt Teil I, 1949-2022 frozen archive) is the pilot for the
flat document-shaped country path: zero domain tables, documents only.
"""

from adapters.base import SourceDefinition
from adapters.deu.sources.bgbl import build_source as build_bgbl

COUNTRY_CODE = "DEU"

SOURCES: dict[str, SourceDefinition] = {
    "bgbl": build_bgbl(),
}
