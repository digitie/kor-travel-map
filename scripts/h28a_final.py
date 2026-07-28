"""T-VN-H28A 최종 증거 manifest — Map 실제 파이프라인 + 후보별 독립 reverse 대조.

각 error 후보에 대해 세 축을 나란히 기록한다.
  1. provider payload의 authoritative 행정코드 (producer T-189 주입)
  2. 좌표를 다시 reverse 지오코딩한 결과의 행정코드·이름·거리·후보집합
  3. 현재 규칙(이름 substring)의 판정

이 세 축으로 true-positive(좌표가 실제로 다른 행정구역)와 false-positive(코드는 일치하는데
이름 표기만 달라 걸린 것)를 분리한다. 비밀은 출력하지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime

import httpx
from kortravelmap.geocoding import KorTravelGeoRestClient, kor_travel_geo_reverse_geocoder
from kortravelmap.providers.kor_travel_concierge import (
    kor_travel_concierge_items_to_bundles,
)

from kortravelmap.dagster.validation import validate_feature_bundles_address

CONCIERGE = os.environ["CONCIERGE_BASE"]
CKEY = os.environ["CONCIERGE_KEY"]
GEO = os.environ["GEO_BASE"]
GKEY = os.environ["GEO_KEY"]
OUT = os.environ.get("OUT", "/out/h28a-final.json")


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


async def main() -> None:
    items = fetch_items()
    upserts = [i for i in items if i.get("operation") == "upsert"]
    print(f"export items: {len(items)} (upsert {len(upserts)})")

    async with httpx.AsyncClient(base_url=GEO, timeout=30.0) as http:
        client = KorTravelGeoRestClient(http, api_key=GKEY)
        bundles = await kor_travel_concierge_items_to_bundles(
            items,
            fetched_at=datetime.now(UTC),
            reverse_geocoder=kor_travel_geo_reverse_geocoder(client),
        )
        print(f"bundles: {len(bundles)}")
        assert len(bundles) == len(upserts), "순서 기반 join 전제가 깨졌다"

        summary = validate_feature_bundles_address(bundles)
        issue_by_key: dict[str, list] = {}
        for iss in summary.issues:
            issue_by_key.setdefault(iss.source_record_key, []).append(iss)

        # error 후보만 독립 reverse로 다시 확인한다(원 응답의 코드·거리·후보집합 확보).
        rows = []
        err_keys = {
            iss.source_record_key
            for iss in summary.issues
            if iss.severity == "error"
        }
        print(f"error 후보 {len(err_keys)}건 독립 reverse 재확인 중...")
        for idx, (item, bundle) in enumerate(zip(upserts, bundles, strict=True)):
            key = bundle.source_record.source_record_key
            if key not in err_keys:
                continue
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
            iss = issue_by_key[key][0]
            row = {
                "name": place.get("name"),
                "lon": lon,
                "lat": lat,
                "provider_address": iss.provider_address,
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
            }

            # ── 분류 ────────────────────────────────────────────────────────
            if psig and geo_sig:
                if psig == geo_sig:
                    row["classification"] = "false_positive_code_same"
                elif psig in geo_set:
                    row["classification"] = "false_positive_boundary"
                else:
                    row["classification"] = "true_positive_code_diff"
            elif not psig:
                # payload에 코드가 없다 → 대조 축 자체가 없음.
                pa = "".join(str(iss.provider_address or "").split())
                row["classification"] = (
                    "unresolved_no_payload_code_short_address"
                    if len(pa) <= 8
                    else "unresolved_no_payload_code"
                )
            else:
                row["classification"] = "unresolved_no_geo_code"
            rows.append(row)

    cls = Counter(r["classification"] for r in rows)
    print("\n=== error 380건 분류 ===")
    for k, v in cls.most_common():
        print(f"  {k}: {v}")

    print("\n=== true positive 후보(있다면) ===")
    tps = [r for r in rows if r["classification"] == "true_positive_code_diff"]
    for r in tps[:15]:
        print(
            f"  {r['name']} | payload={r['payload_sigungu_code']} geo={r['geo_sigungu_code']}"
            f"({r['geo_sigungu_name']}) dist={r['geo_distance_m']} set={r['geo_sigungu_code_set']}"
            f" | {str(r['provider_address'])[:40]}"
        )
    if not tps:
        print("  없음 — 코드 대조로는 단 한 건도 실제 불일치가 아니다.")

    print("\n=== payload 코드 없는 항목 표본 ===")
    for r in [r for r in rows if r["classification"].startswith("unresolved")][:8]:
        print(
            f"  {r['name']} | addr={str(r['provider_address'])[:34]} "
            f"geo={r['geo_sigungu_code']}({r['geo_sigungu_name']}) "
            f"road={str(r['provider_road_address'])[:30]}"
        )

    out = {
        "baseline": {
            "export_items": len(items),
            "upserts": len(upserts),
            "bundles": len(bundles),
            "issues_total": len(summary.issues),
            "by_code": dict(Counter(i.code for i in summary.issues)),
            "by_severity": dict(Counter(i.severity for i in summary.issues)),
        },
        "error_classification": dict(cls),
        "rows": rows,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nmanifest 저장: {OUT} ({len(rows)} rows)")


if __name__ == "__main__":
    asyncio.run(main())
