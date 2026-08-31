"""AUS country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The frl source (Federal
Register of Legislation, the Commonwealth register of legislation) is a
register-shaped, entity-backed path: every title (an Act or instrument) is
a persistent entity with a version lineage, carried by the ``titles`` /
``title_versions`` domain tables with documents hanging off
``entity_ref = titles:{title_id}``.
"""

from adapters.aus.sources.frl import build_source as build_frl
from adapters.base import SourceDefinition

COUNTRY_CODE = "AUS"

SOURCES: dict[str, SourceDefinition] = {
    "frl": build_frl(),
}
