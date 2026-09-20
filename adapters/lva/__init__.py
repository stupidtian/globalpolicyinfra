"""LVA country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The vestnesis source
collects Latvia's official publication *Latvijas Vēstnesis* (vestnesis.lv,
the official gazette defined by the Law on Official Publications and Legal
Information) as a flat document-shaped country path like DEU/bgbl, ESP/boe
and LTU/tad: zero domain tables, documents only. The gazette site has no
date-addressed directory of its own, so enumeration uses the same
publisher's consolidated-law site likumi.lv (day-addressed "jaunākie"
listing on the publication-date axis); the two sites share one document id
namespace, and each listing row carries the gazette document id that the
document task then fetches. Zero domain tables, two task types. See
docs/countries/lva/vestnesis-zh.md.
"""

from adapters.base import SourceDefinition
from adapters.lva.sources.vestnesis import build_source

COUNTRY_CODE = "LVA"

SOURCES: dict[str, SourceDefinition] = {
    "vestnesis": build_source(),
}
