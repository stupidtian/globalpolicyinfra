"""DEU country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. Two sources share one
country ledger: bgbl (Bundesgesetzblatt Teil I, 1949-2022 paper-archive
scan PDFs) and ebgbl (the electronic gazette at recht.bund.de, 2023+).
Both are flat document-shaped: zero domain tables, documents only.
"""

from adapters.base import SourceDefinition
from adapters.deu.sources.bgbl import build_source as build_bgbl
from adapters.deu.sources.ebgbl import build_source as build_ebgbl

COUNTRY_CODE = "DEU"

SOURCES: dict[str, SourceDefinition] = {
    "bgbl": build_bgbl(),
    "ebgbl": build_ebgbl(),
}
