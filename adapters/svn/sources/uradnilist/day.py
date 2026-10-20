"""Task type ``ul_date``: one issue date's listing — the enumeration heart.

GET ``/api/uradni-list/izdaje-seznam?datumObjave={date}``: a JSON two-level
tree, top level = issuer group (``drzavniOrgani`` state organs,
``lokalneSkupnosti`` municipalities, ``nosilciJavnihPooblastil`` holders of
public powers), second level = issuer name, leaves = published acts. Every
act leaf carries ``key`` (the UL slug, e.g. ``2026-01-2272``, the same
namespace the archival uradni-list.si site and the pre-existing AI4GP
scrape use), ``valueString`` (title), ``valueIdVira`` (the PISRS act id,
e.g. ``ZAKO9575`` — municipal ids carry an ``MP_`` prefix),
``valueUlPdf`` (the as-published PDF file name) and ``valueStevilkaIzdaje``
(the UL issue number, e.g. ``1612/26``). Probed 2026-10-12 across
1991-2026 eras, samples in the task folder; see
docs/countries/svn/uradnilist-zh.md.

One task produces the whole day: one documents row per act (the listing
row is the authority — no per-act page needs fetching to register
bibliographic data) plus carrier seeds, branched on the ZOUL boundary:

- **pre-ZOUL** (before 2026-03-01): one ``ul_html`` seed per act — the
  archival uradni-list.si page becomes the act's primary file (doc_id
  carried there), so the PDF name only needs recording in
  ``meta.ul_pdf_path``; one ``ul_pdf`` seed per distinct issue PDF stores
  the verbatim original once as the secondary carrier (whole-issue files
  shared by N acts).
- **post-ZOUL** (the electronic-only era): no archival HTML exists — one
  ``ul_pdf`` seed per act PDF carries the doc_id and the PDF is the
  primary file.

A date the calendar asserts must answer a real listing tree: ``data: null``
here means calendar and listing disagree — loud shape failure, not an
empty day (the calendar-based enumeration never requests no-issue days).
Rows without ``valueUlPdf`` would produce a document with no as-published
file — not a shape seen anywhere in probing, so loud.
"""

from __future__ import annotations

import re

from adapters.base import (
    RequestSpec,
    Response,
    TaskResult,
    TaskSeed,
    TaskView,
)
from adapters.svn.sources.uradnilist import (
    API_BASE,
    CURSOR_KEY,
    ZOUL_ELECTRONIC_ONLY,
    map_doc_type,
    pdf_rel_path,
    source_url_for,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["UlDateHandler"]

#: Top-level issuer groups. scope=state keeps only drzavniOrgani; a group
#: key outside this table is a taxonomy change and fails loudly under
#: scope=state (silently dropping a future state-level group would punch a
#: hole in the mandated time series). nosilciJavnihPooblastil (holders of
#: public powers — professional chambers and similar bodies; first seen on
#: 2026-09-29, where the loud guard caught it live in the small run) is
#: neither a state organ nor a municipality: known but excluded from
#: scope=state, included under scope=all.
_STATE_GROUP = "drzavniOrgani"
_KNOWN_GROUPS = (_STATE_GROUP, "lokalneSkupnosti", "nosilciJavnihPooblastil")

_ID_PREFIX_RE = re.compile(r"^(?:MP_)?([A-Z]+)")


def _id_prefix(pisrs_id: str) -> str:
    match = _ID_PREFIX_RE.match(pisrs_id)
    return match.group(1) if match else ""


class UlDateHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{API_BASE}/uradni-list/izdaje-seznam",
            params={"datumObjave": str(task.params["date"])},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day = str(task.params["date"])
        scope = str(task.params.get("scope", "state"))
        store_pdf = str(task.params.get("pdf", "on")) != "off"
        html_era = day < ZOUL_ELECTRONIC_ONLY
        payload = response.json()
        data = payload.get("data")
        if payload.get("error") is not None or not isinstance(data, dict):
            raise ValueError(
                f"ul_date {day}: calendar asserts an issue here but the listing "
                f"answered error={payload.get('error')!r} data-null — the issue "
                "listing endpoint may have moved"
            )
        if scope == "all":
            groups = list(data.items())
        else:
            unknown = [key for key in data if key not in _KNOWN_GROUPS]
            if unknown:
                raise ValueError(
                    f"ul_date {day}: unknown issuer group key(s) {unknown!r} — "
                    "group taxonomy may have changed; widen deliberately "
                    "(scope=all) or update the pack"
                )
            state_group = data.get(_STATE_GROUP)
            groups = [(_STATE_GROUP, state_group)] if isinstance(state_group, dict) else []

        documents: list[DocumentRecord] = []
        html_seeds: list[TaskSeed] = []
        per_pdf: dict[str, list[str]] = {}
        for group_key, group in groups:
            if not isinstance(group, dict):
                continue
            for issuer in group.get("children", []):
                issuer_name = str(issuer.get("key", "")).strip()
                for row in issuer.get("children", []):
                    slug = str(row.get("key", "")).strip()
                    title = str(row.get("valueString", "")).strip()
                    pisrs_id = str(row.get("valueIdVira", "")).strip()
                    pdf_name = str(row.get("valueUlPdf", "")).strip()
                    if not (slug and title and pisrs_id and pdf_name):
                        raise ValueError(
                            f"ul_date {day}: act row missing required field(s) "
                            f"(slug={slug!r}, title={bool(title)}, "
                            f"pisrs_id={pisrs_id!r}, pdf={pdf_name!r}) — listing "
                            "row shape may have changed"
                        )
                    meta: dict[str, str] = {
                        "pisrs_id": pisrs_id,
                        "id_prefix": _id_prefix(pisrs_id),
                        "ul_slug": slug,
                        "ul_pdf": pdf_name,
                        "ul_pdf_url": f"{API_BASE}/uradni-list/objava/{pdf_name}",
                        "ul_issue": str(row.get("valueStevilkaIzdaje", "")).strip(),
                        "issuer_group": group_key,
                        "scope_slice": scope,
                    }
                    if html_era and store_pdf:
                        # The archival HTML page is the primary file; the
                        # verbatim PDF stays reachable through its recorded
                        # storage path (multi-file convention, FRA
                        # precedent: sibling paths count as ledgered).
                        meta["ul_pdf_path"] = pdf_rel_path(day, pdf_name)
                    source_url = source_url_for(pisrs_id)
                    doc_id = compute_doc_id("SVN", source_url, day)
                    documents.append(
                        DocumentRecord(
                            title=title,
                            source_url=source_url,
                            publication_date=day,
                            issuing_authority=issuer_name or None,
                            doc_type=map_doc_type(pisrs_id),
                            language="slv",
                            raw_metadata=meta,
                        )
                    )
                    per_pdf.setdefault(pdf_name, []).append(doc_id)
                    if html_era:
                        html_seeds.append(
                            TaskSeed(
                                type="ul_html",
                                params={
                                    "slug": slug,
                                    "title": title,
                                    "date": day,
                                    "doc_id": doc_id,
                                },
                            )
                        )

        if not documents:
            return TaskResult(
                expected_empty=(
                    f"{day}: listing holds only acts outside scope={scope}"
                ),
                cursor_updates={CURSOR_KEY: day},
            )
        if html_era:
            seeds = [
                *html_seeds,
                # the verbatim issue PDFs, stored once each as the
                # secondary carrier (no doc_ids — the HTML page carries
                # the ledger attachment); pdf=off skips this leg entirely
                # (the canonical URL stays in meta.ul_pdf_url)
                *(
                    TaskSeed(type="ul_pdf", params={"pdf": pdf_name, "date": day})
                    for pdf_name in per_pdf
                    if store_pdf
                ),
            ]
        else:
            seeds = [
                TaskSeed(
                    type="ul_pdf",
                    params={"pdf": pdf_name, "date": day, "doc_ids": doc_ids},
                )
                for pdf_name, doc_ids in per_pdf.items()
            ]
        return TaskResult(documents=documents, next_tasks=seeds, cursor_updates={CURSOR_KEY: day})
