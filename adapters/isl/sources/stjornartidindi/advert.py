"""Task type ``stjornartidindi_advert``: one gazette advert, one request.

``GET /api/v1/adverts/{uuid}`` — a single JSON response carrying the
bibliographic set (issuer, native type, publication number, signature /
publication / system-entry dates, categories, status) **and** the body:
``document.html`` (the inline as-published text, e.g. a 2025 statute at
2,142,771 characters) plus ``document.pdfUrl``, the typeset original on
``adverts.stjornartidindi.is`` (probed 2026-09-17, samples in the task
folder). One request yields everything:

- the inline HTML is stored verbatim as the primary ``doc.html`` (the
  doc_id-carried file);
- the raw detail response is stored as the ``meta.json`` sibling (the
  lossless audit copy; its path travels in ``meta.files``);
- a body that is missing, empty, or merely the digitisation stub (the
  1995-2000 sparse era answers with one line like "C deild - Útgáfud.:
  26. september 2003" and no text; sample 32) seeds the
  ``stjornartidindi_pdf`` fallback — the PDF is that era's only body
  carrier, so a missing PDF there is a real gap and the pdf task keeps
  default 404 = permanent semantics.

Date semantics (probed 2026-09-17): ``publicationDate`` is the
publication timestamp for live-era items and the system-entry date for
retro-digitised ones — recorded as-is as the timeline date (the site's
own "Útg" display), with ``createdDate`` in meta telling the two apart.
The response's publication number must match the seed's (the listing
row and the detail are one identity); a mismatch is loud.
"""

from __future__ import annotations

import json
import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.isl.sources.stjornartidindi import (
    API_BASE,
    site_url_for,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["AdvertHandler", "map_doc_type"]

_DETAIL_URL = f"{API_BASE}/api/v1/adverts"

#: Native type word (type.title) -> controlled doc_type. The native word
#: is always kept in meta; cross-country typology is analysis-side. The
#: full 95-word vocabulary (probe 14) falls through to OTHER here; the
#: mapping is add-only (section 5.3 labelling rules).
_NATIVE_TO_TYPE: dict[str, str] = {
    "LÖG": "STATUTE",
    "REGLUGERÐ": "REGULATION",
    "GJALDSKRÁ": "REGULATION",
    "FORSETAÚRSKURÐUR": "DECREE",
}

#: Every advert body ends with a publication-date stamp line
#: ("A deild - Útgáfud.: 17. janúar 2025" — present in modern bodies too,
#: first seen in the trial run 2026-09-19 on a 464-char presidential
#: letter). A digitisation stub is a body that carries *nothing but* that
#: stamp (1995-2000 sparse era: "C deild - Útgáfud.: 26. september 2003",
#: probe 32) — so the test strips the stamp and checks whether any text
#: remains, not whether the stamp appears.
_STAMP_RE = re.compile(r"[ABC] deild\s*-\s*Útgáfud\.?:[^<]*$", re.IGNORECASE)
_STUB_MIN_BODY_CHARS = 40


def map_doc_type(native_type: str) -> str:
    return _NATIVE_TO_TYPE.get(native_type.strip().upper(), "OTHER")


def _is_stub_body(html: str) -> bool:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return len(_STAMP_RE.sub("", text).strip(" .:-")) < _STUB_MIN_BODY_CHARS


def _ts_date(timestamp: str) -> str | None:
    """``2026-09-16T14:01:51.777Z`` -> ``2026-09-16``; None when absent."""
    return timestamp[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", timestamp or "") else None


class AdvertHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=f"{_DETAIL_URL}/{task.params['id']}")

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        advert_id = str(task.params["id"])
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(
                f"stjornartidindi_advert {advert_id}: body is not JSON: {exc}"
            ) from exc
        advert = payload.get("advert")
        if not isinstance(advert, dict) or not advert:
            raise ValueError(
                f"stjornartidindi_advert {advert_id}: unexpected response shape "
                f"(keys={sorted(payload)!r})"
            )

        if str(advert.get("id") or "") != advert_id:
            raise ValueError(
                f"stjornartidindi_advert {advert_id}: response describes "
                f"{advert.get('id')!r} instead"
            )
        pub_number = advert.get("publicationNumber") or {}
        pub_num = str(pub_number.get("full") or "")
        seed_pub_num = str(task.params.get("pub_num", ""))
        if seed_pub_num and pub_num != seed_pub_num:
            raise ValueError(
                f"stjornartidindi_advert {advert_id}: seed says {seed_pub_num} but "
                f"the detail answers {pub_num} — listing/detail identity drift"
            )

        pub_ts = str(advert.get("publicationDate") or "")
        pub_date = _ts_date(pub_ts) or str(task.params.get("pub_date", ""))[:10] or None
        if pub_date is None:
            raise ValueError(
                f"stjornartidindi_advert {advert_id}: no usable publicationDate "
                f"({pub_ts!r})"
            )

        meta: dict[str, str] = {"advert_id": advert_id}
        if pub_num:
            meta["pub_num"] = pub_num
            number = str(pub_number.get("number") or "")
            year = str(pub_number.get("year") or "")
            if number:
                meta["pub_number"] = number
            if year:
                meta["pub_year"] = year
        for key in ("status", "signatureDate", "createdDate", "updatedDate"):
            value = str(advert.get(key) or "")
            if value:
                meta[key[0].lower() + key[1:]] = value
        if pub_ts:
            meta["publication_ts"] = pub_ts
        deild = (advert.get("department") or {}).get("slug") or str(
            task.params.get("deild", "")
        )
        if deild:
            meta["deild"] = deild
        native = (advert.get("type") or {}).get("title") or str(
            task.params.get("native_type", "")
        )
        if native:
            meta["native_type"] = native
        type_slug = (advert.get("type") or {}).get("slug") or ""
        if type_slug:
            meta["type_slug"] = type_slug
        main_type = (advert.get("mainType") or {}).get("title") or ""
        if main_type:
            meta["main_type"] = main_type
        involved = (advert.get("involvedParty") or {}).get("title") or str(
            task.params.get("involved_party", "")
        )
        if not involved:
            raise ValueError(
                f"stjornartidindi_advert {advert_id}: no issuing authority in the "
                "detail nor the listing row — both shapes empty is a change"
            )
        national_id = str((advert.get("involvedParty") or {}).get("nationalId") or "")
        if national_id:
            meta["involved_party_national_id"] = national_id
        categories = [
            str(c.get("title") or "")
            for c in (advert.get("categories") or [])
            if isinstance(c, dict)
        ]
        if any(categories):
            meta["categories"] = ",".join(c for c in categories if c)
        for key in ("attachments", "corrections"):
            # Probed shapes are empty arrays (samples 20/32); anything else
            # is preserved whole in meta rather than structured on the spot.
            if advert.get(key):
                meta[key] = json.dumps(advert[key], ensure_ascii=False, sort_keys=True)

        document = advert.get("document") or {}
        html_body = str(document.get("html") or "")
        pdf_url = str(document.get("pdfUrl") or "")
        if pdf_url:
            meta["pdf_url"] = pdf_url
        meta["is_legacy"] = str(document.get("isLegacy") or "")
        meta["api_url"] = f"{_DETAIL_URL}/{advert_id}"
        scope = str(task.params.get("scope_slice", ""))
        if scope:
            meta["scope_slice"] = scope

        # Folder = gazette volume year (publicationNumber.year, the axis
        # reliable across retro-digitised items whose publicationDate is
        # their system-entry date) + the zero-padded issue number.
        number = str(pub_number.get("number") or "")
        year = str(pub_number.get("year") or "") or str(task.params.get("year", ""))
        folder_stem = f"{int(number):04d}-{year}" if number.isdigit() and year else (pub_num.replace("/", "-") or advert_id)
        folder = f"01_raw/stjornartidindi/{year or pub_date[:4]}/{folder_stem}"

        source_url = site_url_for(advert_id)
        doc_id = compute_doc_id("ISL", source_url, pub_date)

        html_missing = not html_body.strip()
        if html_missing and not pdf_url:
            raise ValueError(
                f"stjornartidindi_advert {advert_id}: no HTML body and no pdfUrl "
                f"(html={len(html_body)} chars) — an advert without any body "
                "carrier is an unexplained shape"
            )

        files: list[FileOut] = [FileOut(path=f"{folder}/meta.json", content=response.content)]
        next_tasks: list[TaskSeed] = []
        siblings = ["meta.json"]
        if html_missing:
            # No HTML at all: the PDF becomes the primary carrier — the
            # pdf task fetches it and takes the doc_id (one file per
            # doc_id carries it, section 6.9).
            next_tasks.append(
                TaskSeed(
                    type="stjornartidindi_pdf",
                    params={
                        "id": advert_id,
                        "pdf_url": pdf_url,
                        "path": f"{folder}/doc.pdf",
                        "doc_id": doc_id,
                    },
                )
            )
        else:
            if _is_stub_body(html_body):
                # Digitisation stub ("C deild - Útgáfud.: …"): the stub
                # page stays the primary file (raw_format=html), the PDF
                # rides in as the body-carrying sibling.
                siblings.append("doc.pdf")
                next_tasks.append(
                    TaskSeed(
                        type="stjornartidindi_pdf",
                        params={"id": advert_id, "pdf_url": pdf_url, "path": f"{folder}/doc.pdf"},
                    )
                )
            files.append(
                FileOut(path=f"{folder}/doc.html", content=html_body.encode("utf-8"), doc_id=doc_id)
            )
        meta["files"] = ",".join(siblings)

        title = str(advert.get("title") or "") or str(task.params.get("title", ""))
        if not title:
            raise ValueError(f"stjornartidindi_advert {advert_id}: no title anywhere")
        record = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=pub_date,
            issuing_authority=involved,
            doc_type=map_doc_type(native),
            language="isl",
            raw_metadata=meta,
        )
        return TaskResult(
            documents=[record],
            files=files,
            next_tasks=next_tasks,
        )
