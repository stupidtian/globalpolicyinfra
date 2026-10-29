"""CZE country pack: e-Sbírka (Sbírka zákonů, the Czech Collection of Laws).

Flat document-shaped path (ARCHITECTURE.md section 6.4): one publication
event = one document, zero domain tables — the same gazette shape as
DEU/BGBl, FRA/JORF, ESP/BOE and SVK/Slov-Lex. Amendment/repeal references
and version timelines travel as raw fields in meta (or stay in the source's
open-data dumps for a future version-channel source); building the citation
graph is an analysis-stage concern (user ruling 2026-09-01).
"""

from adapters.base import SourceDefinition
from adapters.cze.sources.esbirka import build_esbirka

COUNTRY_CODE = "CZE"

SOURCES: dict[str, SourceDefinition] = {"esbirka": build_esbirka()}
