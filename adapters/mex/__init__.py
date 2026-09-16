"""MEX country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The dof source (Diario
Oficial de la Federación, the Mexican federal gazette) is a flat
document-shaped country path like ESP/boe and ARG/bora: zero domain
tables, documents only — collected from the gazette's own date-addressed
daily-edition HTML (the machine web services the site once carried are
gone, probed 2026-09-14; the edition page is the only authoritative
listing).
"""

from adapters.base import SourceDefinition
from adapters.mex.sources.dof import build_source as build_dof

COUNTRY_CODE = "MEX"

SOURCES: dict[str, SourceDefinition] = {
    "dof": build_dof(),
}
