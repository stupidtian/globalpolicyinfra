"""USA country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The bills source
(congress.gov API v3, lifecycle crawl) is the reference implementation for
the task model; regulations (Federal Register + reginfo.gov) is the second
source and guidance (agency-direct documents) the third, all sharing the
same country-wide domain schema.
"""

from adapters.base import SourceDefinition
from adapters.usa.sources.bills import build_source as build_bills
from adapters.usa.sources.guidance import build_source as build_guidance
from adapters.usa.sources.regulations import build_source as build_regulations

COUNTRY_CODE = "USA"

SOURCES: dict[str, SourceDefinition] = {
    "bills": build_bills(),
    "regulations": build_regulations(),
    "guidance": build_guidance(),
}
