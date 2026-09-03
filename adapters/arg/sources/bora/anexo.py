"""Task type ``bora_anexo``: one attachment PDF of one gazette entry.

GET ``/pdf/download_anexo`` with every selector in the URL (``seccion``,
``nroAnexo``, ``idAnexo``, ``fechaPublicacion``) — GET is byte-identical to
the browser's POST (probed 2026-09-02: both answer the same 130,353-byte
JSON). The response is ``{"pdfBase64": "…"}``; the decoded bytes land next
to the parent entry as ``anexo_{nro}.pdf``.

Attachments are integral parts of the norm — the notice text says the
anexos "se publican en la edición web" (the print edition does not carry
them; probed 2026-08-28 on Resolución 247/2026 with its two anexos). The
file carries no doc_id: the parent document row (written earlier by
bora_detalle) already pre-declared this filename in its meta.files, and
the documents table is insert-only — the attachment is a sibling file,
not a separate document.
"""

from __future__ import annotations

import base64
import binascii

from adapters.arg.sources.bora import BASE_URL, XHR_HEADERS
from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView

__all__ = ["BoraAnexoHandler"]


class BoraAnexoHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=f"{BASE_URL}/pdf/download_anexo",
            params={
                "seccion": str(task.params["seccion"]),
                "nroAnexo": str(task.params["nro"]),
                "idAnexo": str(task.params["id_anexo"]),
                "fechaPublicacion": str(task.params["fecha"]),
            },
            headers=dict(XHR_HEADERS),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        nro = str(task.params["nro"])
        payload = response.json()
        b64 = payload.get("pdfBase64")
        if not b64 or not isinstance(b64, str):
            raise ValueError(
                f"anexo {task.params['id_anexo']} nro {nro}: response carries no "
                f"pdfBase64 (keys={sorted(payload)})"
            )
        try:
            pdf = base64.b64decode(b64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(
                f"anexo {task.params['id_anexo']} nro {nro}: body is not base64: {exc}"
            ) from exc
        if not pdf.startswith(b"%PDF"):
            raise ValueError(
                f"anexo {task.params['id_anexo']} nro {nro}: decoded body is not a PDF"
            )
        fecha = str(task.params["fecha"])
        # Path keys off the parent aviso's *page* publication date ("pub",
        # passed by bora_detalle) — same identity axis as the parent's
        # source_url; "fecha" stays the request selector the page embedded.
        pub = str(task.params.get("pub") or fecha)
        path = f"01_raw/bora/{pub[:4]}/D{pub}/{task.params['aviso_id']}/anexo_{nro}.pdf"
        return TaskResult(files=[FileOut(path=path, content=pdf)])
