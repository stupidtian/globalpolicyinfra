"""Task type ``kor_body``: one version's body text plus full metadata.

One request yields the whole document — the response fragment carries
(probed 2026-08-29, same shape for historical versions, verified on the
2008 original of the probe law)::

    <input type="hidden" id="lsId" name="lsId" value="010719" />   ← law identity
    <h2> 10ㆍ27법난 피해자의 명예회복 등에 관한 법률 <span>( 약칭: 10ㆍ27법난법 )</span> </h2>
    <div class="ct_sub"><span>[시행 2023. 8. 8.] [법률 제19592호, 2023. 8. 8., 타법개정]</span></div>
    <div class="cont_subtit"> … 문화체육관광부 (종무1담당관), 044-203-2314 … </div>
    <div class="pgroup"> … 제1조(목적) … </div>   × N article groups (+ 부칙 addenda)

The parse also spawns the lifecycle pair (user-confirmed 2026-08-30):
``kor_versions`` (needs lsId, only obtainable from this response) and
``kor_reason`` (one amendment-reason document per version).
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any

from adapters.base import FileOut, RequestSpec, Response, TaskResult, TaskSeed, TaskView
from adapters.kor.sources.lawgokr import (
    BASE_URL,
    body_params,
    canonical_body_url,
    parse_pubinfo,
    xhr_headers,
)
from core.document import DocumentRecord, compute_doc_id

__all__ = ["KorBodyHandler", "map_doc_type", "parse_ministry", "version_folder"]

_LS_ID_RE = re.compile(r'<input[^>]*id="lsId"[^>]*value="(\d+)"')
_H2_RE = re.compile(r"<h2>(.*?)</h2>", re.DOTALL)
_ABBR_RE = re.compile(r"\(\s*약칭\s*:\s*(.*?)\s*\)")
_CT_SUB_RE = re.compile(r'<div class="ct_sub">\s*<span>(.*?)</span>', re.DOTALL)
_MINISTRY_BLOCK_RE = re.compile(r'<div class="cont_subtit">\s*<p>(.*?)</p>', re.DOTALL)
_MINISTRY_SPAN_RE = re.compile(r"<span[^>]*>([^<]*)</span>")
_PHONE_RE = re.compile(r"(\d{2,4}-\d[\d\s\u00a0-]*)")


def map_doc_type(promulgation_type: str) -> str:
    """Korean promulgation-prefix tail -> soft doc_type (Korean original
    travels in meta.promulgation_type; plan Q4)."""
    tail = promulgation_type.strip()
    if not tail:
        return "OTHER"
    if tail == "헌법":
        return "CONSTITUTION"
    if tail.endswith("법률"):
        return "STATUTE"
    if tail.endswith("령"):
        return "DECREE"
    if tail.endswith("규칙"):
        return "RULE"
    return "OTHER"


def parse_ministry(text: str) -> dict[str, str]:
    """소관부처 block: ministry, department, phone (any may be absent)."""
    out: dict[str, str] = {}
    block = _MINISTRY_BLOCK_RE.search(text)
    if block is None:
        return out
    raw = block.group(1)
    spans = [html_mod.unescape(s).strip() for s in _MINISTRY_SPAN_RE.findall(raw)]
    spans = [s for s in spans if s]
    if spans:
        out["ministry"] = spans[0]
    if len(spans) > 1:
        out["ministry_dept"] = spans[1]
    phone = _PHONE_RE.search(html_mod.unescape(raw))
    if phone is not None:
        out["ministry_phone"] = phone.group(1).replace("\u00a0", "").strip().rstrip("-")
    return out


def version_folder(seq: str, ef_yd: str) -> str:
    """Raw-folder path below the country root, e.g. ``01_raw/lawgokr/25/253527_20230808``."""
    return f"01_raw/lawgokr/{seq[:2]}/{seq}_{ef_yd}"


def _strip_tags(fragment: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


class KorBodyHandler:
    def build_request(self, task: TaskView) -> RequestSpec:
        seq = str(task.params["seq"])
        ef_yd = str(task.params["ef_yd"])
        return RequestSpec(
            url=f"{BASE_URL}/lsInfoR.do",
            params=body_params(seq, ef_yd),
            headers=xhr_headers(canonical_body_url(seq, ef_yd)),
        )

    def parse(self, response: Response, task: TaskView) -> TaskResult:
        params = dict(task.params)
        seq = str(params["seq"])
        ef_yd = str(params["ef_yd"])
        if response.status_code != 200:
            raise ValueError(f"body of {seq}/{ef_yd} returned HTTP {response.status_code}")
        text = response.content.decode("utf-8", errors="replace")

        if "pgroup" not in text:
            # Probed in production (2026-08-31): very old historical versions
            # (e.g. 1963) return an HTTP-200 apology page with no articles.
            # For timeline-discovered versions that is a data boundary — skip
            # gracefully; for a list anchor it is a shape change — escalate.
            if params.get("from_versions") and ("죄송" in text or "불편" in text):
                return TaskResult(
                    expected_empty=f"historical version {seq}/{ef_yd} is not served "
                    "by the body endpoint (site apology page)"
                )
            raise ValueError(f"body of {seq}/{ef_yd} carries no article groups")

        ls_id = _LS_ID_RE.search(text)
        if ls_id is None:
            raise ValueError(f"body of {seq}/{ef_yd} carries no lsId hidden field")
        h2 = _H2_RE.search(text)
        if h2 is None:
            raise ValueError(f"body of {seq}/{ef_yd} carries no h2 law name")
        h2_text = _strip_tags(h2.group(1))
        abbr_match = _ABBR_RE.search(h2_text)
        abbreviation = abbr_match.group(1).strip() if abbr_match else ""
        title = _ABBR_RE.sub("", h2_text).strip()

        ct_sub = _CT_SUB_RE.search(text)
        if ct_sub is None:
            raise ValueError(f"body of {seq}/{ef_yd} carries no ct_sub publication line")
        pub = parse_pubinfo(html_mod.unescape(_strip_tags(ct_sub.group(1))))
        if not pub.get("effective_date"):
            raise ValueError(f"body of {seq}/{ef_yd} has an unparsable 시행 date")

        publication_date = pub.get("promulgation_date") or ""
        fallback = False
        if not publication_date:
            publication_date = pub["effective_date"]
            fallback = True

        meta: dict[str, str] = {
            "lsi_seq": seq,
            "ef_yd": ef_yd,
            "ls_id": ls_id.group(1),
            "effective_date": pub["effective_date"],
            "effective_raw": pub.get("effective_raw", ""),
            "amendment_type": pub.get("amendment_type", ""),
        }
        if abbreviation:
            meta["law_abbreviation"] = abbreviation
        if pub.get("promulgation_type"):
            meta["promulgation_type"] = pub["promulgation_type"]
        if pub.get("promulgation_no"):
            meta["promulgation_no"] = pub["promulgation_no"]
        if fallback:
            meta["date_fallback"] = "true"
        meta.update(parse_ministry(text))

        record = DocumentRecord(
            title=title,
            source_url=canonical_body_url(seq, ef_yd),
            publication_date=publication_date,
            issuing_authority=meta.get("ministry"),
            doc_type=map_doc_type(pub.get("promulgation_type", "")),
            entity_ref=f"laws:{ls_id.group(1)}",  # the version hangs off its law
            language="kor",
            raw_metadata=meta,
        )
        doc_id = compute_doc_id("KOR", record.source_url, publication_date)
        file_path = f"{version_folder(seq, ef_yd)}/policy_{seq}_{ef_yd}.html"

        # The law entity (user ruling 2026-08-31): one row per law, versions
        # hang off it via ls_id. Only list-discovered anchors maintain it —
        # historical bodies (from_versions) are past states of an entity the
        # anchor already maintains.
        result_rows: dict[str, list[dict[str, Any]]] = {}
        if not params.get("from_versions"):
            law_row: dict[str, Any] = {
                "ls_id": ls_id.group(1),
                "law_name": title,
                "current_seq": seq,
                "current_ef_yd": ef_yd,
            }
            for source, target in (
                (abbreviation, "abbreviation"),
                (meta.get("ministry"), "ministry"),
                (meta.get("ministry_dept"), "ministry_dept"),
                (meta.get("promulgation_type"), "promulgation_type"),
                (record.doc_type, "doc_type"),
            ):
                if source:
                    law_row[target] = source
            result_rows["laws"] = [law_row]

        # The lifecycle pair: this response is the only source of lsId, and
        # bodies spawned *by* the versions task (from_versions) already sit
        # inside a fetched timeline — they spawn only the reason, so each
        # law's timeline is fetched exactly once.
        next_tasks = [TaskSeed(type="kor_reason", params={"seq": seq, "ef_yd": ef_yd})]
        if not params.get("from_versions"):
            next_tasks.append(
                TaskSeed(
                    type="kor_versions",
                    params={"seq": seq, "ef_yd": ef_yd, "ls_id": ls_id.group(1)},
                )
            )
        return TaskResult(
            upsert_rows=result_rows,
            documents=[record],
            files=[FileOut(path=file_path, content=response.content, doc_id=doc_id)],
            next_tasks=next_tasks,
        )
