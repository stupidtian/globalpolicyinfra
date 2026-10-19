"""Task type ``dou_leitura``: one (calendar day, seção) pair of the gazette.

GET the date-and-section-addressed reading page
(``leiturajornal?secao=…&data=DD-MM-YYYY``) and turn every kept item into
a ``dou_artigo`` seed. Probed behaviours that shape this handler
(2026-10-02, samples in the task folder):

- The page's ``#params`` element carries a JSON payload (up to ~430 KB of
  it on a busy day) with ``jsonArray`` — one row per published item —
  plus ``typeNormDay``, the per-edition presence flags. The payload is
  extracted positionally (everything after the marker's ``>``, first JSON
  value) rather than by trusting a closing-tag guess; a missing marker or
  unparsable JSON dies loudly.
- A no-edition day (Sundays, holidays — and *every* date before the
  interface's 2013-01-02 coverage start) answers HTTP 200 with an empty
  ``jsonArray`` and all-false ``typeNormDay``. That is a *fully consumed*
  day: explained empty, watermark advances. There is no 404 semantics to
  declare.
- Whole editions may travel as extras: on 2021-04-01 the regular DO1
  answered zero rows while DO1_EXTRA_F carried the day's entire section
  (Lei 14.133/2021 included). The default sweep pairs do1 with do1e;
  each seção keeps its own watermark.
- ``tipos`` filtering runs here, on the row's native ``artType`` word
  (accent-stripped prefix match — ``Lei`` keeps ``Lei Complementar``).
  A day whose rows are all filtered out is an explained empty too, and
  the watermark still advances: the day *was* fully consumed.
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.bra.sources.dou import BASE_URL, cursor_key

__all__ = ["DouLeituraHandler", "norm_art_type"]

_PARAMS_MARK = 'id="params"'
_DATE_URL_FMT = "%d-%m-%Y"


def norm_art_type(art_type: str) -> str:
    """Lowercase, accent-stripped form of a native artType word."""
    decomposed = unicodedata.normalize("NFD", art_type.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _kept_by_tipos(art_type: str, tipos: list[str]) -> bool:
    norm = norm_art_type(art_type)
    return any(norm.startswith(norm_art_type(t)) for t in tipos)


class DouLeituraHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day_iso = str(task.params["date"])
        secao = str(task.params["secao"])
        y, m, d = day_iso.split("-")
        return RequestSpec(
            url=f"{BASE_URL}/leiturajornal",
            params={"secao": secao, "data": f"{d}-{m}-{y}"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        day_iso = str(task.params["date"])
        secao = str(task.params["secao"])
        y, m, d = day_iso.split("-")
        dmy = f"{d}-{m}-{y}"

        html = response.content.decode("utf-8", errors="replace")
        mark = html.find(_PARAMS_MARK)
        if mark < 0:
            raise ValueError(
                f"leitura {secao} {day_iso}: no #params marker in the page "
                f"(HTTP {response.status_code}, {len(response.content)} bytes) — shape changed"
            )
        gt = html.find(">", mark)
        if gt < 0:
            raise ValueError(f"leitura {secao} {day_iso}: #params marker never closes")
        try:
            payload, _ = json.JSONDecoder().raw_decode(html[gt + 1 :].lstrip())
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"leitura {secao} {day_iso}: #params payload is not JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise TypeError(f"leitura {secao} {day_iso}: #params payload is {type(payload).__name__}")


        date_url = str(payload.get("dateUrl", ""))
        if date_url and date_url != dmy:
            raise ValueError(
                f"leitura {secao} {day_iso}: page echoes dateUrl={date_url!r} "
                f"instead of {dmy!r} — stale or redirected edition"
            )

        rows = payload.get("jsonArray")
        if not isinstance(rows, list):
            raise TypeError(f"leitura {secao} {day_iso}: jsonArray is {type(rows).__name__}")

        flags = payload.get("typeNormDay")
        flags_str = json.dumps(flags, ensure_ascii=False, sort_keys=True) if isinstance(flags, dict) else ""

        tipos_csv = str(task.params.get("tipos", ""))
        tipos = [t.strip() for t in tipos_csv.split(",") if t.strip()]

        seeds: list[TaskSeed] = []
        skipped = 0
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError(f"leitura {secao} {day_iso}: jsonArray row is not an object")
            url_title = str(row.get("urlTitle") or "").strip()
            if not url_title:
                raise ValueError(
                    f"leitura {secao} {day_iso}: a row carries no urlTitle "
                    f"(artType={row.get('artType')!r})"
                )
            art_type = str(row.get("artType") or "")
            if tipos and not _kept_by_tipos(art_type, tipos):
                skipped += 1
                continue
            params: dict[str, Any] = {
                "url_title": url_title,
                "pub_name": str(row.get("pubName") or ""),
                "pub_date": str(row.get("pubDate") or ""),
                "title": str(row.get("title") or ""),
                "art_type": art_type,
                "number_page": str(row.get("numberPage") or ""),
                "edition_number": str(row.get("editionNumber") or ""),
                "hierarchy_str": str(row.get("hierarchyStr") or ""),
            }
            content = str(row.get("content") or "")
            if content:
                params["content_snippet"] = content[:500]
            hierarchy_size = row.get("hierarchyLevelSize")
            if hierarchy_size not in (None, ""):
                params["hierarchy_level_size"] = str(hierarchy_size)
            pub_order = str(row.get("pubOrder") or "")
            if pub_order:
                params["pub_order"] = pub_order
            sub_titulo = str(row.get("subTitulo") or "")
            if sub_titulo:
                params["sub_titulo"] = sub_titulo
            seeds.append(TaskSeed(type="dou_artigo", params=params))

        if not rows:
            return TaskResult(
                expected_empty=(
                    f"DOU {secao} {day_iso}: no edition (jsonArray empty, "
                    f"typeNormDay {flags_str or '{}'})"
                ),
                cursor_updates={cursor_key(secao): day_iso},
            )
        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"DOU {secao} {day_iso}: all {len(rows)} items filtered out "
                    f"by tipos={tipos_csv}"
                ),
                cursor_updates={cursor_key(secao): day_iso},
            )
        return TaskResult(
            next_tasks=seeds,
            cursor_updates={cursor_key(secao): day_iso},
        )
