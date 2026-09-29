"""Task type ``rg_item``: one gazette item file, one request, one document.

GET the item's own file under ``/eskiler/`` and store the response bytes
verbatim as the document's primary file. Two probed forms (2026-09-27):

- **htm** — a Word-exported HTML in the **Windows-1254** code page. Its
  header block repeats the issue date, ``Sayı : 33382``, the native type
  word, the issuing authority line (``Ticaret Bakanlığından:``) and an
  uppercase title. The block enriches the record (authority is otherwise
  unavailable) and cross-checks the seed: a mismatching issue number or
  date means the wrong file came back and fails loudly. A headerless htm
  is tolerated (old-era shapes) — the seed's fields stand.
- **pdf** — the original typeset. No metadata inside; every bibliographic
  field comes from the seed. The bytes must start with ``%PDF-``; an html
  body under a ``.pdf`` name is the source lying and fails loudly (the
  sibling mevzuat file endpoint is known to answer 200+html for missing
  files, so the magic check is deliberate).

The title always comes from the fihrist anchor text (readable mixed case,
uniform across htm/pdf); the htm header's uppercase title is kept in meta
as ``native_title`` when parseable. Document reference numbers are scraped
from the title with two conservative patterns only (a leading ``2014/7021``
BKK number and an explicit ``Karar Sayısı: 11752``); anything else stays
unparsed for the analysis side.
"""

from __future__ import annotations

import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.tur.sources.resmigazete import item_url
from core.document import DocumentRecord, compute_doc_id

__all__ = ["RgItemHandler", "map_doc_type"]

_PDF_MAGIC = b"%PDF-"

_TYPE_TO_DOC_TYPE: dict[str, str] = {
    "KANUNLAR": "STATUTE",
    "KANUN": "STATUTE",
    "KANUN HÜKMÜNDE KARARNAMELER": "DECREE",
    "KANUN HÜKMÜNDE KARARNAME": "DECREE",
    "CUMHURBAŞKANLIĞI KARARNAMELERİ": "DECREE",
    "CUMHURBAŞKANLIĞI KARARNAMESİ": "DECREE",
    "CUMHURBAŞKANI KARARLARI": "DECREE",
    "CUMHURBAŞKANI KARARI": "DECREE",
    "BAKANLAR KURULU KARARLARI": "DECREE",
    "BAKANLAR KURULU KARARI": "DECREE",
    "TÜZÜKLER": "REGULATION",
    "TÜZÜK": "REGULATION",
    "YÖNETMELİKLER": "REGULATION",
    "YÖNETMELİK": "REGULATION",
    "TEBLİĞLER": "ORDER",
    "TEBLİĞ": "ORDER",
}


def _fold(text: str) -> str:
    """Upper-case fold tolerating dotted/diacritic drift (İ/I, Â/A …)."""
    table = str.maketrans("çğıöşüÇĞİÖŞÜâÂ", "cgiosuCGIOSUaA")
    return text.translate(table).upper()


def map_doc_type(native_type: str) -> str:
    """Native type word → controlled doc_type (native always kept in meta;
    cross-country typology is analysis-side, not collection-side)."""
    folded = _fold(native_type)
    for key, value in _TYPE_TO_DOC_TYPE.items():
        if _fold(key) == folded:
            return value
    return "OTHER"


_BKK_NO_RE = re.compile(r"^(\d{4}/\d+)\s")
_KARAR_NO_RE = re.compile(r"Karar Say[ıi]s[ıi]\s*:\s*(\d+)")
_SAYI_LINE_RE = re.compile(r"Say[ıi]\s*:\s*(\d+)")
_CHARSET_RE = re.compile(rb'charset=["\']?([\w-]+)', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _sniff_charset(raw: bytes) -> str:
    match = _CHARSET_RE.search(raw[:4000])
    if match:
        codec = match.group(1).decode("ascii", errors="replace").lower()
        if codec == "windows-1254" or codec == "cp1254":
            return "cp1254"
        return codec
    return "cp1254"  # probed default for gazette htm items


def _plain_lines(raw: bytes) -> list[str]:
    html = raw.decode(_sniff_charset(raw), errors="replace")
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL)
    text = _TAG_RE.sub("\n", body)
    text = text.replace("&nbsp;", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return [line for line in lines if line]


def _header_lines(lines: list[str]) -> dict[str, str]:
    """Read the htm header block: issue number, native type, authority,
    uppercase title (probed shape: Sayı → type → authority: → title …)."""
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        sayi = _SAYI_LINE_RE.search(line)
        if not sayi:
            continue
        out["sayi"] = sayi.group(1)
        rest = lines[i + 1 : i + 9]
        for j, line_j in enumerate(rest):
            if line_j.endswith(":") and len(line_j) > 3:
                out["authority"] = line_j[:-1].strip()
                title_parts = []
                for line_k in rest[j + 1 :]:
                    if line_k.startswith(("MADDE", "Amaç", "BİRİNCİ", "GENEL", "I.")):
                        break
                    if line_k.upper() == line_k and len(line_k) > 3:
                        title_parts.append(line_k)
                    elif title_parts:
                        break
                if title_parts:
                    out["native_title"] = " ".join(title_parts)
                break
            if line_j.upper() == line_j and len(line_j) > 2 and "native_type" not in out:
                out["native_type"] = line_j
        break
    return out


class RgItemHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=item_url(
                str(task.params["date"]),
                int(task.params.get("mukerrer", 0)),
                int(task.params["seq"]),
                str(task.params["ext"]),
            )
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        date = str(params["date"])
        mukerrer = int(params.get("mukerrer", 0))
        seq = int(params["seq"])
        ext = str(params["ext"]).lower()
        title = str(params["title"])
        sayi = str(params["sayi"])
        bolum = str(params.get("bolum", ""))
        tip = str(params.get("tip", ""))

        is_pdf = ext == "pdf"
        if is_pdf != response.content.startswith(_PDF_MAGIC):
            raise ValueError(
                f"rg_item {date} M{mukerrer}-{seq}: body does not match the "
                f"addressed .{ext} form "
                f"(magic={response.content[:8]!r}, {len(response.content)} bytes)"
            )

        authority: str | None = None
        meta: dict[str, str] = {"sayi": sayi, "seq": str(seq)}
        if mukerrer > 0:
            meta["mukerrer"] = str(mukerrer)
        if bolum:
            meta["bolum"] = bolum
        if tip:
            meta["native_type"] = tip
        bkk = _BKK_NO_RE.search(title)
        if bkk:
            meta["kanun_karar_no"] = bkk.group(1)
        karar = _KARAR_NO_RE.search(title)
        if karar:
            meta["kanun_karar_no"] = karar.group(1)

        if not is_pdf:
            header = _header_lines(_plain_lines(response.content))
            if header.get("sayi") and header["sayi"] != sayi:
                raise ValueError(
                    f"rg_item {date} M{mukerrer}-{seq}: file header says issue "
                    f"{header['sayi']}, seed says {sayi}"
                )
            if header.get("authority"):
                authority = header["authority"]
            if header.get("native_title"):
                meta["native_title"] = header["native_title"]
            if header.get("native_type") and not tip:
                meta["native_type"] = header["native_type"]

        ymd = date.replace("-", "")
        mark = f"M{mukerrer}" if mukerrer > 0 else ""
        name = f"{ymd}{mark}-{seq}.{ext}"
        path = f"01_raw/resmigazete/{ymd[:4]}/D{ymd}/{name}"
        meta["files"] = name

        source_url = item_url(date, mukerrer, seq, ext)
        document = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=date,
            issuing_authority=authority,
            doc_type=map_doc_type(tip),
            language="tur",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("TUR", source_url, date)
        return TaskResult(
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )
