"""GBR country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The ``leg`` source
(legislation.gov.uk, The National Archives) collects, per item of UK-wide
legislation, the as-enacted / as-made original CLML XML through the site's
website-as-API channel; the ``lex`` bulk source (lex.lab.i.ai.gov.uk re-
publishes the same corpus as parquet packages) is planned as a follow-up
batch and its columns are reserved in the shared ``items`` table.
"""

from adapters.base import SourceDefinition
from adapters.gbr.sources.leg import build_source as build_leg

COUNTRY_CODE = "GBR"

SOURCES: dict[str, SourceDefinition] = {
    "leg": build_leg(),
}
