"""EST country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The riigiteataja source
collects Estonia's official gazette Riigi Teataja (riigiteataja.ee,
operated by the Ministry of Justice and Digital Affairs; purely electronic
publication since 2010) as a flat registry-shaped country path like
LVA/vestnesis and ISL/stjornartidindi: zero domain tables, documents only.
The corpus spans the as-published layer (algtekst) and the officially
consolidated layer (terviktekst) in one version-granular inventory; Estonia
is the first Finno-Ugric language in the project (est). See
docs/countries/est/riigiteataja-zh.md.
"""

from adapters.base import SourceDefinition
from adapters.est.sources.riigiteataja import build_source

COUNTRY_CODE = "EST"

SOURCES: dict[str, SourceDefinition] = {
    "riigiteataja": build_source(),
}
