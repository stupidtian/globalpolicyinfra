"""KOR country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The lawgokr source
(current statutes & decrees at www.law.go.kr) follows the flat
document-shaped path: zero domain tables, documents only — plus the
lifecycle pair confirmed by the user (2026-08-30): ``kor_versions``
(version lineage) and ``kor_reason`` (official amendment reasons).
"""

from adapters.base import SourceDefinition
from adapters.kor.sources.lawgokr import build_source as build_lawgokr

COUNTRY_CODE = "KOR"

SOURCES: dict[str, SourceDefinition] = {
    "lawgokr": build_lawgokr(),
}
