"""RUS country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The pravo source collects
Russia's federally officialised legal acts from the official internet
portal of legal information (pravo.gov.ru): enumeration and document
identity come from the official-publication subsystem
(publication.pravo.gov.ru, date-addressed day search), full text comes
from the legal-text bank (actual.pravo.gov.ru, the successor of the old
ips.pravo.gov.ru interface) keyed by the same publication number. Flat
document path: zero domain tables, ``documents`` is the whole ledger.
"""

from adapters.base import SourceDefinition
from adapters.rus.sources.pravo import build_source

COUNTRY_CODE = "RUS"

SOURCES: dict[str, SourceDefinition] = {
    "pravo": build_source(),
}
