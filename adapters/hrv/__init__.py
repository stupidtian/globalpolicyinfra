"""HRV country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The nn source collects
the Službeni dio (official part) of Narodne novine — Croatia's official
gazette, published by the state-majority company Narodne novine d.d. and
addressed via ELI on the NN Tražilica platform (narodne-novine.nn.hr).
Gazette-shaped flat source like DEU BGBl / FRA JORF / ESP BOE: zero domain
tables, one document per published item, body carried by the item HTML page
(1990-2022) or the per-item digital-native PDF (2023+, where the HTML body
is back-filled with a lag). Croatian (hr) is a first language for the
project. Court and judicial-council issuers are out of the default corpus
(scope=policy). See docs/countries/hrv/nn-zh.md.
"""

from adapters.base import SourceDefinition
from adapters.hrv.sources.nn import build_source

COUNTRY_CODE = "HRV"

SOURCES: dict[str, SourceDefinition] = {
    "nn": build_source(),
}
