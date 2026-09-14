"""Task type ``che_sr_versions``: one SR entry's lineage + anchor files (2 of 2).

The proven-stable query skeleton (the shape that kept answering through
the endpoint's degraded windows of 2026-09-12/13): the entry's type as
the only required pattern, the bare version lineage and the anchor's
expressions as two OPTIONAL blocks. Scope ``sr=anchor`` (default)
collects files for the anchor version only — the max-``dateApplicability``
version, future-dated scheduled consolidations included (their windows
live in the lineage; picking "max ≤ today" would go stale the day a
scheduled version takes effect without any ``modified`` bump to reopen
the entry — pre-published 2027 versions probed 2026-09-09). Scope
``sr=all`` switches to a single nested block so URLs stay attributed to
their version (two separate blocks would cross-multiply lineage × files).

Outputs: the ``sr_versions`` whole-group replacement, a partial
``sr_entries`` upsert filling ``latest_version_date`` (the anchor
pointer), and one ``che_file`` spawn per (language, format) selected by
the sweep — anchored documents date from the version's applicability
start (AUS compilation-date semantics). Titles for the file records ride
in from the entry task via ``facts`` (the lineage response carries none).
"""

from __future__ import annotations

from typing import Any

from adapters.base import (
    ReplaceRows,
    RequestSpec,
    Response,
    TaskResult,
    TaskSeed,
    TaskView,
)
from adapters.che.sources.fedlex import (
    ACCEPT_SPARQL_JSON,
    LANG_ALIASES,
    SPARQL_ENDPOINT,
    doc_type_for,
    file_fmt_from_url,
    normalize_www_url,
    raw_file_path,
)

__all__ = ["CheSrVersionsHandler", "versions_query"]


def versions_query(entry_uri: str, scope_all: bool) -> str:
    # Variable-subject skeleton (?entry + FILTER): same family as the day
    # query, the shape that stayed healthy through the endpoint's
    # overnight degraded windows (2026-09-12/13) — a constant-subject
    # variant of the same query answered 927 rows at 22:00 and zero from
    # midnight on, while this form kept answering.
    block = (
        """  OPTIONAL {
    ?v a jolux:Consolidation ; jolux:isMemberOf ?entry .
    OPTIONAL { ?v jolux:dateApplicability ?dateApp }
    OPTIONAL { ?v jolux:dateEndApplicability ?endApp }
    OPTIONAL { ?v <http://purl.org/dc/terms/modified> ?mod }
    OPTIONAL {
      ?v jolux:isRealizedBy ?lexpr .
      ?lexpr jolux:language ?langURI .
      OPTIONAL { ?lm jolux:isExemplifiedBy ?url ; ^jolux:isEmbodiedBy ?lexpr .
                 OPTIONAL { ?lm jolux:numberOfPages ?pages } }
      BIND (STRAFTER(STR(?langURI), "language/") AS ?lang)
    }
  }"""
        if scope_all
        else """  OPTIONAL {
    ?v a jolux:Consolidation ; jolux:isMemberOf ?entry .
    OPTIONAL { ?v jolux:dateApplicability ?dateApp }
    OPTIONAL { ?v jolux:dateEndApplicability ?endApp }
    OPTIONAL { ?v <http://purl.org/dc/terms/modified> ?mod }
  }
  OPTIONAL {
    ?lv a jolux:Consolidation ; jolux:isMemberOf ?entry ; jolux:dateApplicability ?lvApp .
    FILTER NOT EXISTS {
      ?lv2 a jolux:Consolidation ; jolux:isMemberOf ?entry ; jolux:dateApplicability ?lvApp2 .
      FILTER (?lvApp2 > ?lvApp)
    }
    ?lv jolux:isRealizedBy ?lexpr .
    ?lexpr jolux:language ?langURI .
    OPTIONAL { ?lm jolux:isExemplifiedBy ?url ; ^jolux:isEmbodiedBy ?lexpr .
               OPTIONAL { ?lm jolux:numberOfPages ?pages } }
    BIND (STRAFTER(STR(?langURI), "language/") AS ?lang)
  }"""
    )
    return f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux>
SELECT DISTINCT ?v ?dateApp ?endApp ?mod ?lang ?url ?pages
WHERE {{
  ?entry a jolux:ConsolidationAbstract .
  FILTER (STR(?entry) = "{entry_uri}")
{block}
}}"""


def _cell(binding: dict[str, Any], name: str) -> str:
    cell = binding.get(name)
    return cell.get("value", "") if cell else ""


def _uri_tail(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1]


def _version_date(version_uri: str, date_app: str) -> str:
    """The lineage identity: the URI's tail date (YYYYMMDD → ISO), falling
    back to the applicability date when the tail is not a plain date."""
    tail = _uri_tail(version_uri)
    if len(tail) == 8 and tail.isdigit():
        return f"{tail[:4]}-{tail[4:6]}-{tail[6:]}"
    if date_app:
        return date_app
    raise ValueError(f"version {version_uri} carries no usable date")


class CheSrVersionsHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        scope_all = str(task.params.get("sr", "anchor")) == "all"
        return RequestSpec(
            url=SPARQL_ENDPOINT,
            params={
                "query": versions_query(str(task.params["entry_uri"]), scope_all)
            },
            headers=dict(ACCEPT_SPARQL_JSON),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        if response.status_code != 200:
            raise ValueError(f"SR versions query returned HTTP {response.status_code}")
        payload = response.json()
        bindings = payload.get("results", {}).get("bindings")
        if not isinstance(bindings, list):
            raise TypeError("SR versions response has no results.bindings array")
        if not bindings:
            from runtime.errors import TransientError

            raise TransientError(
                f"SR versions for {task.params['entry_uri']} returned zero rows — "
                "endpoint flap (empty-but-valid answers observed under load)"
            )

        entry_uri = str(task.params["entry_uri"])
        scope_all = str(task.params.get("sr", "anchor")) == "all"
        fmts = {x.strip() for x in str(task.params.get("fmts", "html")).split(",") if x.strip()}
        langs_filter = {
            LANG_ALIASES[x.strip()]
            for x in str(task.params.get("langs", "")).split(",")
            if x.strip()
        }
        facts: dict[str, Any] = dict(task.params.get("facts") or {})
        titles: dict[str, str] = {
            str(k): str(v) for k, v in dict(facts.get("titles") or {}).items()
        }

        versions: dict[str, dict[str, str]] = {}
        anchor_files: dict[tuple[str, str], str] = {}
        version_files: dict[tuple[str, str, str], str] = {}
        for binding in bindings:
            v_uri = _cell(binding, "v")
            if v_uri:
                version = versions.setdefault(v_uri, {})
                for name in ("dateApp", "endApp", "mod"):
                    value = _cell(binding, name)
                    if value and not version.get(name):
                        version[name] = value
            lang, url = _cell(binding, "lang"), _cell(binding, "url")
            if lang and url:
                pages = _cell(binding, "pages")
                if scope_all:
                    if v_uri:
                        version_files[(v_uri, lang, url)] = pages
                else:
                    anchor_files[(lang, url)] = pages

        version_dates = {
            v: _version_date(v, info.get("dateApp", "")) for v, info in versions.items()
        }
        anchor_date = max(version_dates.values()) if version_dates else None
        sr_number = str(facts.get("sr_number") or "")

        version_rows = [
            {
                "entry_uri": entry_uri,
                "version_date": version_dates[v_uri],
                "date_end_applicability": versions[v_uri].get("endApp") or None,
                "modified": versions[v_uri].get("mod") or None,
                "is_current": 1 if anchor_date and version_dates[v_uri] == anchor_date else 0,
            }
            for v_uri in sorted(versions, key=lambda v: version_dates[v])
        ]

        spawns: list[TaskSeed] = []
        if scope_all:
            for (v_uri, lang, url), pages in sorted(version_files.items()):
                if file_fmt_from_url(url) not in fmts:
                    continue
                if langs_filter and lang not in langs_filter:
                    continue
                spawns.append(
                    self._file_seed(entry_uri, sr_number, v_uri, version_dates[v_uri],
                                    lang, url, pages, titles, facts)
                )
        elif anchor_date:
            for (lang, url), pages in sorted(anchor_files.items()):
                if file_fmt_from_url(url) not in fmts:
                    continue
                if langs_filter and lang not in langs_filter:
                    continue
                spawns.append(
                    self._file_seed(entry_uri, sr_number, None, anchor_date,
                                    lang, url, pages, titles, facts)
                )

        entry_pointer = {"entry_uri": entry_uri, "latest_version_date": anchor_date}
        result = TaskResult(
            upsert_rows={"sr_entries": [entry_pointer]},
            replacements=[
                ReplaceRows(
                    table="sr_versions", match={"entry_uri": entry_uri}, rows=version_rows
                )
            ],
            next_tasks=spawns,
        )
        if not versions:
            result.expected_empty = (
                f"SR entry {entry_uri} has no member versions — ledger row only"
            )
        elif not spawns:
            result.expected_empty = (
                f"anchor version of {entry_uri} offers no file in the "
                f"requested formats/languages"
            )
        return result

    @staticmethod
    def _file_seed(
        entry_uri: str,
        sr_number: str,
        version_uri: str | None,
        version_date: str,
        lang: str,
        url: str,
        pages: str,
        titles: dict[str, str],
        facts: dict[str, Any],
    ) -> TaskSeed:
        meta: dict[str, str] = {
            "entry_uri": entry_uri,
            "sr_number": sr_number,
            "version_date": version_date,
            "in_force_status": str(facts.get("in_force_status") or ""),
            "graph_url": url,
        }
        if version_uri:
            meta["version_uri"] = version_uri
        if facts.get("basic_act"):
            meta["basic_act"] = str(facts["basic_act"])
        if facts.get("etype_de"):
            meta["native_type"] = str(facts["etype_de"])
        if pages:
            meta["pages"] = pages
        www_url = normalize_www_url(url)
        title = titles.get(lang) or titles.get("DEU") or sr_number or entry_uri
        return TaskSeed(
            type="che_file",
            params={
                "kind": "sr",
                "url": www_url,
                "path": raw_file_path("sr", www_url, sr_number or _uri_tail(entry_uri)),
                "title": title,
                "publication_date": version_date,
                "language": lang.lower(),
                "doc_type": doc_type_for(str(facts.get("etype_de") or "")),
                "entity_ref": f"sr_entries:{entry_uri}",
                "meta": meta,
            },
        )
