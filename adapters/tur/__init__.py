"""TUR country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. Turkey is a Presidency
pair — the gazette (publication flow, flat document path like ESP/boe)
and the consolidated-current legislation registry (entity path like
KOR/lawgokr, one ``mevzuat`` row per regulation keyed on the site's
(MevzuatTur, MevzuatNo, MevzuatTertip) triple). Both endpoints key-free
and cookie-free (probed 2026-09-27; see docs/countries/tur/).
"""

from adapters.base import SourceDefinition
from adapters.tur.sources.mevzuat import build_source as build_mevzuat
from adapters.tur.sources.resmigazete import build_source as build_resmigazete

COUNTRY_CODE = "TUR"

SOURCES: dict[str, SourceDefinition] = {
    "resmigazete": build_resmigazete(),
    "mevzuat": build_mevzuat(),
}
