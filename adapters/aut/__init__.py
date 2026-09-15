"""AUT country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The ris source (RIS
OgdSearchResult API of the Austrian legal information system) is a flat
gazette-shaped country path like DEU/bgbl and ESP/boe: zero domain tables,
documents only — one BGBl entry is one document, collected from the
Bundeskanzleramt's open-data API (data.bka.gv.at): window search over the
BgblAuth (2004–, structured metadata era) and BgblPdf (1945–2003, scan era
with OCR full-text XML) applications plus one XML file per entry.
"""

from adapters.aut.sources.ris import build_source
from adapters.base import SourceDefinition

COUNTRY_CODE = "AUT"

SOURCES: dict[str, SourceDefinition] = {
    "ris": build_source(),
}
