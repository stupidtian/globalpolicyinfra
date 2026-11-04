"""PER country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The elperuano source
collects the Diario Oficial El Peruano's Normas Legales supplement (the
statutory publication medium, Editora Perú, gazette founded 1825) from
1997-07 onward: legacy-era whole-edition PDFs (1997-07 to 2023-08) and
portal-era per-norm device pages (2023-09 onward), era decided per entry
by link shape. Flat gazette corpus — zero domain tables.
"""

from adapters.base import SourceDefinition
from adapters.per.sources.elperuano import build_source as build_elperuano

COUNTRY_CODE = "PER"

SOURCES: dict[str, SourceDefinition] = {
    "elperuano": build_elperuano(),
}
