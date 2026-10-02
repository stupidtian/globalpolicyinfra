"""POL country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. One source, ``isap``:
Poland's Dziennik Ustaw (the journal of laws) through the official Sejm
ELI API at api.sejm.gov.pl (key-free, stateless; probed 2026-09-20,
samples in the task folder — see docs/countries/pol/isap-zh.md). The
isap.sejm.gov.pl web application itself is Imperva-gated and robots-disallowed
and is NOT the channel; the ELI API is the machine mirror of the same corpus.
"""

from adapters.base import SourceDefinition
from adapters.pol.sources.isap import build_source

COUNTRY_CODE = "POL"

SOURCES: dict[str, SourceDefinition] = {
    "isap": build_source(),
}
