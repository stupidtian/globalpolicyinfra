"""Task type ``sfs_list``: one listing page of one number-year.

Response shape (probed 2026-09-09)::

    <dokumentlista traffar="153" sidor="2" sida="1" …>
      <dokument>
        <dok_id>sfs-2026-1776</dok_id>
        <beteckning>2026:1776</beteckning>
        <nummer>1776</nummer>
        <datum>2026-09-03</datum>
        <organ>Landsbygds- och infrastrukturdepartementet SPN</organ>
        <titel>Förordning (2026:1776) om ärendehanteringssystem …</titel>
        <rm>2026</rm>
        <publicerad>2026-09-09 04:40:42</publicerad>
      </dokument>
      …
    </dokumentlista>

Every row's ``rm`` must equal the requested year — the listing's ``from``
and ``to`` parameters malfunction for sfs (they return window-external
documents, probed 2026-09-09 with three cross-checked windows), so the
``rm`` echo is the partition-bleed alarm. ``dok_id`` must equal
``sfs-{beteckning with ':' → '-'}`` — the invariant the whole addressing
scheme rests on. Notice rows (``N2026:3``) may carry a promulgation date
a year later than their number-year (probed: N2020:13 promulgated
2021-10-22) — the partition follows the number-year, the date travels
verbatim.

Rows carry no amendment status and no effective date: those live in the
document page. ``publicerad`` (platform registration stamp, a daily
04:30–04:40 batch) deliberately never enters task params — it is a live
server echo and would corrode task identity day by day.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.swe.sources.riksdagen import LIST_URL, PAGE_SIZE, dok_id_for

__all__ = ["SfsListHandler"]

_REQUIRED = ("dok_id", "beteckning", "datum", "rm")


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


class SfsListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=LIST_URL,
            params={
                "doktyp": "sfs",
                "rm": str(task.params["ar"]),
                "sz": str(PAGE_SIZE),
                "p": str(task.params["p"]),
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        ar = str(task.params["ar"])
        page = int(task.params["p"])
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ValueError(f"list {ar} p{page}: body is not XML: {exc}") from exc
        if root.tag != "dokumentlista":
            raise ValueError(f"list {ar} p{page}: unexpected root element {root.tag!r}")

        sidor_raw = (root.get("sidor") or "").strip()
        try:
            sidor = int(sidor_raw)
        except ValueError:
            raise ValueError(
                f"list {ar} p{page}: sidor attribute is not an integer ({sidor_raw!r})"
            ) from None

        seeds: list[TaskSeed] = []
        for dokument in root.iter("dokument"):
            row = {field: _text(dokument.find(field)) for field in _REQUIRED}
            for field, value in row.items():
                if not value:
                    raise ValueError(f"list {ar} p{page}: a row misses {field!r}")
            sfs_nr = row["beteckning"]
            if row["rm"] != ar:
                raise ValueError(
                    f"list {ar} p{page}: row {sfs_nr!r} carries rm={row['rm']!r} "
                    "— partition bleed (the rm filter stopped matching the year)"
                )
            if row["dok_id"] != dok_id_for(sfs_nr):
                raise ValueError(
                    f"list {ar} p{page}: row {sfs_nr!r} carries dok_id "
                    f"{row['dok_id']!r} — the id↔number invariant broke"
                )
            datum = row["datum"]
            if len(datum) != 10 or datum[4] != "-" or datum[7] != "-":
                raise ValueError(
                    f"list {ar} p{page}: row {sfs_nr!r} has a non-ISO datum {datum!r}"
                )
            params: dict[str, str] = {
                "dok_id": row["dok_id"],
                "sfs_nr": sfs_nr,
                "ar": ar,
                "datum": datum,
            }
            organ = _text(dokument.find("organ"))
            if organ:
                params["organ"] = organ
            seeds.append(TaskSeed(type="sfs_doc", params=params))

        if not seeds:
            if sidor == 0:
                return TaskResult(
                    expected_empty=(
                        f"SFS register carries no {ar} entries "
                        "(below the 1736 corpus start or an unreached year)"
                    )
                )
            raise ValueError(
                f"list {ar} p{page}: page holds no rows yet claims {sidor} page(s)"
            )

        next_tasks = list(seeds)
        if page < sidor:
            next_tasks.append(
                TaskSeed(type="sfs_list", params={**task.params, "p": page + 1})
            )
        return TaskResult(next_tasks=next_tasks)
