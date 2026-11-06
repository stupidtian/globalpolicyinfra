"""COL country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. Colombia contributes
two complementary sources (both flat document paths, zero domain
tables):

- ``suin``   — SUIN-Juriscol (Ministerio de Justicia), the normative
  registry: one norm's *current* consolidated state per document, from
  the key-free lexis.minjusticia.gov.co HTTP pair (public Elasticsearch
  metadata search + full-text API). Parallel-safe.
- ``diario`` — Diario Oficial de Colombia (Imprenta Nacional), the state
  gazette: one whole-issue PDF per document, from the Imprenta's JSF
  searcher via a session-bound chain. Serial (session semantics).
"""

from adapters.base import SourceDefinition
from adapters.col.sources.diario import build_source as build_diario
from adapters.col.sources.suin import build_source as build_suin

COUNTRY_CODE = "COL"

SOURCES: dict[str, SourceDefinition] = {
    "suin": build_suin(),
    "diario": build_diario(),
}
