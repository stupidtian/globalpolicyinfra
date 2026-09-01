"""Task type ``boe_sumario``: one calendar day of the gazette.

GET the date-addressed daily-summary XML on BOE's open-data API and turn
every kept-section item into a ``boe_item`` seed. Two probed behaviours
shape this handler (2026-09-01, samples in the task folder):

- The request declares ``accept_not_found``: a no-edition day (Sundays,
  holidays) answers HTTP 404 with a fixed envelope —
  ``<response><status><code>404</code>…</status><data/></response>``. The
  body is verified against that shape before the day is recorded as an
  explained empty; anything else under a 404 is an unexplained shape and
  dies loudly. An empty day is still a *fully consumed* day: the watermark
  advances.
- Items sit either directly under ``departamento`` or one ``epigrafe``
  level deeper (both shapes occur across probed days), and ``seccion``
  elements may repeat across multiple ``diario`` blocks (same-day
  extraordinary editions) — the walk covers all of them.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.esp.sources.boe import ACCEPT_XML, API_BASE, CURSOR_KEY

__all__ = ["BoeSumarioHandler"]

_SUMARIO_URL = f"{API_BASE}/datosabiertos/api/boe/sumario/"


def _is_not_found_envelope(root: ET.Element, status_code: int) -> bool:
    """True when the body is the API's own "does not exist" answer."""
    return (
        root.tag == "response"
        and (root.findtext("status/code") or "").strip() == str(status_code)
    )


class BoeSumarioHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        ymd = str(task.params["date"]).replace("-", "")
        return RequestSpec(
            url=f"{_SUMARIO_URL}{ymd}",
            headers=dict(ACCEPT_XML),
            accept_not_found=True,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        date = str(task.params["date"])
        secciones = {s.strip() for s in str(task.params.get("secciones", "1")).split(",")}

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ValueError(f"sumario {date}: body is not XML: {exc}") from exc

        if response.status_code in (404, 410):
            if not _is_not_found_envelope(root, response.status_code):
                raise ValueError(
                    f"sumario {date}: HTTP {response.status_code} with an unexpected "
                    f"body (root={root.tag!r}) — not the known no-edition envelope"
                )
            return TaskResult(
                expected_empty=f"BOE has no edition on {date} (source answers "
                f"{response.status_code}: la información solicitada no existe)",
                cursor_updates={CURSOR_KEY: date},
            )

        if root.tag != "response" or (root.findtext("status/code") or "").strip() != "200":
            code = (root.findtext("status/code") or "").strip() if root.tag == "response" else ""
            raise ValueError(
                f"sumario {date}: unexpected response shape "
                f"(root={root.tag!r}, status code={code or response.status_code!r})"
            )

        seeds: list[TaskSeed] = []
        issue_numbers: list[str] = []
        for seccion in root.iter("seccion"):
            if (seccion.get("codigo") or "").strip() not in secciones:
                continue
            for item in seccion.iter("item"):
                identificador = (item.findtext("identificador") or "").strip()
                if not identificador:
                    raise ValueError(
                        f"sumario {date}: an item carries no identificador "
                        f"(section {seccion.get('codigo')!r})"
                    )
                params: dict[str, str] = {"id": identificador}
                control = (item.findtext("control") or "").strip()
                if control:
                    params["control"] = control
                origen = str(task.params.get("origen", "estatal"))
                if origen != "estatal":  # scope travels in task identity
                    params["origen"] = origen
                seeds.append(TaskSeed(type="boe_item", params=params))
        for diario in root.iter("diario"):
            numero = (diario.get("numero") or "").strip()
            if numero:
                issue_numbers.append(numero)

        if not seeds:
            return TaskResult(
                expected_empty=(
                    f"BOE issue(s) {','.join(issue_numbers) or '?'} of {date} carry no "
                    f"section {','.join(sorted(secciones))} items"
                ),
                cursor_updates={CURSOR_KEY: date},
            )
        return TaskResult(
            next_tasks=seeds,
            cursor_updates={CURSOR_KEY: date},
        )
