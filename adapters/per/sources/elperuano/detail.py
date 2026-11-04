"""Task type ``per_norm_detail``: one portal-era norm, one request, one document.

Two carriers arrive under this task type (decided by the URL the listing
handed over):

- **device page** (``busquedas.elperuano.pe/dispositivo/…``): the SSR page
  embeds the whole norm as a standalone XHTML document inside
  ``div#visor-html`` — ``h1.sumilla`` (title), two ``h2`` (type, number),
  the "Lima, date" line and the body's ``p.cuerpo`` paragraphs. The page
  bytes are stored verbatim; the title comes from the page itself, the
  issuing authority rides in from the listing (the page does not carry
  it).
- **special supplement PDF** (``epdoc2…/VistaNLSE.asp``): some
  extraordinary norms ship as a one-norm "SEPARATA ESPECIAL" PDF instead
  of a device page; its URL decodes to ``{norm_id}{YYYYMMDD}``. Title
  words come from the listing via task params (a PDF carries no HTML
  metadata).

Both register the document here (``produced_by`` = this task type, which
is what scopes the clean declaration to portal-era carriers only).
"""

from __future__ import annotations

import base64
import binascii
import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.per.sources.elperuano import device_file_path, map_doc_type
from core.document import DocumentRecord, compute_doc_id

__all__ = ["PerNormDetailHandler"]

_SUPPLEMENT_REF = re.compile(r"Referencias=([A-Za-z0-9+/=]+)")
_ID_DATE = re.compile(r"^(?P<norm_id>.+?)(?P<ymd>\d{8})$")


def _reference_norm_id(url: str) -> str:
    """VistaNLSE URL -> the norm id it delivers (base64 reference is
    ``{norm_id}{YYYYMMDD}``, e.g. ``2447008-120251010`` -> ``2447008-1``)."""
    match = _SUPPLEMENT_REF.search(url)
    if match is None:
        raise ValueError(f"supplement URL {url!r} carries no Referencias")
    try:
        decoded = base64.b64decode(match.group(1), validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(f"supplement URL {url!r}: undecodable Referencias ({exc})") from None
    split = _ID_DATE.match(decoded)
    if split is None:
        raise ValueError(
            f"supplement URL {url!r}: decoded reference {decoded!r} does not end "
            "in an 8-digit date"
        )
    return split.group("norm_id")


class PerNormDetailHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(url=str(task.params["url"]))

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        url = str(task.params["url"])
        date_iso = str(task.params["date"])
        authority = str(task.params.get("authority", ""))
        edicion = str(task.params.get("edicion", "NL"))

        if "/dispositivo/" in url:
            return self._parse_device(response, task, url, date_iso, authority, edicion)
        if "VistaNLSE.asp" in url:
            return self._parse_supplement(response, task, url, date_iso, authority, edicion)
        raise ValueError(f"detail {url!r}: neither a device page nor a supplement URL")

    def _parse_device(
        self,
        response: Response,
        task: TaskView,
        url: str,
        date_iso: str,
        authority: str,
        edicion: str,
    ) -> TaskResult:
        from bs4 import BeautifulSoup, Tag

        data_id = url.rstrip("/").rsplit("/", 1)[-1]
        if not re.fullmatch(r"[0-9]+-[0-9]+", data_id):
            raise ValueError(f"device URL {url!r}: tail {data_id!r} is not a norm id")
        soup = BeautifulSoup(response.content, "html.parser")
        visor = soup.select_one("div#visor-html")
        if visor is None:
            raise ValueError(f"device page {data_id}: no embedded visor (div#visor-html)")

        sumilla_el = visor.select_one("h1.sumilla")
        sumilla = sumilla_el.get_text(" ", strip=True) if isinstance(sumilla_el, Tag) else ""
        headings = [
            el.get_text(" ", strip=True)
            for el in visor.select("h2")
            if isinstance(el, Tag) and el.get_text(strip=True)
        ]
        params_designation = str(task.params.get("designation", ""))
        designation = " ".join(headings) or params_designation or data_id
        # title rungs: page sumilla -> the embedded document's own <title>
        # (probed 2026-11-02: not every device page carries h1/h2 — an
        # extraordinary decreto de urgencia renders its type into plain
        # paragraphs and keeps only the <title>) -> listing words -> id
        embedded_title = visor.find("title")
        embedded = embedded_title.get_text(" ", strip=True) if embedded_title is not None else ""
        title = (
            sumilla
            or embedded
            or str(task.params.get("sumilla", ""))
            or params_designation
            or data_id
        )

        meta: dict[str, str] = {
            "era": "device",
            "data_id": data_id,
            "designation": designation,
            "edicion": edicion,
            **({"sumilla": str(task.params["sumilla"])} if task.params.get("sumilla") else {}),
            **({"annex_ids": str(task.params["annex_ids"])} if task.params.get("annex_ids") else {}),
        }
        path = device_file_path(data_id, "html")
        document = DocumentRecord(
            title=title,
            source_url=url,
            publication_date=date_iso,
            issuing_authority=authority or None,
            doc_type=map_doc_type(designation),
            language="spa",
            raw_metadata=meta,
        )
        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=compute_doc_id(
                "PER", url, date_iso
            ))],
        )

    def _parse_supplement(
        self,
        response: Response,
        task: TaskView,
        url: str,
        date_iso: str,
        authority: str,
        edicion: str,
    ) -> TaskResult:
        if not response.content.startswith(b"%PDF-"):
            raise ValueError(
                f"supplement {url!r}: response is not a PDF (head={response.content[:8]!r})"
            )
        norm_id = _reference_norm_id(url)
        designation = str(task.params.get("designation", "")) or norm_id
        sumilla = str(task.params.get("sumilla", ""))
        meta: dict[str, str] = {
            "era": "separata",
            "data_id": norm_id,
            "designation": designation,
            "edicion": edicion,
            **({"sumilla": str(task.params["sumilla"])} if task.params.get("sumilla") else {}),
            **({"annex_ids": str(task.params["annex_ids"])} if task.params.get("annex_ids") else {}),
        }
        path = device_file_path(norm_id, "pdf")
        document = DocumentRecord(
            title=sumilla or designation,
            source_url=url,
            publication_date=date_iso,
            issuing_authority=authority or None,
            doc_type=map_doc_type(designation),
            language="spa",
            raw_metadata=meta,
        )
        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=compute_doc_id(
                "PER", url, date_iso
            ))],
        )
