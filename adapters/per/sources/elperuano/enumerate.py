"""Task type ``per_day_list``: one calendar day of the Normas Legales supplement.

POST the legacy portal's Filtro with the day (dd/MM/yyyy) and turn every
article into its carrier's follow-up:

- legacy-era entries (link = whole-edition PDF on epdoc2) are **registered
  immediately** — the listing already carries every research field
  (authority, designation, sumilla, date) — and grouped by edition PDF so
  one ``per_day_edition`` per distinct edition file follows;
- portal-era entries (link = device page, or a single-norm supplement PDF
  for some extraordinary items) spawn one ``per_norm_detail`` each; their
  documents register at fetch time where the page supplies the title
  itself (ESP boe_item shape).

A no-edition day (holiday, supplement skipped) answers HTTP 200 with the
portal's empty template — no ``<article>`` at all, no ``<h5>``; that is a
fully consumed day: ``expected_empty`` plus the watermark.
"""

from __future__ import annotations

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.per.sources.elperuano import (
    CURSOR_KEY,
    FILTER_URL,
    edition_ref_parts,
    era_of,
    map_doc_type,
    old_source_url,
    parse_day_listing,
)
from core.document import DocumentRecord

__all__ = ["PerDayListHandler"]


def _meta_with_annex(meta: dict[str, str], annex_ids: tuple[str, ...]) -> dict[str, str]:
    """Annex part ids ride along losslessly (2026-10-28 shape: the
    "Descargar TUPA" buttons) — sibling PDFs of the same norm."""
    if annex_ids:
        meta["annex_ids"] = ";".join(annex_ids)
    return meta


def _form(date_iso: str) -> dict[str, str]:
    year, month, day = date_iso.split("-")
    return {
        "btnBuscar": "",
        "cddesde": f"{day}/{month}/{year}",
        "cdhasta": f"{day}/{month}/{year}",
    }


class PerDayListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        date_iso = str(task.params["date"])
        return RequestSpec(
            url=FILTER_URL,
            method="POST",
            headers={"X-Requested-With": "XMLHttpRequest"},
            form_body=_form(date_iso),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date_iso = str(task.params["date"])
        if response.status_code != 200:
            raise ValueError(f"daily listing {date_iso} returned HTTP {response.status_code}")

        entries = parse_day_listing(response.content, date_iso)
        if not entries:
            return TaskResult(
                expected_empty=(
                    f"El Peruano has no Normas Legales supplement on {date_iso} "
                    "(holiday or no-norm day: the portal answers its empty template)"
                ),
                cursor_updates={CURSOR_KEY: date_iso},
            )

        documents: list[DocumentRecord] = []
        details: list[TaskSeed] = []
        editions: dict[str, list[str]] = {}
        for entry in entries:
            era = era_of(entry)
            if era == "edition":
                code, ymd = edition_ref_parts(entry.data_url)
                documents.append(
                    DocumentRecord(
                        title=entry.sumilla or entry.designation,
                        source_url=old_source_url(code, ymd, entry.data_id),
                        publication_date=date_iso,
                        issuing_authority=entry.authority or None,
                        doc_type=map_doc_type(entry.designation),
                        language="spa",
                        raw_metadata=_meta_with_annex(
                            {
                                "era": "edition",
                                "data_id": entry.data_id,
                                "designation": entry.designation,
                                "edicion": code,
                                "edition_code": code,
                                "edition_url": entry.data_url,
                                **({"sumilla": entry.sumilla} if entry.sumilla else {}),
                            },
                            entry.annex_ids,
                        ),
                    )
                )
                editions.setdefault(entry.data_url, []).append(entry.data_id)
            elif era == "device":
                details.append(
                    TaskSeed(
                        type="per_norm_detail",
                        params={
                            "url": entry.link,
                            "date": date_iso,
                            "authority": entry.authority,
                            "edicion": "EX" if entry.extraordinary else "NL",
                            # title words travel for diagnosability: a
                            # permanently failed fetch names the norm in
                            # the ledger; the page stays the title authority
                            "designation": entry.designation,
                            **({"sumilla": entry.sumilla} if entry.sumilla else {}),
                            **(
                                {"annex_ids": ";".join(entry.annex_ids)}
                                if entry.annex_ids
                                else {}
                            ),
                        },
                    )
                )
            else:  # separata — the link IS the one-norm PDF; the listing is
                # the only place its title words exist, so they ride in params
                details.append(
                    TaskSeed(
                        type="per_norm_detail",
                        params={
                            "url": entry.link,
                            "date": date_iso,
                            "authority": entry.authority,
                            "edicion": "EX" if entry.extraordinary else "NL",
                            "designation": entry.designation,
                            **({"sumilla": entry.sumilla} if entry.sumilla else {}),
                            **(
                                {"annex_ids": ";".join(entry.annex_ids)}
                                if entry.annex_ids
                                else {}
                            ),
                        },
                    )
                )

        next_tasks: list[TaskSeed] = list(details)
        for url, data_ids in editions.items():
            code, ymd = edition_ref_parts(url)
            next_tasks.append(
                TaskSeed(
                    type="per_day_edition",
                    params={"date": date_iso, "url": url, "code": code, "ymd": ymd, "data_ids": data_ids},
                )
            )
        return TaskResult(
            documents=documents,
            next_tasks=next_tasks,
            cursor_updates={CURSOR_KEY: date_iso},
        )
