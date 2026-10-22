"""Task type ``mev_list``: one page of one type's catalogue.

POST the DataTables envelope to ``/anasayfa/MevzuatDatatable`` (probed
2026-09-27; PascalCase ``parameters``, records ordered by number
descending, ``length`` capped at 100 server-side). Every record carries
the full entity identity plus dates, so one response both upserts entity
rows and seeds the text fetch. A full page chains the next page unless
the ``pages`` cap (trial runs) is reached; ``recordsTotal`` is cross-
checked against the accumulated count when the walk ends.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.tur.sources.mevzuat import API_BASE, PAGE_SIZE, to_iso_date

__all__ = ["MevListHandler", "datatable_envelope"]

_DATATABLE_URL = f"{API_BASE}/anasayfa/MevzuatDatatable"


def datatable_envelope(tur: int, start: int, length: int = PAGE_SIZE) -> dict[str, Any]:
    """The exact envelope the site's own JS posts (columns trimmed to the
    one the UI renders; the server binds ``parameters`` only)."""
    return {
        "draw": 1,
        "columns": [
            {
                "data": None,
                "name": "",
                "searchable": True,
                "orderable": False,
                "search": {"value": "", "regex": False},
            }
        ],
        "order": [],
        "start": start,
        "length": length,
        "search": {"value": "", "regex": False},
        "parameters": {
            "AranacakIfade": "",
            "AranacakYer": 1,
            "TamCumle": False,
            "MevzuatTur": tur,
            "GenelArama": False,
        },
    }


class MevListHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=_DATATABLE_URL,
            method="POST",
            json_body=datatable_envelope(
                int(task.params["tur"]), int(task.params.get("start", 0))
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        tur = int(params["tur"])
        start = int(params.get("start", 0))
        payload = response.json()

        total = payload.get("recordsTotal")
        rows = payload.get("data")
        if not isinstance(total, int) or not isinstance(rows, list):
            raise TypeError(
                f"mev_list tur={tur} start={start}: unexpected envelope "
                f"(recordsTotal={total!r}, data={type(rows).__name__})"
            )
        if total == 0:
            raise ValueError(
                f"mev_list tur={tur}: server reports an empty catalogue — "
                "unknown type codes fall back to the whole registry, this "
                "shape was never probed"
            )

        entity_rows: list[dict[str, Any]] = []
        seeds: list[TaskSeed] = []
        strays = 0
        for row in rows:
            record = self._record(tur, row)
            if record is None:
                strays += 1
                continue
            entity_rows.append(
                {
                    "mevzuat_tur": record["tur"],
                    "mevzuat_no": record["no"],
                    "mevzuat_tertip": record["tertip"],
                    "mevzuat_adi": record["adi"],
                    "kabul_tarihi": record["kabul"],
                    "rg_tarihi": record["rg"],
                    "rg_sayisi": record["rg_sayisi"],
                    "mukerrer": record["mukerrer"],
                }
            )
            # fileType 2 = file-only text (no iframe body; the whole CB
            # Kararı corpus, probed 2026-09-28) → the PDF is the text.
            text_type = "mev_pdf" if row.get("fileType") == 2 else "mev_metin"
            metin_params: dict[str, Any] = {
                "tur": record["tur"],
                "no": record["no"],
                "tertip": record["tertip"],
                "adi": record["adi"],
            }
            if record["rg"]:
                metin_params["rg_tarihi"] = record["rg"]
            seeds.append(TaskSeed(type=text_type, params=metin_params))

        if strays > len(rows) // 2:
            raise ValueError(
                f"mev_list tur={tur} start={start}: majority of the page "
                "answers another type — server-side fallback shape"
            )

        next_tasks: list[TaskSeed] = []
        fetched_to = start + len(rows)
        capped = int(params.get("pages", 0)) and (start // PAGE_SIZE) + 1 >= int(
            params["pages"]
        )
        if rows and fetched_to < total and not capped:
            # chain on ANY non-empty page: the server legitimately shorts
            # pages sometimes (probed tur=5 delivering 87 of 100)
            nxt: dict[str, Any] = {"tur": tur, "start": fetched_to}
            if params.get("pages"):
                nxt["pages"] = params["pages"]
            if params.get("refresh"):
                nxt["refresh"] = params["refresh"]
            next_tasks.append(TaskSeed(type="mev_list", params=nxt))
        if not rows and fetched_to < total and not capped:
            result = TaskResult(upsert_rows={"mevzuat": entity_rows})
            result.expected_empty = (
                f"mev_list tur={tur}: server exhausted the catalogue at "
                f"{fetched_to} of {total} reported records"
            )
            return result

        return TaskResult(upsert_rows={"mevzuat": entity_rows}, next_tasks=seeds + next_tasks)

    def _record(self, tur: int, row: dict[str, Any]) -> dict[str, Any] | None:
        """One catalogue record → entity fields. A record answering another
        type is a server stray (probed tur=2 page carrying one tur=17 row):
        minority strays are skipped by the caller; None marks them."""
        no = str(row.get("mevzuatNo") or "").strip()
        adi = " ".join(str(row.get("mevAdi") or "").split())
        tertip_raw = row.get("mevzuatTertip")
        if not no or not adi or tertip_raw in (None, ""):
            raise ValueError(
                f"mev_list tur={tur}: record missing identity fields "
                f"(no={no!r}, adi={adi!r}, tertip={tertip_raw!r})"
            )
        row_tur = row.get("mevzuatTur")
        if isinstance(row_tur, int) and row_tur != tur:
            # the Kanun catalogue legitimately carries its type-0 tail
            # (Osmanlı-era statutes; probed: 916 total = 907 + 9 type-0) —
            # upsert under the row's own type; other mixtures are strays
            if not (tur in (0, 1) and row_tur in (0, 1)):
                return None
            tur = row_tur
        if str(row.get("mevzuatTurEnumString") or "") and isinstance(row_tur, int):
            pass  # identity carried by the numeric tur above
        mukerrer = row.get("mukerrer")
        return {
            "tur": tur,
            "no": no,
            "tertip": int(tertip_raw),
            "adi": adi,
            "kabul": to_iso_date(row.get("kabulTarih")),
            "rg": to_iso_date(row.get("resmiGazeteTarihi")),
            "rg_sayisi": str(row.get("resmiGazeteSayisi") or "") or None,
            "mukerrer": str(mukerrer) if mukerrer else None,
        }
