"""BRA country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The dou source (Diário
Oficial da União, the Brazilian federal gazette, section 1 plus its extra
editions) is a flat document-shaped country path like ESP/boe and
ISL/stjornartidindi: zero domain tables, documents only — collected from
the gazette portal's per-day/per-section reading pages (an embedded JSON
item list) and one HTML detail page per item (see docs/countries/bra/
dou-zh.md). Reaching in.gov.br requires a proxy from some networks
(standard ``HTTPS_PROXY``, zero code changes).
"""

from adapters.base import SourceDefinition
from adapters.bra.sources.dou import build_source as build_dou

COUNTRY_CODE = "BRA"

SOURCES: dict[str, SourceDefinition] = {
    "dou": build_dou(),
}
