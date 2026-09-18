"""LTU country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The tad source (Teisės
aktų duomenų bazė — the Seimas-hosted legal-acts database) is a flat
document-shaped country path like DEU/bgbl and ESP/boe: zero domain
tables, documents only. Lithuania's official publication medium since
2014 is the TAR register (e-tar.lt), which sits behind a Cloudflare
browser challenge; this source instead collects the Seimas system's
TAR-registered mirror (three stateless GET layers: legacy search on
www.lrs.lt, document detail via showdoc redirect to e-seimas.lrs.lt, and
the /rs/ legalact text service). See docs/countries/ltu/tad-zh.md.
"""

from adapters.base import SourceDefinition
from adapters.ltu.sources.tad import build_source as build_tad

COUNTRY_CODE = "LTU"

SOURCES: dict[str, SourceDefinition] = {
    "tad": build_tad(),
}
