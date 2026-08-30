"""FRA country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The jorf source (Journal
officiel de la République française, the official gazette) is a flat
document-shaped country path like DEU/bgbl: zero domain tables, documents
only — but served as daily tar.gz snapshots from DILA's open-data directory
instead of per-entry PDFs.
"""

from adapters.base import SourceDefinition
from adapters.fra.sources.jorf import build_source as build_jorf

COUNTRY_CODE = "FRA"

SOURCES: dict[str, SourceDefinition] = {
    "jorf": build_jorf(),
}
