"""Task type ``kor_reason``: one version's official amendment reason.

``lsRvsDocInfoR.do`` returns the 제정·개정이유 document — the 법제처-provided
reasoning behind this version's enactment/amendment plus the amendment
text (제정·개정문). One document per version, high policy-motivation value
(user-confirmed inclusion 2026-08-30). Response shape (probed 2026-08-30)::

    <input type="hidden" id="lsNm" value="10ㆍ27법난 피해자의 명예회복 등에 관한 법률" />
    <input type="hidden" id="lsId" value="010719" />
    <input type="hidden" id="ancYd" value="20230808" />   ← promulgation date, YYYYMMDD
    <input type="hidden" id="ancNo" value="19592" />      ← promulgation number
    … 【제정·개정이유】 … 【제정·개정문】 …

A version without a reason document (possible for some old enactments —
not observed in probing, handled defensively) parses as expected_empty.
The file lands beside its version's body: one policy version, one folder.
"""

from __future__ import annotations

import re

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskView
from adapters.kor.sources.lawgokr import (
    BASE_URL,
    body_params,
    canonical_body_url,
    canonical_reason_url,
    parse_pubinfo,
    xhr_headers,
)
from adapters.kor.sources.lawgokr.body import version_folder
from core.document import DocumentRecord, compute_doc_id

__all__ = ["KorReasonHandler"]

_HIDDEN_RE = re.compile(r'<input[^>]*id="(lsNm|lsId|ancYd|ancNo)"[^>]*value="([^"]*)"')
_REASON_MARKS = ("제정·개정이유", "제정·개정문", "제정ㆍ개정")
_PUB_LINE_RE = re.compile(r"\[시행[^\]]*\]\s*\[([^\]]+)\]")


def _iso_from_yyyymmdd(raw: str) -> str | None:
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return None


class KorReasonHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        seq = str(task.params["seq"])
        ef_yd = str(task.params["ef_yd"])
        return RequestSpec(
            url=f"{BASE_URL}/lsRvsDocInfoR.do",
            params=body_params(seq, ef_yd),
            headers=xhr_headers(canonical_body_url(seq, ef_yd)),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        seq = str(params["seq"])
        ef_yd = str(params["ef_yd"])
        if response.status_code != 200:
            raise ValueError(f"amendment reason of {seq}/{ef_yd} returned HTTP {response.status_code}")
        text = response.content.decode("utf-8", errors="replace")

        if not any(mark in text for mark in _REASON_MARKS):
            return TaskResult(
                expected_empty=f"version {seq}/{ef_yd} has no 제정·개정이유 document"
            )

        hidden = dict(_HIDDEN_RE.findall(text))
        publication_date = _iso_from_yyyymmdd(hidden.get("ancYd", ""))
        meta: dict[str, str] = {
            "lsi_seq": seq,
            "ef_yd": ef_yd,
            "doc_kind": "reason",
            "related_source_url": canonical_body_url(seq, ef_yd),
        }
        law_name = hidden.get("lsNm", "").strip()
        if hidden.get("lsId"):
            meta["ls_id"] = hidden["lsId"]
        if hidden.get("ancNo"):
            meta["promulgation_no"] = hidden["ancNo"]

        if publication_date is None:
            # Fallback: parse the [시행 …] [법률 제N호, date, type] line.
            pub_line = _PUB_LINE_RE.search(text)
            pub = parse_pubinfo(pub_line.group(1)) if pub_line else {}
            publication_date = pub.get("promulgation_date") or pub.get("effective_date")
            meta.update(
                {k: v for k, v in pub.items() if k in ("amendment_type", "promulgation_type")}
            )
        if not law_name:
            law_name = f"{seq}/{ef_yd}"
        title = f"{law_name} — 제정·개정이유"

        source_url = canonical_reason_url(seq, ef_yd)
        record = DocumentRecord(
            title=title,
            source_url=source_url,
            publication_date=publication_date,
            doc_type="OTHER",
            entity_ref=f"laws:{hidden['lsId']}" if hidden.get("lsId") else None,
            language="kor",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("KOR", source_url, publication_date)
        file_path = f"{version_folder(seq, ef_yd)}/reason_{seq}_{ef_yd}.html"
        return TaskResult(
            documents=[record],
            files=[FileOut(path=file_path, content=response.content, doc_id=doc_id)],
        )
