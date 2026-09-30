"""Task type ``chl_versions``: one norma's version timeline (the lineage).

``get_versiones`` returns every version of one norma — XML-flavored JSON
(probed 2026-09-20; single-version norms collapse to a dict, hence the
list-wrap)::

    {"Versiones": {"@id_norma": 82255, "Version": [
       {"@tipoVersion": "Última Versión", "@vigenteDesde": "1995-03-17",
        "UrlVersion": {"$": "https://www.leychile.cl/N?i=82255&f=1995-03-17"}},
       {"@vigenteHasta": "1995-03-16", "@tipoVersion": "Texto Original",
        "@vigenteDesde": "1990-12-31", "UrlVersion": {...},
        "Modificatorias": {"Modificatoria": {
            "@tipoModificacion": "MODIFICACION", "@tipoNorma": "RES",
            "@idNorma": 33873, "@nroNorma": 234,
            "@fechaPublicacion": "17-MAR-1995", "@inicioVigencia": "1995-03-17",
            "@organismo": "MINISTERIO DE ECONOMÍA…"}}}]}}

Ley 18290 (1984, heavily amended): 37 versions — Texto Original, 35
Intermedios (each the consolidated state after an amendment), Última.
Each version row carries its validity range plus, for the version it
replaced, the amending norms — the native amendment chain, kept as raw
JSON (building the who-amended-whom graph is an analysis-stage design,
collection stores the fields losslessly).

A rewrite task: the timeline is one group per norma — delete the norma's
``norma_versions`` rows, insert the current set. Discovery: every
version except the latest spawns a ``chl_body`` (flagged
``from_versions`` — born inside a timeline, never re-spawns one). The
latest version is skipped: the register row already anchored it, and
identical params would only collide with that done task.
"""

from __future__ import annotations

import json
from typing import Any

from adapters.base import ReplaceRows, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.chl.sources.leychile import API_BASE

__all__ = ["ChlVersionsHandler"]

#: Timeline labels -> numeric tipoVersion codes the body endpoint expects
#: (all four request combinations probed 2026-09-20; Intermedio takes the
#: empty code).
_TYPE_CODES = {
    "Texto Original": "1",
    "Intermedio": "",
    "Última Versión": "2",
    "Única": "3",
}


class ChlVersionsHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{API_BASE}/Consulta/get_versiones",
            params={
                "idNorma": str(task.params["id_norma"]),
                "formato": "json",
                "idParte": "",
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        id_norma = str(task.params["id_norma"])
        if response.status_code != 200:
            raise ValueError(f"version timeline of {id_norma} returned HTTP {response.status_code}")

        data: Any = response.json()
        envelope = data.get("Versiones") if isinstance(data, dict) else None
        versions = envelope.get("Version") if isinstance(envelope, dict) else None
        if versions is None:
            raise ValueError(f"version timeline of {id_norma} carries no Versiones.Version")
        if isinstance(versions, dict):
            versions = [versions]
        if not versions:
            raise ValueError(f"version timeline of {id_norma} is empty")

        rows: list[dict[str, str]] = []
        next_tasks: list[TaskSeed] = []
        for version in versions:
            if not isinstance(version, dict):
                # ValueError (not TypeError) per pack convention: unknown
                # shapes escalate via the engine, they are data findings.
                raise ValueError(  # noqa: TRY004
                    f"version timeline of {id_norma} holds a non-dict entry"
                )
            vigente_desde = str(version.get("@vigenteDesde", "") or "")
            if not vigente_desde:
                raise ValueError(f"a version of norma {id_norma} carries no @vigenteDesde")
            tipo = str(version.get("@tipoVersion", "") or "")
            rows.append(
                {
                    "id_norma": id_norma,
                    "vigente_desde": vigente_desde,
                    "tipo_version": tipo,
                    "vigente_hasta": str(version.get("@vigenteHasta", "") or ""),
                    "modificatorias": json.dumps(
                        version.get("Modificatorias", {}), ensure_ascii=False
                    ),
                }
            )
            # The latest version was already anchored by the register row
            # (row FECHA_VIGENCIA = Última's vigenteDesde, probed); spawn
            # only genuinely historical versions.
            if tipo == "Última Versión":
                continue
            next_tasks.append(
                TaskSeed(
                    type="chl_body",
                    params={
                        "id_norma": id_norma,
                        "id_version": vigente_desde,
                        "tipo_version": _TYPE_CODES.get(tipo, ""),
                        "from_versions": 1,
                    },
                )
            )

        if len(rows) == 1 and not next_tasks:
            # A never-amended norma should never reach this task (the list
            # skips Única anchors) — a single-entry timeline here means the
            # row's TIPOVERSION disagreed with the timeline; still record
            # the row, no historical spawn is legitimately expected.
            return TaskResult(
                replacements=[
                    ReplaceRows(table="norma_versions", match={"id_norma": id_norma}, rows=rows)
                ],
                expected_empty=f"norma {id_norma} timeline holds a single version "
                "(row TIPOVERSION disagreed with Única — no historical versions)",
            )
        return TaskResult(
            replacements=[
                ReplaceRows(table="norma_versions", match={"id_norma": id_norma}, rows=rows)
            ],
            next_tasks=next_tasks,
        )
