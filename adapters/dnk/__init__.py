"""DNK country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The retsinformation
source covers the official Danish legal database retsinformation.dk —
Lovtidende A/B (the printed gazette media, canonical ELI ``/eli/lta|ltb/``
paths = publication events = the time-series backbone) plus the native
version lineage (``/api/document/{id}/timeline``) for acts and consolidated
orders. Danish-language corpus first for this pack (``language="dan"``).
"""

from adapters.base import SourceDefinition
from adapters.dnk.sources.retsinformation import build_source

COUNTRY_CODE = "DNK"

SOURCES: dict[str, SourceDefinition] = {
    "retsinformation": build_source(),
}
