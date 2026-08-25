"""USA country pack: sources, task types, domain schema.

Self-registered per ARCHITECTURE.md section 6.4: the registry scans this
package and reads ``COUNTRY_CODE`` + ``SOURCES``. The bills source (congress.gov
API v3, lifecycle crawl) is the reference implementation for the task model.
"""

from adapters.base import SourceDefinition
from adapters.usa.sources.bills import build_source

COUNTRY_CODE = "USA"

SOURCES: dict[str, SourceDefinition] = {
    "bills": build_source(),
}
