"""Task type ``che_as_day``: one AS publication date, whole.

One SPARQL request returns every work published that date with all its
language expressions and their file URLs (the production query shape,
probed 2026-09-12 — 2 works × 3 languages = 24 rows / 37KB for
2026-09-04). Rows repeat work-level fields per (expression × URL); the
parser groups them back into works. A same-URL row can appear twice when
a manifestation carries two userFormat notations — grouping by URL set
absorbs that (probed 2026-09-09).

Outputs:

- ``as_works`` upsert — one row per work: the shared event metadata
  (sequence, SR classification, memorial issue, the four native dates,
  type and institution labels, the de/fr/it titles). Also the only record
  for pre-1998-09-01 works, which have no files anywhere in the source.
- one ``che_file`` spawn per (work, language, format) with format ∈ the
  sweep's ``fmts`` and language ∈ ``langs`` (empty = every language the
  graph offers). The spawn carries everything the document row needs:
  per-language title/identifier, dates, mapped doc_type + native word.
  ``max_works`` caps spawns per day, never enumeration — the event rows
  still land, so the timeline stays complete under a test guard.
- the date cursor advances unconditionally on completion: the day was
  fully consumed by this one request, empty weekend days included
  (expected_empty explains the zero).
"""

from __future__ import annotations

from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.che.sources.fedlex import (
    ACCEPT_SPARQL_JSON,
    AS_CURSOR_KEY,
    LANG_ALIASES,
    SPARQL_ENDPOINT,
    doc_type_for,
    file_fmt_from_url,
    normalize_www_url,
    raw_file_path,
)

__all__ = ["CheAsDayHandler", "day_query"]

_XSD_DATE = "^^<http://www.w3.org/2001/XMLSchema#date>"


def day_query(day: str) -> str:
    return f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?work ?seq ?docDate ?inForce ?tax ?typeDe ?instDe ?instFr ?expr ?lang ?identifier ?memorialName ?title ?short ?issue ?url ?pages
WHERE {{
  ?work a jolux:Act ;
        jolux:legalResourceFamilyType <https://fedlex.data.admin.ch/vocabulary/resource-family/oc> ;
        jolux:publicationDate ?pubDate ;
        jolux:sequenceInTheYearOfPublication ?seq ;
        jolux:isPartOf ?issueRes ;
        jolux:isRealizedBy ?expr .
  ?issueRes jolux:memorialNumber ?issue .
  OPTIONAL {{ ?work jolux:dateDocument ?docDate }}
  OPTIONAL {{ ?work jolux:dateEntryInForce ?inForce }}
  OPTIONAL {{ ?work jolux:classifiedByTaxonomyEntry ?taxRes . ?taxRes skos:notation ?tax }}
  OPTIONAL {{ ?work jolux:typeDocument ?typeRes . ?typeRes skos:prefLabel ?typeDe . FILTER(LANGMATCHES(LANG(?typeDe), "de")) }}
  OPTIONAL {{ ?work jolux:responsibilityOf ?instRes . ?instRes skos:prefLabel ?instDe . FILTER(LANGMATCHES(LANG(?instDe), "de")) }}
  OPTIONAL {{ ?work jolux:responsibilityOf ?instRes2 . ?instRes2 skos:prefLabel ?instFr . FILTER(LANGMATCHES(LANG(?instFr), "fr")) }}
  ?expr jolux:language ?langURI ; dct:identifier ?identifier ; jolux:memorialName ?memorialName ; jolux:title ?title .
  OPTIONAL {{ ?expr jolux:titleShort ?short }}
  OPTIONAL {{ ?m jolux:isExemplifiedBy ?url ; ^jolux:isEmbodiedBy ?expr . OPTIONAL {{ ?m jolux:numberOfPages ?pages }} }}
  BIND (STRAFTER(STR(?langURI), "language/") AS ?lang)
  FILTER (?pubDate = "{day}"{_XSD_DATE})
}} ORDER BY ?seq ?lang ?url"""


def _cell(binding: dict[str, Any], name: str) -> str:
    cell = binding.get(name)
    return cell.get("value", "") if cell else ""


class CheAsDayHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        day = str(task.params["date"])
        return RequestSpec(
            url=SPARQL_ENDPOINT,
            params={"query": day_query(day)},
            headers=dict(ACCEPT_SPARQL_JSON),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"AS day query returned HTTP {response.status_code}")
        payload = response.json()
        bindings = payload.get("results", {}).get("bindings")
        if not isinstance(bindings, list):
            raise TypeError("AS day response has no results.bindings array")

        day = str(task.params["date"])
        fmts = {x.strip() for x in str(task.params.get("fmts", "html")).split(",") if x.strip()}
        langs_filter = {
            LANG_ALIASES[x.strip()]
            for x in str(task.params.get("langs", "")).split(",")
            if x.strip()
        }

        works: dict[str, dict[str, Any]] = {}
        for binding in bindings:
            work_uri = _cell(binding, "work")
            if not work_uri or "/eli/oc/" not in work_uri:
                raise ValueError(f"unexpected work URI {work_uri!r} on {day}")
            work = works.setdefault(
                work_uri,
                {
                    "seq": None, "docDate": "", "inForce": "", "tax": "",
                    "typeDe": "", "instDe": "", "instFr": "", "issue": "",
                    "expressions": {},
                },
            )
            for target, source in (
                ("seq", "seq"), ("docDate", "docDate"), ("inForce", "inForce"),
                ("tax", "tax"), ("typeDe", "typeDe"), ("instDe", "instDe"),
                ("instFr", "instFr"), ("issue", "issue"),
            ):
                value = _cell(binding, source)
                if value and not work[target]:
                    work[target] = value

            expr_uri = _cell(binding, "expr")
            expr = work["expressions"].setdefault(
                expr_uri,
                {
                    "lang": _cell(binding, "lang"),
                    "identifier": _cell(binding, "identifier"),
                    "memorialName": _cell(binding, "memorialName"),
                    "title": _cell(binding, "title"),
                    "short": _cell(binding, "short"),
                    "urls": {},
                },
            )
            url = _cell(binding, "url")
            if url:
                pages = _cell(binding, "pages")
                expr["urls"][url] = pages

        if not works:
            return TaskResult(
                expected_empty=f"no AS publications on {day}",
                cursor_updates={AS_CURSOR_KEY: day},
            )

        rows: list[dict[str, Any]] = []
        for work_uri, work in sorted(works.items()):
            titles = {"DEU": "", "FRA": "", "ITA": ""}
            for expr in work["expressions"].values():
                if expr["lang"] in titles:
                    titles[expr["lang"]] = expr["title"]
            rows.append(
                {
                    "work_uri": work_uri,
                    "seq": int(work["seq"]) if str(work["seq"]).isdigit() else None,
                    "publication_date": day,
                    "date_document": work["docDate"] or None,
                    "date_entry_in_force": work["inForce"] or None,
                    "date_no_longer_in_force": None,
                    "sr_class": work["tax"] or None,
                    "issue": int(work["issue"]) if str(work["issue"]).isdigit() else None,
                    "type_de": work["typeDe"] or None,
                    "institution_de": work["instDe"] or None,
                    "institution_fr": work["instFr"] or None,
                    "title_de": titles["DEU"] or None,
                    "title_fr": titles["FRA"] or None,
                    "title_it": titles["ITA"] or None,
                }
            )

        # Deep-fetch selection: whole works (all their language files) up to
        # the cap — never a half-fetched work. Enumeration above is always
        # complete, so the event timeline survives a test guard.
        selected = sorted(works.items())
        max_works = task.params.get("max_works")
        if max_works:
            selected = selected[: int(max_works)]
        spawns: list[TaskSeed] = []
        for work_uri, work in selected:
            for expr_uri, expr in sorted(work["expressions"].items()):
                lang = expr["lang"]
                if langs_filter and lang not in langs_filter:
                    continue
                for url, pages in sorted(expr["urls"].items()):
                    if file_fmt_from_url(url) not in fmts:
                        continue
                    meta: dict[str, str] = {
                        "work_uri": work_uri,
                        "identifier": expr["identifier"],
                        "memorial_name": expr["memorialName"],
                        "sr_class": work["tax"],
                        "seq": work["seq"],
                        "issue": work["issue"],
                        "date_document": work["docDate"],
                        "date_entry_in_force": work["inForce"],
                        "graph_url": url,
                    }
                    if expr["short"]:
                        meta["title_short"] = expr["short"]
                    if work["typeDe"]:
                        meta["native_type"] = work["typeDe"]
                    if pages:
                        meta["pages"] = pages
                    www_url = normalize_www_url(url)
                    spawns.append(
                        TaskSeed(
                            type="che_file",
                            params={
                                "kind": "as",
                                "url": www_url,
                                "path": raw_file_path("as", www_url),
                                "title": expr["title"],
                                "publication_date": day,
                                "language": expr["lang"].lower(),
                                "doc_type": doc_type_for(work["typeDe"]),
                                "entity_ref": f"as_works:{work_uri}",
                                "meta": meta,
                            },
                        )
                    )

        return TaskResult(
            upsert_rows={"as_works": rows},
            next_tasks=spawns,
            cursor_updates={AS_CURSOR_KEY: day},
        )
