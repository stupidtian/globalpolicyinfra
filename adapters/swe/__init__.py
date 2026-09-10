"""SWE country pack: SFS (Svensk författningssamling) via Riksdagen.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The riksdagen source is
a flat document-shaped gazette path like DEU/bgbl, FRA/jorf, ESP/boe and
SVK/slovlex: zero domain tables, documents only — collected from the
Riksdagen open-data API, which republishes the Government Office's
författningsregister (every text header self-identifies ``Källa:
Regeringskansliet / Lagrummet``).
"""

from adapters.base import SourceDefinition
from adapters.swe.sources.riksdagen import build_riksdagen

COUNTRY_CODE = "SWE"

SOURCES: dict[str, SourceDefinition] = {
    "riksdagen": build_riksdagen(),
}
