"""SVN country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The uradnilist source
collects Slovenia's official gazette *Uradni list Republike Slovenije*
(as-published, 1991-01-18 through today) as a flat document-shaped country
path like DEU/bgbl, ESP/boe and LVA/vestnesis: zero domain tables,
documents only. The gazette has no listing site of its own since the ZOUL
reform (2026-03-01 moved publication exclusively onto the government
legislation service's PISRS portal); PISRS serves the whole run — an
authoritative issue calendar, a day-addressed issue listing (each row
carrying the act's id, title, issuer, UL issue number and the as-published
PDF name) and the PDFs themselves — over one free JSON/HTTP API. Zero
domain tables, three task types. See docs/countries/svn/uradnilist-zh.md.
"""

from adapters.base import SourceDefinition
from adapters.svn.sources.uradnilist import build_source

COUNTRY_CODE = "SVN"

SOURCES: dict[str, SourceDefinition] = {
    "uradnilist": build_source(),
}
