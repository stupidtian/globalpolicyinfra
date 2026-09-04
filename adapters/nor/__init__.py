"""NOR country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The lovtidende source
(Norsk lovtidende avdeling I — Norway's legal gazette for laws and
central regulations, published by Stiftelsen Lovdata on behalf of the
Ministry of Justice) is a flat document-shaped country path like
DEU/bgbl, FRA/jorf and ESP/boe: zero domain tables, documents only —
collected from Lovdata's official open-data bulk packages on
api.lovdata.no (NLOD 2.0, no key, no session; the www.lovtidende web
register is robots-disallowed and never touched).
"""

from adapters.base import SourceDefinition
from adapters.nor.sources.lovtidende import build_source as build_lovtidende

COUNTRY_CODE = "NOR"

SOURCES: dict[str, SourceDefinition] = {
    "lovtidende": build_lovtidende(),
}
