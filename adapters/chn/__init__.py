"""CHN country pack: source, task types, cleaning declaration.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The gongbao source (the
State Council Gazette at www.gov.cn/gongbao) follows the flat gazette
path: zero domain tables, documents only — the gazette corpus has no
cross-document persistent entity and no native version lineage.
"""

from adapters.base import SourceDefinition
from adapters.chn.sources.gongbao import build_source as build_gongbao

COUNTRY_CODE = "CHN"

SOURCES: dict[str, SourceDefinition] = {
    "gongbao": build_gongbao(),
}
