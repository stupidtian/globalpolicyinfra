"""Task type ``mev_metin``: one entity's consolidated text, one document.

GET the detail page's text iframe — one response carrying the header
metadata block plus the full kodifiye text in HTML (the Constitution's
answer is 668,119 bytes; a yönetmelik's 63,809; probed 2026-09-27). The
bytes are stored verbatim as ``metin.html``.

The header block comes in five probed dialects (label spellings differ
per instrument family; all matched with generous whitespace and colon
forms):

- statutes (tur 1/5): ``Kanun Numarası : …`` / ``Kabul Tarihi : …`` /
  ``Yayımlandığı Resmî Gazete : Tarih : … Sayı : … (Mükerrer)`` /
  ``Yayımlandığı Düstur : Tertip : … Cilt : … Sayfa : …`` — repealed
  statutes (tur 5) open with a "Bu Kanun … yürürlükten kaldırılmıştır"
  sentence naming the repealing law (kept verbatim in meta).
- tüzük/yönetmelik (tur 2/3/7/8/10/21): BKK decision date+number,
  ``Dayandığı Kanunun Tarihi : … No : …``, ``… Gazetenin Tarihi : …
  No : …``, ``Düsturun Tertibi : … Cildi : …`` (no Sayfa; "Cildi");
  the CB'lık yönetmelik spells the decision number ``Sayısı:``.
- KHK (tur 4): ``Kanun Hükmünde Kararnamenin Tarihi : … No : …`` +
  ``Yetki Kanununun Tarihi : …`` (first authorization law kept) +
  ``… Gazete Tarihi : … No : … (3. Mükerrer)`` — the mükerrer note can
  carry an ordinal.
- presidential decrees (tur 19): ``Cumhurbaşkanlığı Kararnamesinin
  Sayısı : …`` / ``Yayımlandığı Resmî Gazetenin Tarihi - Sayısı :
  8/1/2025 - 32776`` (dash-separated date and issue).
- communiqués (tur 9): **no header block at all** — the number rides in
  the title (``TEBLİĞ NO: 2026/29``); dates come from the catalogue seed
  only. tur 9 is therefore exempt from the header-presence check.

A header gazette date contradicting the seed's catalogue date fails
loudly, as does a body carrying no recognizable header outside tur 9
(the known iframe failure mode is an empty or session-error page).
Entities whose text exists only as a file (``fileType=2``, e.g. all CB
Kararı records) are seeded to :mod:`pdf` instead — never here.

doc_id's date part comes from the seed's catalogue ``rg_tarihi`` (stable
identity) with the header as cross-check; amendment footnotes stay in the
stored bytes — revision graphs are analysis-side work.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.tur.sources.mevzuat import API_BASE
from core.document import DocumentRecord, compute_doc_id

__all__ = ["MevMetinHandler", "map_doc_type"]

_IFRAME_URL = f"{API_BASE}/anasayfa/MevzuatFihristDetayIframe"

_TUR_TO_DOC_TYPE: dict[int, str] = {
    0: "STATUTE",  # Osmanlı kanunu — still a statute-family text
    1: "STATUTE",  # Kanun
    2: "REGULATION",  # Tüzük
    3: "REGULATION",  # Yönetmelik (union)
    4: "DECREE",  # KHK
    5: "STATUTE",  # Mülga kanun — a repealed statute is still a statute
    6: "REGULATION",  # Cecici tüzük
    7: "REGULATION",  # Kurum/kuruluş yönetmeliği
    8: "REGULATION",  # Üniversite yönetmeliği
    9: "ORDER",  # Tebliğ
    10: "REGULATION",  # BKK yönetmeliği
    16: "OTHER",  # AYM içtihatı
    17: "OTHER",  # İç tüzük
    18: "DECREE",  # BKK
    19: "DECREE",  # CB kararnamesi
    20: "DECREE",  # CB kararı
    21: "REGULATION",  # CB'lık yönetmeliği
}

#: types whose texts carry no header block at all (probed: tebliğ 2026/29)
HEADERLESS_TURS: frozenset[int] = frozenset({9})


def map_doc_type(tur: int) -> str:
    """Type code → controlled doc_type (native code always kept in meta)."""
    return _TUR_TO_DOC_TYPE.get(tur, "OTHER")


def _collapsed_text(raw: bytes) -> str:
    html = raw.decode("utf-8", errors="replace")
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", unescape(text))


_DATE = r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})"
#: gazette line prefix up to the date — tolerates ": Tarih :", "nin Tarihi :",
#: " Tarihi: ", "nin Tarihi - Sayısı :" (tur 19) inside ~40 non-digits.
_RG_DATE_RE = re.compile(
    rf"Yay[ıi]mland[ıi][ğg][ıi]\s*Resm[îi]\s*Gazete(?:nen)?[^\d]{{0,40}}{_DATE}"
)
#: adoption line — "Kabul Tarihi", "… Kararının/Kararnamenin Tarihi"
_KABUL_RE = re.compile(rf"(?:Kabul|Karar[ıi]n[ıi]n|Kararnamenin)\s*Tarih[ıi]\s*:\s*{_DATE}")
#: identity number on the adoption line ("No : 2013/5150" / "Sayısı:11674")
_ADOPTION_NO_RE = re.compile(r"(?:No|Say[ıi]s[ıi])\s*:\s*([\d/]+)")
_KANUN_NO_RE = re.compile(r"Kanun\s*Numaras[ıi]\s*:\s*(\d+)")
_KARARNAME_NO_RE = re.compile(
    r"Cumhurbaşkanl[ıi][ğg][ıi]\s*Kararnamesinin\s*Say[ıi]s[ıi]\s*:\s*(\d+)"
)
#: issue number in the window right after the gazette date ("Sayı: 17863",
#: "No: 30473", "- 32776" for tur 19) and the mükerrer note "(3. Mükerrer)".
_RG_SAYI_RE = re.compile(r"(?:Say[ıi]s?[ıi]?|No)\s*:\s*(\d{2,6})|-\s*(\d{3,6})")
_MUKERRER_NOTE_RE = re.compile(r"\((?:\d+\.\s*)?Mükerrer\)")
_DUSTUR_RE = re.compile(
    r"Yay[ıi]mland[ıi][ğg][ıi]\s*D[üu]stur(?:un)?[^\d]{0,20}(?:Tertibi|Tertip)[^\d]{0,8}(\d+)"
    r"\s*(?:Cildi|Cilt)\s*:\s*(\d+)(?:\s*Sayfa\s*:\s*(\d+))?"
)
#: underlying/authorization statute — tüzük "Dayandığı", KHK "Yetki
#: Kanununun" (the triple-suffix form occurs, probed tur 4)
_DAYANDIGI_RE = re.compile(
    rf"(?:Dayand[ıi][ğg][ıi]|Yetki)\s*Kanun(?:unun|un)?\s*Tarih[ıi]\s*:\s*{_DATE}\s*No\s*:\s*(\d+)"
)
#: repealed-statute preface ("Bu Kanun … yürürlükten kaldırılmıştır.")
_KALDIRILDI_RE = re.compile(r"(Bu\s+\S[^.]{0,220}?yürürlükten\s*kaldırılmıştır)")


def _match_date(groups: tuple[str, ...]) -> str:
    d, m, y = groups
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


class MevMetinHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        return RequestSpec(
            url=_IFRAME_URL,
            params={
                "MevzuatTur": str(task.params["tur"]),
                "MevzuatNo": str(task.params["no"]),
                "MevzuatTertip": str(task.params["tertip"]),
            },
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = task.params
        tur = int(params["tur"])
        no = str(params["no"])
        tertip = int(params["tertip"])
        adi = str(params["adi"])
        seed_rg = str(params["rg_tarihi"]) if params.get("rg_tarihi") else None

        text = _collapsed_text(response.content)
        found: dict[str, str] = {}

        kanun_no = _KANUN_NO_RE.search(text)
        if kanun_no:
            found["kanun_no"] = kanun_no.group(1)
        kararname_no = _KARARNAME_NO_RE.search(text)
        if kararname_no:
            found["kararname_no"] = kararname_no.group(1)

        kabul = _KABUL_RE.search(text)
        if kabul:
            found["kabul_tarihi"] = _match_date(kabul.groups())
            adoption_no = _ADOPTION_NO_RE.search(text[kabul.end() : kabul.end() + 30])
            if adoption_no:
                found["karar_no"] = adoption_no.group(1)

        rg = _RG_DATE_RE.search(text)
        if rg:
            found["rg_tarihi"] = _match_date(rg.groups())
            window = text[rg.end() : rg.end() + 40]
            sayi = _RG_SAYI_RE.search(window)
            if sayi:
                found["rg_sayisi"] = sayi.group(1) or sayi.group(2)
            if _MUKERRER_NOTE_RE.search(window):
                found["mukerrer"] = "EVET"

        dustur = _DUSTUR_RE.search(text)
        if dustur:
            found["dustur_tertip"] = dustur.group(1)
            found["dustur_cilt"] = dustur.group(2)
            if dustur.group(3):
                found["dustur_sayfa"] = dustur.group(3)

        dayandigi = _DAYANDIGI_RE.search(text)
        if dayandigi:
            found["dayandigi_kanun_tarihi"] = _match_date(dayandigi.groups()[:3])
            found["dayandigi_kanun_no"] = dayandigi.group(4)

        kaldirildi = _KALDIRILDI_RE.search(text[:500])
        if kaldirildi:
            found["yururlukten_kaldirildi"] = re.sub(r"\s+", " ", kaldirildi.group(1))

        has_header = any(
            key in found
            for key in ("kanun_no", "kararname_no", "kabul_tarihi", "rg_tarihi")
        )
        if not has_header and tur not in HEADERLESS_TURS:
            raise ValueError(
                f"mev_metin tur={tur} no={no}: body carries no recognizable "
                f"header block ({len(response.content)} bytes)"
            )
        for key, label in (("kanun_no", "statute"), ("kararname_no", "decree")):
            if found.get(key) and found[key] != no:
                raise ValueError(
                    f"mev_metin no={no}: header numbers {label} {found[key]}"
                )
        if seed_rg and found.get("rg_tarihi") and found["rg_tarihi"] != seed_rg:
            raise ValueError(
                f"mev_metin tur={tur} no={no}: header gazette date "
                f"{found['rg_tarihi']} contradicts catalogue {seed_rg}"
            )

        meta: dict[str, str] = {"mevzuat_tur": str(tur), "mevzuat_tertip": str(tertip)}
        for key in (
            "kanun_no",
            "kararname_no",
            "karar_no",
            "kabul_tarihi",
            "rg_sayisi",
            "dayandigi_kanun_tarihi",
            "dayandigi_kanun_no",
            "dustur_tertip",
            "dustur_cilt",
            "dustur_sayfa",
            "mukerrer",
            "yururlukten_kaldirildi",
        ):
            if found.get(key):
                meta[key] = found[key]
        meta["pdf_url"] = f"{API_BASE}/MevzuatMetin/{tur}.{tertip}.{no}.pdf"
        meta["doc_url"] = f"{API_BASE}/MevzuatMetin/{tur}.{tertip}.{no}.doc"
        meta["files"] = "metin.html"

        entity_update: dict[str, Any] = {
            "mevzuat_tur": tur,
            "mevzuat_no": no,
            "mevzuat_tertip": tertip,
            "mevzuat_adi": adi,
        }
        for key in ("kabul_tarihi", "rg_tarihi", "rg_sayisi"):
            if found.get(key):
                entity_update[key] = found[key]

        path = f"01_raw/mevzuat/{tur}/{no}/metin.html"
        source_url = f"{API_BASE}/mevzuat?MevzuatNo={no}&MevzuatTur={tur}&MevzuatTertip={tertip}"
        pub_date = seed_rg or found.get("rg_tarihi")
        document = DocumentRecord(
            title=adi,
            source_url=source_url,
            publication_date=pub_date,
            doc_type=map_doc_type(tur),
            language="tur",
            entity_ref=f"mevzuat:{tur}:{no}:{tertip}",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("TUR", source_url, pub_date)
        return TaskResult(
            upsert_rows={"mevzuat": [entity_update]},
            documents=[document],
            files=[FileOut(path=path, content=response.content, doc_id=doc_id)],
        )
