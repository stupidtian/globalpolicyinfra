"""Task type ``rt_act``: one document version, one request.

``GET /public-api/api/v1/akt/{globaalID}/blob-xml`` — the full act XML in
the source's own Juurakt schema (probed 2026-10-27, samples in the task
folder). One response carries the bibliographic block AND the body, so one
request is one document:

- the raw XML is stored verbatim as the primary file
  (``01_raw/riigiteataja/{publication year}/{globaalID}.xml``);
- the bibliographic block (``metaandmed``) is parsed into the documents
  row: publication mark (part / date / issue / article — the timeline
  date), adoption and promulgation dates, validity window, issuing
  authority, native type, version fields, amendment marks.

Date semantics: ``avaldamismarge/avaldamineKuupaev`` is the official
publication date of THIS version — the publication event of an as-published
original or the republication event of a consolidated text (the text-layer
word ``tekstiliik`` tells the two apart and travels in meta); adoption
(``vastuvoetud/aktikuupaev``), promulgation and validity are separate
fields, never merged into it. Timestamps carry a tz suffix
(``2002-05-27+03:00``) and are normalized to their date part.

Out-of-scope shape: a publication mark of part ``RT V`` is the
English-translation series — collected nowhere (the corpus here is the
Estonian-language one); answered as an explained empty, task still done.
"""

from __future__ import annotations

import json
import re
from xml.etree import ElementTree

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.est.sources.riigiteataja import (
    PUBLIC_API_BASE,
    REQUEST_HEADERS,
    site_url_for,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["ActHandler", "map_doc_type"]

#: Native type word (dokumentLiik) -> controlled doc_type. The native word
#: is always kept in meta; cross-country typology is analysis-side. The
#: source's 25-word vocabulary (incl. välisleping, teadaanne) falls
#: through to OTHER; the mapping is add-only (section 5.3 labelling rules).
_NATIVE_TO_TYPE: dict[str, str] = {
    "seadus": "STATUTE",
    "määrus": "REGULATION",
    "korraldus": "SECONDARY_LEGISLATION",
    "käskkiri": "SECONDARY_LEGISLATION",
}

_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")

#: English-translation series (RT V) — see module docstring.
_TRANSLATION_PART = "RT V"


def map_doc_type(native_type: str) -> str:
    return _NATIVE_TO_TYPE.get(native_type.strip().lower(), "OTHER")


def _local(tag: str) -> str:
    return tag.rpartition("}")[2]


def _children(el: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in el if _local(child.tag) == name]


def _child(el: ElementTree.Element, name: str) -> ElementTree.Element | None:
    found = _children(el, name)
    return found[0] if found else None


def _text(el: ElementTree.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    stripped = el.text.strip()
    return stripped or None


def _child_text(el: ElementTree.Element, name: str) -> str | None:
    return _text(_child(el, name))


def _grandchild_text(el: ElementTree.Element, middle: str, name: str) -> str | None:
    middle_el = _child(el, middle)
    return _text(_child(middle_el, name)) if middle_el is not None else None


def _date_part(raw: str | None) -> str | None:
    """``2002-05-27+03:00`` -> ``2002-05-27``; None when absent."""
    if not raw:
        return None
    match = _DATE_PREFIX.match(raw)
    return match.group(1) if match else raw


def _as_path_dict(el: ElementTree.Element) -> dict[str, str]:
    """Flatten one metadata subtree into ``path -> text`` (deterministic
    lossless serialisation for repeatable blocks like muutmismarge)."""
    flat: dict[str, str] = {}

    def walk(node: ElementTree.Element, prefix: str) -> None:
        texts = _text(node)
        if texts and node is not el:
            flat[prefix] = texts
            return
        for child in node:
            walk(child, f"{prefix}/{_local(child.tag)}" if prefix else _local(child.tag))

    walk(el, _local(el.tag))
    return flat


class ActHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{PUBLIC_API_BASE}/akt/{task.params['id']}/blob-xml",
            headers=REQUEST_HEADERS,
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        act_id = str(task.params["id"])
        label = f"rt_act {act_id}"
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise ValueError(f"{label}: body is not XML: {exc}") from exc
        meta = _child(root, "metaandmed")
        if meta is None:
            raise ValueError(
                f"{label}: no metaandmed block (root={_local(root.tag)!r}) — "
                "act shape may have changed"
            )

        xml_id = _child_text(meta, "globaalID")
        group_id = _child_text(meta, "terviktekstiGrupiID") or ""
        # Identity: the answering document is the requested version either
        # by id or by version-group membership. Trial-run shape 2026-10-27
        # (globaalID 103112010012): a numeric sweep id whose blob answers a
        # UUID-keyed document of the SAME group (the source's re-keyed
        # migration form; the metadata endpoint still reports the numeric
        # id as kehtivId). The ledger keeps the sweep id; the answered id
        # travels in meta.
        seed_group = str(task.params.get("group", ""))
        if xml_id != act_id:
            if seed_group and group_id == seed_group:
                meta_out_drift = {"answered_globaal_id": xml_id or ""}
            else:
                raise ValueError(
                    f"{label}: response describes {xml_id!r} instead — "
                    "sweep/detail identity drift"
                )
        else:
            meta_out_drift = {}
        issuer = _child_text(meta, "valjaandja") or str(task.params.get("valjaandja", ""))
        if not issuer:
            raise ValueError(f"{label}: no issuing authority in the XML nor the seed row")

        adopted_el = _child(meta, "vastuvoetud")
        adopted_date = _date_part(_child_text(adopted_el, "aktikuupaev") if adopted_el is not None else None)

        # Publication date, with the legacy-era fallback chain (trial-run
        # shapes 2026-10-27): the modern current publication mark carries
        # avaldamineKuupaev; migrated pre-2010 items may carry only the
        # ORIGINAL publication mark inside vastuvoetud (the RTL series,
        # sometimes without a date child either); some carry no publication
        # mark but an adoption date; a last group of 2002-2004 migration
        # items carries NO date except the validity start (kehtivuseAlgus),
        # which then stands in. The basis always travels in meta so the
        # four cases stay apart; an item with no date at all stays loud.
        pub_mark = _child(meta, "avaldamismarge")
        pub_ts = _child_text(pub_mark, "avaldamineKuupaev") if pub_mark is not None else None
        basis = "publication_mark"
        orig_mark = _child(adopted_el, "avaldamismarge") if adopted_el is not None else None
        if not pub_ts and orig_mark is not None:
            pub_ts = _child_text(orig_mark, "avaldamineKuupaev")
            if pub_ts:
                basis = "original_publication_mark"
        if not pub_ts and adopted_date:
            pub_ts = adopted_date
            basis = "adoption_date"
        validity = _child(meta, "kehtivus")
        validity_start = _date_part(_child_text(validity, "kehtivuseAlgus")) if validity is not None else None
        if not pub_ts and validity_start:
            pub_ts = validity_start
            basis = "validity_start"
        pub_date = _date_part(pub_ts)
        if not pub_date or not re.match(r"^\d{4}-\d{2}-\d{2}$", pub_date):
            raise ValueError(
                f"{label}: no usable publication date in the publication marks, "
                f"the adoption date nor the validity start "
                f"(avaldamineKuupaev={pub_ts!r}, aktikuupaev={adopted_date!r}) — "
                "an undated version is an unexplained shape"
            )
        # The mark fields (part / issue / article / reference) come from the
        # current publication mark, falling back to the original one for
        # migrated items that carry only that.
        eff_mark = pub_mark if pub_mark is not None else orig_mark
        rt_part = _child_text(eff_mark, "RTosa") if eff_mark is not None else ""
        if rt_part is not None and rt_part.strip().upper() == _TRANSLATION_PART:
            return TaskResult(
                expected_empty=(
                    f"{label}: RT V publication mark — the English-translation "
                    "series is outside the Estonian-language corpus"
                )
            )
        rt_part = rt_part or ""

        promulgation = _child(adopted_el, "valjakuulutamine") if adopted_el is not None else None
        if promulgation is None:
            promulgation = _child(meta, "valjakuulutamine")
        version = _child(meta, "versioon")

        meta_out: dict[str, str] = {
            "globaal_id": act_id,
            "publication_date_basis": basis,
            **meta_out_drift,
        }
        for xml_name, meta_name in (
            ("tekstiliik", "tekstiliik"),
            ("dokumentLiik", "dokument_liik"),
            ("dokumentEtapp", "dokument_etapp"),
            ("dokumentStaatus", "dokument_staatus"),
            ("skeemiNimi", "skeem"),
            ("terviktekstiGrupiID", "group_id"),
            ("metaandmedVersioon", "meta_version"),
            ("metaandmedVersioonKuupaev", "meta_version_date"),
            ("metaandmedVersioonPohjustaja", "meta_version_by"),
        ):
            value = _child_text(meta, xml_name)
            if value:
                meta_out[meta_name] = value
        if adopted_date:
            meta_out["adopted_date"] = adopted_date
        if adopted_el is not None:
            joustumine = _date_part(_child_text(adopted_el, "joustumine"))
            if joustumine:
                meta_out["entry_into_force"] = joustumine
        if promulgation is not None:
            promulgated = _child(promulgation, "valjakuulutatud")
            meta_out["promulgation"] = json.dumps(
                _as_path_dict(promulgated if promulgated is not None else promulgation),
                ensure_ascii=False,
                sort_keys=True,
            )
        if rt_part:
            meta_out["rt_part"] = rt_part
        for xml_name, meta_name in ("RTnr", "rt_number"), ("RTartikkel", "rt_article"):
            value = _child_text(eff_mark, xml_name) if eff_mark is not None else None
            if value:
                meta_out[meta_name] = value
        akt_viide = _child_text(eff_mark, "aktViide") if eff_mark is not None else None
        if akt_viide:
            meta_out["akt_viide"] = akt_viide
        if validity is not None:
            validity_end = _date_part(_child_text(validity, "kehtivuseLopp"))
            if validity_start:
                meta_out["validity_start"] = validity_start
            if validity_end:
                meta_out["validity_end"] = validity_end
        if version is not None:
            version_no = _child_text(version, "dokumentVersioon")
            version_date = _date_part(_child_text(version, "dokumentVersioonKuupaev"))
            if version_no:
                meta_out["document_version"] = version_no
            if version_date:
                meta_out["document_version_date"] = version_date
        keywords = [text for el in _children(meta, "marksona") if (text := _text(el))]
        if keywords:
            meta_out["keywords"] = ",".join(keywords)
        # Amendment marks are root-level siblings of metaandmen (the
        # publication block closes first), probed 2026-10-27.
        amendment_marks = [
            json.dumps(_as_path_dict(mark), ensure_ascii=False, sort_keys=True)
            for mark in _children(root, "muutmismarge")
        ]
        if amendment_marks:
            meta_out["amendment_marks"] = "\n".join(amendment_marks)
        seed_liik = str(task.params.get("liik", ""))
        native_type = _child_text(meta, "dokumentLiik") or seed_liik
        meta_out["native_type"] = native_type
        scope = str(task.params.get("scope_slice", ""))
        if scope:
            meta_out["scope_slice"] = scope

        title_el = _child(root, "aktinimi")
        title = _grandchild_text(title_el, "nimi", "pealkiri") if title_el is not None else None
        if not title:
            title = str(task.params.get("title", ""))
        if not title:
            raise ValueError(f"{label}: no title in the XML nor the seed row")

        seed_issuer = str(task.params.get("valjaandja", ""))
        if seed_issuer and seed_issuer != issuer:
            raise ValueError(
                f"{label}: seed says issuer {seed_issuer!r} but the XML answers "
                f"{issuer!r} — sweep/detail identity drift"
            )

        source_url = site_url_for(act_id)
        doc_id = compute_doc_id("EST", source_url, pub_date)
        folder = f"01_raw/riigiteataja/{pub_date[:4]}"
        record = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=pub_date,
            issuing_authority=issuer,
            doc_type=map_doc_type(native_type),
            language="est",
            raw_metadata=meta_out,
        )
        return TaskResult(
            documents=[record],
            files=[
                FileOut(
                    path=f"{folder}/{act_id}.xml",
                    content=response.content,
                    doc_id=doc_id,
                )
            ],
        )
