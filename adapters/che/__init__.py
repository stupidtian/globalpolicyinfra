"""CHE country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The fedlex source (the
Federal Chancellor's official legal publication platform) carries both
Swiss publication vehicles natively: the **AS** layer (Amtliche Sammlung /
Recueil officiel — the official collection, a gazette-shaped event stream,
the time-series backbone) and the **SR** layer (Systematische Sammlung /
Recueil systématique — the classified compilation of legislation in force,
a register with a point-in-time version lineage per entry). Both are read
through the platform's public SPARQL endpoint; files download from the
portal host's filestore via the URLs the graph itself provides.
"""

from adapters.base import SourceDefinition
from adapters.che.sources.fedlex import build_source as build_fedlex

COUNTRY_CODE = "CHE"

SOURCES: dict[str, SourceDefinition] = {
    "fedlex": build_fedlex(),
}
