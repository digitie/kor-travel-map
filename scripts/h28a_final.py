"""T-VN-H28A 최종 증거 manifest — 버전 고정 baseline + 현재 Map 검증 결과.

현재 validator의 severity와 무관하게 2026-07-29 당시 파괴적 규칙을 코드로 재현해 baseline
후보를 고른다. 각 후보에 대해 세 축을 나란히 기록한다.
  1. provider payload의 행정코드
  2. 좌표를 다시 reverse 지오코딩한 결과의 행정코드·이름·거리·후보집합
  3. 현재 validator의 판정

**중요 — 1 vs 2는 독립이 아니다.** kor-travel-concierge의 payload 행정코드는 같은
kor-travel-geo ``POST /v2/reverse``를 같은 좌표로 호출해 만든 캐시본이다
(``backend/ktc/etl/admin_region_service.py`` ``fetch_admin_region``). 따라서 둘의 일치는
좌표 정확성의 증거가 못 되고, 불일치는 위치 오류가 아니라 producer 캐시 낡음을 뜻한다.
``classification`` 필드는 그 한계를 안고 있는 값이므로 좌표 정확성 결론에 쓰지 않는다.
``classify_text_vs_reverse_name_axis``도 provider 원천 텍스트와 좌표 reverse 이름을
비교하므로 **행정코드 캐시와는 독립**이지만 **좌표와는 독립이 아니다**. 토큰이 없다는
사실은 legacy 규칙이 판정 불능임을 증명할 뿐 좌표가 정확함을 증명하지 않는다.

비밀은 출력하지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
from kortravelmap.dagster.validation import validate_feature_bundles_address
from pydantic import SecretStr

from kortravelmap.dto import FeatureBundle
from kortravelmap.geocoding import KorTravelGeoRestClient, kor_travel_geo_reverse_geocoder
from kortravelmap.providers.kor_travel_concierge import (
    KorTravelConciergeQuarantine,
    kor_travel_concierge_items_to_bundles,
)

CONCIERGE = os.environ["CONCIERGE_BASE"]
CKEY = os.environ["CONCIERGE_KEY"]
GEO = os.environ["GEO_BASE"]
GKEY = SecretStr(os.environ["GEO_KEY"])
OUT = os.environ.get("OUT", "/out/h28a-final.json")

BASELINE_RULE_VERSION = "provider_address_mismatch@8073d0d4"
"""PR #885 전 파괴적 규칙의 정확한 git 기준점."""

TEXT_REVERSE_CLASSIFIER_VERSION = "text-vs-reverse-name-v1"


def fetch_items() -> list[dict]:
    items: list[dict] = []
    cursor = None
    while True:
        ep = f"{CONCIERGE}/api/v1/features/changes?limit=500"
        if cursor:
            ep += f"&cursor={urllib.parse.quote(str(cursor))}"
        req = urllib.request.Request(ep, headers={"X-API-Key": CKEY})
        with urllib.request.urlopen(req, timeout=60) as r:
            page = json.loads(r.read().decode())
        batch = page.get("items") or []
        items.extend(batch)
        if not page.get("has_more") or not page.get("next_cursor") or not batch:
            break
        cursor = page["next_cursor"]
    return items


# ── 텍스트 ↔ 좌표 reverse 이름 축 분류 ─────────────────────────────────────
#
# payload 행정코드는 같은 kor-travel-geo /v2/reverse를 같은 좌표로 호출한 캐시본이라
# 좌표 정확성의 증거가 되지 못한다(리포트 §2 정정). 이 축은 그 캐시와 독립인 provider
# 원천 텍스트를 쓰지만, 비교 대상 geo_sigungu_name은 좌표 reverse 결과다.

_ADMIN_TOKEN = re.compile(r"[가-힣]+[시군구]")
_SUFFIXES = ("특별자치시", "특별자치도", "광역시", "특별시", "시", "군", "구")


def compact(value: object) -> str:
    return "".join(str(value or "").split())


def _stem(name: str) -> str:
    c = compact(name)
    for s in _SUFFIXES:
        if len(c) > len(s) and c.endswith(s):
            return c[: -len(s)]
    return c


def classify_text_vs_reverse_name_axis(rows: list[dict]) -> dict[str, list[dict]]:
    """리포트 §2-bis 표(375 / 4 / 1)를 재생성한다."""
    out: dict[str, list[dict]] = {
        "A_행정구역_토큰_없음": [],
        "B_축약_단계_차이": [],
        "C_다른_행정구역_지목": [],
    }
    for r in rows:
        text = compact(r.get("provider_address"))
        geo = r.get("geo_sigungu_name") or ""
        if not _ADMIN_TOKEN.search(text):
            out["A_행정구역_토큰_없음"].append(r)
        elif geo and _stem(geo) and _stem(geo) in text:
            out["B_축약_단계_차이"].append(r)
        else:
            out["C_다른_행정구역_지목"].append(r)
    return out


def print_text_reverse_name_report(rows: list[dict]) -> None:
    groups = classify_text_vs_reverse_name_axis(rows)
    print("\n=== provider 텍스트 ↔ 좌표 reverse 이름 분류 ===")
    for name, items in groups.items():
        print(f"  {len(items):4d}  {name}")
        for r in items[:3]:
            print(
                f"          {r.get('name')} | geo={r.get('geo_sigungu_name')} "
                f"| {str(r.get('provider_address'))[:40]}"
            )
    print(
        "\n  A는 legacy 규칙이 판정 불능임을 텍스트만으로 확정한다. "
        "B/C는 좌표 reverse 이름을 사용하며, C의 좌표 정확성 판단에는 제3의 독립 수단이 "
        "필요하다."
    )


def _provider_address(bundle: FeatureBundle) -> str | None:
    record = bundle.source_record
    address = bundle.feature.address
    raw = record.raw_address or address.road or address.legal
    if raw is None:
        return None
    normalized = " ".join(str(raw).split())
    return normalized or None


def is_baseline_provider_address_mismatch(bundle: FeatureBundle) -> bool:
    """``BASELINE_RULE_VERSION``의 error 선별식을 현재 validator와 독립적으로 재현한다."""
    feature = bundle.feature
    address = feature.address
    provider_address = _provider_address(bundle)
    return bool(
        provider_address
        and feature.coord is not None
        and address.bjd_code is not None
        and address.sigungu_name
        and compact(address.sigungu_name) not in compact(provider_address)
    )


async def main() -> None:
    items = fetch_items()
    upserts = [i for i in items if i.get("operation") == "upsert"]
    print(f"export items: {len(items)} (upsert {len(upserts)})")

    async with httpx.AsyncClient(base_url=GEO, timeout=30.0) as http:
        client = KorTravelGeoRestClient(http, api_key=GKEY)
        geocoder = kor_travel_geo_reverse_geocoder(client)
        quarantine: list[KorTravelConciergeQuarantine] = []
        converted: list[tuple[dict, FeatureBundle]] = []
        for item in upserts:
            item_bundles = await kor_travel_concierge_items_to_bundles(
                [item],
                fetched_at=datetime.now(UTC),
                reverse_geocoder=geocoder,
                quarantine=quarantine,
            )
            if item_bundles:
                converted.append((item, item_bundles[0]))
        bundles = [bundle for _, bundle in converted]
        print(f"bundles: {len(bundles)}")
        print(f"quarantine: {len(quarantine)}")
        assert len(upserts) == len(bundles) + len(quarantine), (
            "upsert 보존 불변식이 깨졌다: upserts != bundles + quarantine"
        )

        summary = validate_feature_bundles_address(bundles)
        issue_by_key: dict[str, list] = {}
        for iss in summary.issues:
            issue_by_key.setdefault(iss.source_record_key, []).append(iss)

        # 현재 validator 결과와 무관하게 버전 고정 baseline 후보를 선별한다.
        rows = []
        baseline_pairs = [
            (item, bundle)
            for item, bundle in converted
            if is_baseline_provider_address_mismatch(bundle)
        ]
        current_issues_by_key = {
            key: tuple(issues) for key, issues in issue_by_key.items()
        }
        print(
            f"{BASELINE_RULE_VERSION} 후보 {len(baseline_pairs)}건 독립 reverse 재확인 중..."
        )
        for item, bundle in baseline_pairs:
            key = bundle.source_record.source_record_key
            place = item.get("place") or {}
            paddr = place.get("address") or {}
            lon, lat = place.get("longitude"), place.get("latitude")

            geo_sig = geo_name = geo_bjd = None
            geo_dist = None
            geo_set: list[str] = []
            if lon is not None and lat is not None:
                raw = await client.reverse(float(lon), float(lat))
                cands = list(raw.candidates)
                if cands:
                    top = cands[0]
                    reg = top.region
                    geo_sig = reg.sig_cd if reg else None
                    geo_name = reg.sigungu if reg else None
                    geo_bjd = (top.address.legal_dong_code if top.address else None) or (
                        reg.bjd_cd if reg else None
                    )
                    geo_dist = top.distance_m
                    geo_set = sorted(
                        {c.region.sig_cd for c in cands if c.region and c.region.sig_cd}
                    )

            psig = paddr.get("sigungu_code")
            provider_address = _provider_address(bundle)
            row = {
                "name": place.get("name"),
                "lon": lon,
                "lat": lat,
                "provider_address": provider_address,
                "provider_road_address": paddr.get("road_address"),
                "provider_official_address": paddr.get("official_address"),
                "payload_sigungu_code": psig,
                "payload_legal_dong_code": paddr.get("legal_dong_code"),
                "feature_sigungu_code": bundle.feature.address.sigungu_code,
                "feature_sigungu_name": bundle.feature.address.sigungu_name,
                "geo_sigungu_code": geo_sig,
                "geo_sigungu_name": geo_name,
                "geo_bjd_code": geo_bjd,
                "geo_distance_m": geo_dist,
                "geo_sigungu_code_set": geo_set,
                "current_issues": [
                    {"code": issue.code, "severity": issue.severity}
                    for issue in current_issues_by_key.get(key, ())
                ],
            }

            # ── 분류 ────────────────────────────────────────────────────────
            if psig and geo_sig:
                if psig == geo_sig:
                    row["classification"] = "code_cache_same"
                elif psig in geo_set:
                    row["classification"] = "code_cache_boundary"
                else:
                    row["classification"] = "code_cache_diff"
            elif not psig:
                # payload에 코드가 없다 → 대조 축 자체가 없음.
                pa = "".join(str(provider_address or "").split())
                row["classification"] = (
                    "unresolved_no_payload_code_short_address"
                    if len(pa) <= 8
                    else "unresolved_no_payload_code"
                )
            else:
                row["classification"] = "unresolved_no_geo_code"
            rows.append(row)

    cls = Counter(r["classification"] for r in rows)
    print(f"\n=== {BASELINE_RULE_VERSION} 후보 분류 ===")
    for k, v in cls.most_common():
        print(f"  {k}: {v}")

    print("\n=== payload cache와 현재 reverse 코드가 다른 후보(있다면) ===")
    code_diffs = [r for r in rows if r["classification"] == "code_cache_diff"]
    for r in code_diffs[:15]:
        print(
            f"  {r['name']} | payload={r['payload_sigungu_code']} geo={r['geo_sigungu_code']}"
            f"({r['geo_sigungu_name']}) dist={r['geo_distance_m']} set={r['geo_sigungu_code_set']}"
            f" | {str(r['provider_address'])[:40]}"
        )
    if not code_diffs:
        print("  없음 — staleness 축에서 다른 코드가 관측되지 않았다.")

    print("\n=== payload 코드 없는 항목 표본 ===")
    for r in [r for r in rows if r["classification"].startswith("unresolved")][:8]:
        print(
            f"  {r['name']} | addr={str(r['provider_address'])[:34]} "
            f"geo={r['geo_sigungu_code']}({r['geo_sigungu_name']}) "
            f"road={str(r['provider_road_address'])[:30]}"
        )

    out = {
        "baseline": {
            "baseline_rule_version": BASELINE_RULE_VERSION,
            "export_items": len(items),
            "upserts": len(upserts),
            "bundles": len(bundles),
            "quarantine": len(quarantine),
            "baseline_candidates": len(rows),
        },
        "current_validation": {
            "issues_total": len(summary.issues),
            "by_code": dict(Counter(i.code for i in summary.issues)),
            "by_severity": dict(Counter(i.severity for i in summary.issues)),
            "evidence_grade_counts": summary.evidence_grade_counts,
            "name_state_counts": summary.name_state_counts,
        },
        "quarantine": [
            {
                "item_key": entry.item_key,
                "reason_code": entry.reason_code,
                "message": entry.message,
            }
            for entry in quarantine
        ],
        "text_reverse_classifier_version": TEXT_REVERSE_CLASSIFIER_VERSION,
        "baseline_candidate_classification": dict(cls),
        "rows": rows,
    }
    await asyncio.to_thread(
        Path(OUT).write_text,
        json.dumps(out, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print_text_reverse_name_report(rows)
    print(f"\nmanifest 저장: {OUT} ({len(rows)} rows)")


if __name__ == "__main__":
    asyncio.run(main())
