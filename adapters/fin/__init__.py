"""FIN country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The finlex source is the
**statute gazette layer** (säädöskokoelma) of Finlex — the Ministry of
Justice's official statute database — read from the free open-data REST API
on opendata.finlex.fi (no key, no session, no browser). See
docs/countries/fin/finlex-zh.md.
"""

from adapters.base import SourceDefinition
from adapters.fin.sources.finlex import build_source as build_finlex

COUNTRY_CODE = "FIN"

SOURCES: dict[str, SourceDefinition] = {
    "finlex": build_finlex(),
}
