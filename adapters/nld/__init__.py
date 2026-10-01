"""NLD country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The bekendmakingen
source is a flat document-shaped gazette path like DEU/bgbl, FRA/jorf and
ESP/boe: zero domain tables, documents only — the Staatsblad publication
feed of the Dutch official announcements platform, collected from KOOP's
official SRU 2.0 API (no key, no session, no browser; the platform's own
documented bulk-access route).
"""

from adapters.base import SourceDefinition
from adapters.nld.sources.bekendmakingen import build_bekendmakingen

COUNTRY_CODE = "NLD"

SOURCES: dict[str, SourceDefinition] = {
    "bekendmakingen": build_bekendmakingen(),
}
