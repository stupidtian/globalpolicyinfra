"""NZL country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The gazette source (New
Zealand Gazette / Te Kāhiti o Aotearoa, the official government gazette)
is a flat document-shaped path like ESP/boe and FRA/jorf: zero domain
tables, documents only — collected from the DigitalNZ aggregation API,
where the Gazette Office publishes notice metadata and full text as the
"New Zealand Gazette" collection (the gazette.govt.nz site itself sits
behind a commercial bot wall and disallows its search and PDF paths in
robots.txt, so the aggregation API is the sanctioned machine channel).
"""

from adapters.base import SourceDefinition
from adapters.nzl.sources.gazette import build_source as build_gazette

COUNTRY_CODE = "NZL"

SOURCES: dict[str, SourceDefinition] = {
    "gazette": build_gazette(),
}
