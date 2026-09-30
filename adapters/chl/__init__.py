"""CHL country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The leychile source
(Ley Chile, the BCN legal database at leychile.cl / bcn.cl/leychile) is a
register-shaped corpus: one norma = one entity (``normas``), native version
lineage (``norma_versions``), documents hanging off the entity via
``entity_ref`` — 415,344 normas from 1850 to today, repealed ones included
(probed 2026-09-20).
"""

from adapters.base import SourceDefinition
from adapters.chl.sources.leychile import build_source as build_leychile

COUNTRY_CODE = "CHL"

SOURCES: dict[str, SourceDefinition] = {
    "leychile": build_leychile(),
}
