"""The guidance source: agency-direct policy documents.

One source, agencies as modules (``agency=`` routes to a profile)::

    python cli.py collect --country usa --source guidance agency=irs year=2026
    python cli.py collect --country usa --source guidance agency=ofac max_docs=50
    python cli.py collect --country usa --source guidance agency=occ

Task types (agency knowledge lives in profiles, see common.py)::

    gz_index / gz_issue   gazette chain (IRS IRB weekly bulletin)
    sitemap_page          one sitemap.xml -> filtered guid_page tasks
    guid_page             one agency document page -> row + mirrors
    guid_file_dl          one artifact download -> documents entry
    index_page            agency index -> child listing tasks (NWS)
    pdf_listing           server-rendered listing -> direct PDF downloads
    nist_latest           GitHub API: newest NIST Tech Pubs release tag
    nist_release_dl       one release snapshot: download + archive + rows

Params (key=value)::

    agency=irs|ofac|occ|bis|nws|epa|nist   required; which agency module
    window=FROM:TO        irs: issue numbers like 2026-30:2026-35
    year=YYYY             irs: only that year's issues; occ: filter URLs
    series=NNN            nws: one directive series
    release=Tag           nist: pin one release (default: latest)
    max_pages=N           sitemap chain depth guard (test guardrail)
    max_docs=N            cap spawned detail tasks (test guardrail)
"""

from __future__ import annotations

from typing import Any

from adapters.base import SourceDefinition, TaskSeed
from adapters.usa.schema import DOMAIN_KEYS, DOMAIN_SCHEMA, DOMAIN_TABLES

__all__ = ["build_source"]

_KNOWN_AGENCIES = ("irs", "ofac", "occ", "bis", "nws", "epa", "nist")


def _fail(message: str) -> SystemExit:
    return SystemExit(
        f"error: {message}\n"
        "usage examples:\n"
        "  python cli.py collect --country usa --source guidance agency=irs year=2026\n"
        "  python cli.py collect --country usa --source guidance agency=ofac max_docs=20\n"
        "  python cli.py collect --country usa --source guidance agency=occ max_docs=20\n"
        "  python cli.py collect --country usa --source guidance agency=bis\n"
        "  python cli.py collect --country usa --source guidance agency=nws series=010\n"
        "  python cli.py collect --country usa --source guidance agency=epa max_docs=20"
    )


def start_tasks(params: dict[str, Any]) -> list[TaskSeed]:
    agency = str(params.get("agency", "") or "").strip().lower()
    if agency not in _KNOWN_AGENCIES:
        raise _fail(f"agency must be one of {_KNOWN_AGENCIES} (got {agency!r})")

    optional: dict[str, Any] = {}
    if params.get("window"):
        optional["window"] = str(params["window"])
    if params.get("year"):
        optional["year"] = str(params["year"])
    if params.get("max_docs"):
        optional["quota_left"] = int(params["max_docs"])

    if agency == "irs":
        # the IRB index lists recent issues; window/year filter them down
        irs_params = dict(optional)
        if params.get("max_docs"):
            irs_params["max_docs"] = int(params["max_docs"])
        return [TaskSeed(type="gz_index", params={"agency": "irs", **irs_params})]

    if agency == "bis":
        from adapters.usa.sources.guidance.commerce.bis import BIS_LISTING_PAGES

        return [
            TaskSeed(type="pdf_listing", params={"agency": "bis", "url": url, **optional})
            for url in BIS_LISTING_PAGES
        ]

    if agency == "nws":
        from adapters.usa.sources.guidance.commerce.nws import NWS_INDEX_URL

        if params.get("series"):
            return [
                TaskSeed(
                    type="pdf_listing",
                    params={
                        "agency": "nws",
                        "url": f"https://www.weather.gov/directives/{params['series']}",
                        **optional,
                    },
                )
            ]
        return [TaskSeed(type="index_page", params={"agency": "nws", "url": NWS_INDEX_URL, **optional})]

    if agency == "nist":
        if params.get("release"):  # pin one release tag; default = discover latest
            return [
                TaskSeed(
                    type="nist_release_dl",
                    params={"agency": "nist", "tag": str(params["release"])},
                )
            ]
        return [TaskSeed(type="nist_latest", params={"agency": "nist"})]

    # sitemap agencies: seed the root sitemap, cap detail spawns via quota
    from adapters.usa.sources.guidance.epa.portal import EPA_SITEMAP
    from adapters.usa.sources.guidance.treasury.occ import OCC_SITEMAP
    from adapters.usa.sources.guidance.treasury.ofac_faq import OFAC_SITEMAP

    seed_url = {"ofac": OFAC_SITEMAP, "occ": OCC_SITEMAP, "epa": EPA_SITEMAP}[agency]
    seed_params: dict[str, Any] = {"agency": agency, "url": seed_url, "page": 1}
    if params.get("max_pages"):
        seed_params["max_pages"] = int(params["max_pages"])
    if params.get("year"):  # year filter applied at parse time per URL
        seed_params["year"] = str(params["year"])
    if optional.get("quota_left"):
        seed_params["quota_left"] = optional["quota_left"]
    return [TaskSeed(type="sitemap_page", params=seed_params)]


def build_source() -> SourceDefinition:
    import adapters.usa.sources.guidance.commerce.bis
    import adapters.usa.sources.guidance.commerce.nist
    import adapters.usa.sources.guidance.commerce.nws

    # importing the agency modules registers their profiles
    import adapters.usa.sources.guidance.treasury.occ
    import adapters.usa.sources.guidance.treasury.ofac_faq  # noqa: F401 (registers ofac)
    from adapters.usa.sources.guidance.commerce.nist import (
        NistLatestHandler,
        NistReleaseDownloadHandler,
    )
    from adapters.usa.sources.guidance.common import (
        GuidFileDownloadHandler,
        GuidPageHandler,
        IndexPageHandler,
        PdfListingHandler,
        SitemapPageHandler,
    )
    from adapters.usa.sources.guidance.treasury.irs_irb import (
        IrbIndexHandler,
        IrbIssueHandler,
    )

    return SourceDefinition(
        name="guidance",
        start_tasks=start_tasks,
        task_types={
            "gz_index": IrbIndexHandler(),
            "gz_issue": IrbIssueHandler(),
            "sitemap_page": SitemapPageHandler(),
            "guid_page": GuidPageHandler(),
            "guid_file_dl": GuidFileDownloadHandler(),
            "index_page": IndexPageHandler(),
            "pdf_listing": PdfListingHandler(),
            "nist_latest": NistLatestHandler(),
            "nist_release_dl": NistReleaseDownloadHandler(),
        },
        domain_schema=DOMAIN_SCHEMA,
        domain_tables=DOMAIN_TABLES,
        domain_keys=DOMAIN_KEYS,
    )
