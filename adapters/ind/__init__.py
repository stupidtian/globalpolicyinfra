"""IND country pack (self-registered; see adapters/ind/sources/gazette/).
"""

from adapters.base import SourceDefinition
from adapters.ind.sources.gazette import build_source

COUNTRY_CODE = "IND"

SOURCES: dict[str, SourceDefinition] = {
    "gazette": build_source(),
}
