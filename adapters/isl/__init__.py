"""ISL country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The stjornartidindi
source collects Iceland's official gazette *Stjórnartíðindi* (published
under the Act on the Official Gazette and the Law Gazette, No. 15/2005;
electronic publication is the legally effective one) as a flat
document-shaped country path like DEU/bgbl, ESP/boe and LVA/vestnesis:
zero domain tables, documents only. One source covers statutes (A deild),
executive regulations (B deild) and other official announcements
(C deild). Zero domain tables, three task types. See
docs/countries/isl/stjornartidindi-zh.md.
"""

from adapters.base import SourceDefinition
from adapters.isl.sources.stjornartidindi import build_source

COUNTRY_CODE = "ISL"

SOURCES: dict[str, SourceDefinition] = {
    "stjornartidindi": build_source(),
}
