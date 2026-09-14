"""Task type ``che_sr_entry``: one SR entry's metadata (part 1 of 2).

The entry fetch is deliberately split from its version lineage
(``che_sr_versions``): the endpoint intermittently degrades queries whose
join size explodes (observed 2026-09-12/13: the combined
metadata×lineage×anchor query answered 929 rows at midnight, then
valid-looking zero rows for hours, while each half alone kept answering —
the join size, not the query text, is what the degraded mode kills).
Each task keeps a query shape that stayed healthy throughout.

This one carries the entry-local facts: SR classification number,
basicAct backlink to the AS promulgation, effectivity window and status
code, historical id, native type label, and one title per language the
entry's current expressions offer (``?clang``/``?ctitle``). It upserts
the ``sr_entries`` row (``latest_version_date`` still NULL — the lineage
task fills it) and spawns ``che_sr_versions`` carrying the titles, which
the file records need and the lineage response does not carry.
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.che.sources.fedlex import ACCEPT_SPARQL_JSON, SPARQL_ENDPOINT

__all__ = ["CheSrEntryHandler", "entry_query"]


def entry_query(entry_uri: str) -> str:
    # Variable-subject skeleton (the day-query family): the endpoint's
    # overnight degraded mode (observed 2026-09-12/13, ~00:00–03:00 CET)
    # inconsistently empties constant-subject lookups while scan-shaped
    # queries keep answering; anchoring via ?entry + FILTER keeps this
    # query in the stable family. Zero rows stays a TransientError.
    return f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?sr ?histId ?dateDoc ?inForce ?noLonger ?status ?basicAct ?etypeDe ?clang ?ctitle
WHERE {{
  ?entry a jolux:ConsolidationAbstract .
  FILTER (STR(?entry) = "{entry_uri}")
  OPTIONAL {{ ?entry jolux:classifiedByTaxonomyEntry ?taxRes . ?taxRes skos:notation ?sr }}
  OPTIONAL {{ ?entry jolux:historicalLegalId ?histId }}
  OPTIONAL {{ ?entry jolux:dateDocument ?dateDoc }}
  OPTIONAL {{ ?entry jolux:dateEntryInForce ?inForce }}
  OPTIONAL {{ ?entry jolux:dateNoLongerInForce ?noLonger }}
  OPTIONAL {{ ?entry jolux:inForceStatus ?status }}
  OPTIONAL {{ ?entry jolux:basicAct ?basicAct }}
  OPTIONAL {{ ?entry jolux:typeDocument ?etypeRes . ?etypeRes skos:prefLabel ?etypeDe .
              FILTER (LANGMATCHES(LANG(?etypeDe), "de")) }}
  OPTIONAL {{ ?entry jolux:isRealizedBy ?ce . ?ce jolux:language ?clangURI ; jolux:title ?ctitle .
              BIND (STRAFTER(STR(?clangURI), "language/") AS ?clang) }}
}}"""


def _cell(binding: dict[str, Any], name: str) -> str:
    cell = binding.get(name)
    return cell.get("value", "") if cell else ""


def _uri_tail(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1]


class CheSrEntryHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=SPARQL_ENDPOINT,
            params={"query": entry_query(str(task.params["entry_uri"]))},
            headers=dict(ACCEPT_SPARQL_JSON),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"SR entry query returned HTTP {response.status_code}")
        payload = response.json()
        bindings = payload.get("results", {}).get("bindings")
        if not isinstance(bindings, list):
            raise TypeError("SR entry response has no results.bindings array")
        if not bindings:
            # The entry exists (walk/feed enumerated it); a zero-row answer
            # is the endpoint's intermittent degraded mode, which serves
            # valid-looking EMPTY results under load (observed 2026-09-12:
            # the same query answered 929 rows, then zero, then 929 rows).
            from runtime.errors import TransientError

            raise TransientError(
                f"SR entry {task.params['entry_uri']} returned zero rows — "
                "endpoint flap (empty-but-valid answers observed under load), "
                "not a missing entry"
            )

        entry_uri = str(task.params["entry_uri"])
        fields: dict[str, str] = {}
        titles: dict[str, str] = {}
        for binding in bindings:
            for name in ("sr", "histId", "dateDoc", "inForce", "noLonger",
                         "status", "basicAct", "etypeDe"):
                value = _cell(binding, name)
                if value and not fields.get(name):
                    fields[name] = value
            clang, ctitle = _cell(binding, "clang"), _cell(binding, "ctitle")
            if clang and ctitle and clang not in titles:
                titles[clang] = ctitle

        entry_row: dict[str, Any] = {
            "entry_uri": entry_uri,
            "sr_number": fields.get("sr") or None,
            "basic_act": fields.get("basicAct") or None,
            "date_document": fields.get("dateDoc") or None,
            "date_entry_in_force": fields.get("inForce") or None,
            "date_no_longer_in_force": fields.get("noLonger") or None,
            "in_force_status": _uri_tail(fields["status"]) if fields.get("status") else None,
            "historical_legal_id": fields.get("histId") or None,
            "title_de": titles.get("DEU"),
            "title_fr": titles.get("FRA"),
            "latest_version_date": None,  # the lineage task fills this in
        }

        mode = {
            "fmts": str(task.params.get("fmts", "html")),
            "langs": str(task.params.get("langs", "")),
            "sr": str(task.params.get("sr", "anchor")),
        }
        entry_facts = {
            "sr_number": fields.get("sr") or "",
            "hist_id": fields.get("histId") or "",
            "in_force_status": _uri_tail(fields["status"]) if fields.get("status") else "",
            "basic_act": fields.get("basicAct") or "",
            "etype_de": fields.get("etypeDe") or "",
            "titles": titles,
        }
        return TaskResult(
            upsert_rows={"sr_entries": [entry_row]},
            next_tasks=[
                TaskSeed(
                    type="che_sr_versions",
                    params={**mode, "entry_uri": entry_uri, "facts": entry_facts},
                    signal=task.signal,
                )
            ],
        )
