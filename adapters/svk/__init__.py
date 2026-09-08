"""SVK country pack: Slov-Lex (Zbierka zákonov, the Slovak Collection of Laws).

Flat document-shaped path (ARCHITECTURE.md section 6.4): one publication
event = one document, zero domain tables — the same gazette shape as
DEU/BGBl, FRA/JORF and ESP/BOE. Amendment/repeal references travel as raw
fields in meta; building the citation graph is an analysis-stage concern
(user ruling 2026-09-01).
"""

from adapters.base import SourceDefinition
from adapters.svk.sources.slovlex import build_slovlex

COUNTRY_CODE = "SVK"

SOURCES: dict[str, SourceDefinition] = {"slovlex": build_slovlex()}
