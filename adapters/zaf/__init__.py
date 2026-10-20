"""ZAF country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The govza source collects
the documents portal of the South African government website (gov.za,
operated by the Government Communication and Information System) — the
official web channel that mirrors the Government Gazette (Staatskoerant,
published on paper and online by the Government Printing Works, the two
editions legally co-equal since the 2012/13 amendments) together with the
other policy layers the portal indexes: Acts, Bills, draft bills, green and
white papers. Flat document-shaped country path like DEU/bgbl, ESP/boe and
ISL/stjornartidindi: zero domain tables, documents only. See
docs/countries/zaf/govza-zh.md.
"""

from adapters.base import SourceDefinition
from adapters.zaf.sources.govza import build_source

COUNTRY_CODE = "ZAF"

SOURCES: dict[str, SourceDefinition] = {
    "govza": build_source(),
}
