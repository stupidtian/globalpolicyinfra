"""Task types ``cze_info`` / ``cze_doc`` / ``cze_odkazy``: one act's
metadata assembly and download-pointer resolution, on the versioned alias.

Three requests, three tasks, one reason each (section 6 one-request
contract + the INSERT-OR-IGNORE documents ledger):

* ``cze_info``  GET …/dalsi-informace — the type trio (typAktuKod /
  podtypAktuKod / druhPravnihoAktuKod) and the approval date live ONLY
  here (probed 2026-10-15). The documents row must be complete in the one
  task that emits it, so this response rides into cze_doc's params.
* ``cze_doc``   GET …/{alias} (detail root) — the document itself:
  publication timestamp (exact to the millisecond for electronic-era
  entries, midnight for the print era), ELI, effectiveness window, the
  Collection issue (částka). Cross-checks the register row on number,
  title and date — a mismatch is a shape change, escalated loudly.
* ``cze_odkazy`` GET …/odkazy-ke-stazeni — resolves the informative
  package's dokumentId on the alias address. Probed across eras
  (2026-10-15, corrected the same day): the ALIAS-level informativni id
  serves the as-declared original text for EVERY era — 8/1918, 99/1963,
  262/2006 and 2016/222 all carry undated stems, and 2016/222's XML
  verifiably lacks § 22a (an amendment-era section) — the original, not
  the consolidation. (The DATED stems belong to current-version ids taken
  from act-level pointers — never used here; an early probe misattributed
  one, hence the earlier print-era "metadata-only" design, now corrected.)
  A response with no usable package id is a loud escalation.

Response shapes (probed 2026-10-15 on both eras; byte-true samples in the
task folder's probe archive)::

    dalsi:   {"cisloPredpisu": "1", "podtypAktuKod": "VYHLASKA",
              "typAktuKod": "PRAVPRED", "druhPravnihoAktuKod": "CISTNOV",
              "datumSchvaleni": "2025-12-29", "uzemneZavazneCR": true, …}
    root:    {"datumCasVyhlaseni": "2026-01-08T13:09:27.614+01:00",
              "staleUrl": "/sb/2026/1/0000-00-00", "typZneni": "VYHLASENE",
              "nazev": "Vyhláška,  kterou se mění …", "eli": "/eli/cz/sb/2026/1/0000-00-00",
              "cisloCastky": "1", "rokCastky": 2026, "kodDokumentuSbirky": "1/2026 Sb.",
              "datumUcinnostiOd": "2026-01-11", "datumUcinnostiDo": null,
              "sbirkaKod": "sb", "dokumentBaseId": 4484, …}
    odkazy:  {"informativniZneni": {"odkazPdf": {"dokumentId": 4484}},
              "pravneZavazneZneni": {…}, "overeneZneni": {…}}   (blocks vary
            by era; the informativni id — present in every probed shape,
            both eras — is the one this source consumes)
"""

from __future__ import annotations

import re
from typing import Any

from adapters.base import RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.cze.sources.esbirka import (
    api_doc_url,
    canonical_url,
    guard_block_page,
    guard_waf,
    map_doc_type,
    stale_parts,
)
from core.document import DocumentRecord

__all__ = [
    "CzeDocHandler",
    "CzeInfoHandler",
    "CzeOdkazyHandler",
    "squash",
]


def squash(text: str) -> str:
    """Collapse whitespace runs — Czech titles arrive with double spaces on
    both the register and the detail payload (probed both eras)."""
    return re.sub(r"[\s ]+", " ", text).strip()


def _json_object(response: Response, label: str) -> dict[str, Any]:
    guard_waf(response.status_code, label)
    if response.status_code != 200:
        raise ValueError(f"{label} returned HTTP {response.status_code}")
    guard_block_page(response.content, label)
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"{label} did not return a JSON object")  # noqa: TRY004
    return data


def _require_str(data: dict[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} carries no usable {key!r}")
    return value.strip()


class CzeInfoHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=api_doc_url(str(task.params["stale"]), "/dalsi-informace"),
            headers={"Accept": "application/json"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        stale = str(params["stale"])
        data = _json_object(response, f"dalsi-informace of {stale}")

        number = _require_str(data, "cisloPredpisu", f"dalsi-informace of {stale}")
        _coll, _year, want, _ver = stale_parts(stale)
        if number != want:
            raise ValueError(
                f"dalsi-informace of {stale} numbers itself {number!r}, "
                f"the address says {want!r}"
            )
        podtyp = _require_str(data, "podtypAktuKod", f"dalsi-informace of {stale}")

        merged = dict(params)
        merged["podtyp_aktu"] = podtyp
        for source, target in (("typAktuKod", "typ_aktu"),
                               ("druhPravnihoAktuKod", "druh_aktu")):
            value = data.get(source)
            if isinstance(value, str) and value.strip():
                merged[target] = value.strip()
        approval = data.get("datumSchvaleni")
        if isinstance(approval, str) and approval.strip():
            merged["datum_schvaleni"] = approval.strip()[:10]
        territorial = data.get("uzemneZavazneCR")
        if isinstance(territorial, bool):
            merged["uzemne_zavazne_cr"] = territorial
        return TaskResult(next_tasks=[TaskSeed(type="cze_doc", params=merged)])


class CzeDocHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=api_doc_url(str(task.params["stale"])),
            headers={"Accept": "application/json"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        stale = str(params["stale"])
        coll, year, _number, _ver = stale_parts(stale)
        data = _json_object(response, f"detail of {stale}")

        # Era/alias guards: capture targets the as-declared text only.
        typ_zneni = _require_str(data, "typZneni", f"detail of {stale}")
        if typ_zneni != "VYHLASENE":
            raise ValueError(
                f"detail of {stale} is a {typ_zneni!r} version — the alias "
                "address stopped resolving to the as-declared text"
            )
        sbirka = _require_str(data, "sbirkaKod", f"detail of {stale}")
        if sbirka != coll:
            raise ValueError(
                f"detail of {stale} claims collection {sbirka!r}, address says {coll!r}"
            )
        echoed = data.get("staleUrl")
        if isinstance(echoed, str) and echoed.strip() and echoed.strip() != stale:
            raise ValueError(
                f"detail of {stale} echoes address {echoed.strip()!r}"
            )

        # Register × detail cross-checks — a mismatch is a shape change.
        kod = _require_str(data, "kodDokumentuSbirky", f"detail of {stale}")
        if squash(kod) != str(params["kod"]):
            raise ValueError(
                f"detail of {stale} numbers itself {kod!r}, register said "
                f"{params['kod']!r}"
            )
        nazev = _require_str(data, "nazev", f"detail of {stale}")
        if squash(nazev) != str(params["nazev"]):
            raise ValueError(
                f"detail of {stale} titles itself {squash(nazev)!r}, register "
                f"said {str(params['nazev'])!r}"
            )
        declared = _require_str(data, "datumCasVyhlaseni", f"detail of {stale}")
        publication_date = declared[:10]
        if publication_date != str(params["datum"]):
            raise ValueError(
                f"detail of {stale} declares publication {publication_date!r}, "
                f"register said {params['datum']!r}"
            )

        meta: dict[str, str] = {
            "kod_dokumentu": str(params["kod"]),
            "rok": year,
            "sbirka_kod": coll,
            "typ_zneni": typ_zneni,
            "datum_cas_vyhlaseni": declared,
            "podtyp_aktu": str(params["podtyp_aktu"]),
        }
        for source in ("typ_aktu", "druh_aktu", "datum_schvaleni", "stav"):
            value = params.get(source)
            if value is not None:
                meta[source] = str(value)
        if "uzemne_zavazne_cr" in params:
            meta["uzemne_zavazne_cr"] = "true" if params["uzemne_zavazne_cr"] else "false"
        for key, meta_key in (("eli", "eli"), ("cisloCastky", "cislo_castky"),
                              ("dokumentBaseId", "dokument_base_id")):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                meta[meta_key] = value.strip()
            elif isinstance(value, int):
                meta[meta_key] = str(value)
        rok_castky = data.get("rokCastky")
        if isinstance(rok_castky, int):
            meta["rok_castky"] = str(rok_castky)
        for key, meta_key in (
                ("datumUcinnostiOd", "datum_ucinnosti_od"),
                ("datumUcinnostiDo", "datum_ucinnosti_do"),
                ("datumUcinnostiZneniOd", "datum_ucinnosti_zneni_od"),
                ("datumUcinnostiZneniDo", "datum_ucinnosti_zneni_do"),
                ("nikdyNebylUcinny", "nikdy_nebyl_ucinny")):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                meta[meta_key] = value.strip()[:10]
            elif value is True:
                meta[meta_key] = "true"

        record = DocumentRecord(
            title=squash(nazev),
            source_url=canonical_url(stale),
            publication_date=publication_date,
            doc_type=map_doc_type(str(params["podtyp_aktu"])),
            language="ces",
            raw_metadata=meta,
        )
        # The download chain carries the authoritative publication date so
        # cze_file recomputes the very same doc_id the FileOut must point at.
        return TaskResult(
            documents=[record],
            next_tasks=[TaskSeed(
                type="cze_odkazy",
                params={"stale": stale, "datum": publication_date},
            )],
        )


class CzeOdkazyHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=api_doc_url(str(task.params["stale"]), "/odkazy-ke-stazeni"),
            headers={"Accept": "application/json"},
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        stale = str(params["stale"])
        data = _json_object(response, f"odkazy of {stale}")

        # The informative package on the alias address — version-faithful
        # for every era (probed 1918/1963/2006/2016/2026, download-level;
        # 2016/222's XML lacks the amendment-era § 22a — the original).
        # The binding-text and verified-scan blocks ride along in the
        # response but are deliberately not consumed (no-PDF ruling).
        package = data.get("informativniZneni")
        if not (isinstance(package, dict)
                and isinstance(package.get("odkazPdf"), dict)
                and isinstance(package["odkazPdf"].get("dokumentId"), int)):
            raise ValueError(  # noqa: TRY004
                f"odkazy of {stale} carries no informativni package id "
                "(keys: "
                f"{sorted(package) if isinstance(package, dict) else package!r})"
            )
        return TaskResult(next_tasks=[TaskSeed(
            type="cze_fetch",
            params={**params, "kanal": "informativni",
                    "did": package["odkazPdf"]["dokumentId"]},
        )])
