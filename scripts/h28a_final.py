"""T-VN-H28A 최종 증거 manifest — Map 실제 파이프라인 + 후보별 독립 reverse 대조.

각 error 후보에 대해 세 축을 나란히 기록한다.
  1. provider payload의 행정코드
  2. 좌표를 다시 reverse 지오코딩한 결과의 행정코드·이름·거리·후보집합
  3. 현재 규칙(이름 substring)의 판정

**중요 — 1 vs 2는 독립이 아니다.** kor-travel-concierge의 payload 행정코드는 같은
kor-travel-geo ``POST /v2/reverse``를 같은 좌표로 호출해 만든 캐시본이다
(``backend/ktc/etl/admin_region_service.py`` ``fetch_admin_region``). 따라서 둘의 일치는
좌표 정확성의 증거가 못 되고, 불일치는 위치 오류가 아니라 producer 캐시 낡음을 뜻한다.
``classification`` 필드는 그 한계를 안고 있는 값이므로 결론 근거로 쓰지 않는다.

결론 근거는 ``classify_by_text_axis``다 — 유일한 독립 축인 provider **원천 텍스트**만
쓰며 좌표 증거를 쓰지 않는다(리포트 §2-bis, 375/4/1).

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


# ── 독립 축 분류 (T-VN-H28B 정정 근거) ──────────────────────────────────────
#
# payload 행정코드는 같은 kor-travel-geo /v2/reverse를 같은 좌표로 호출한 캐시본이라
# 좌표 정확성의 증거가 되지 못한다(리포트 §2 정정). 유일한 독립 축인 provider **원천
# 텍스트**만으로 분류한다 — 좌표 증거를 쓰지 않는다.

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


def classify_by_text_axis(rows: list[dict]) -> dict[str, list[dict]]:
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


def print_text_axis_report(rows: list[dict]) -> None:
    groups = classify_by_text_axis(rows)
    print("\n=== 독립 축(provider 텍스트) 분류 — 좌표 증거 불사용 ===")
    for name, items in groups.items():
        print(f"  {len(items):4d}  {name}")
        for r in items[:3]:
            print(
                f"          {r.get('name')} | geo={r.get('geo_sigungu_name')} "
                f"| {str(r.get('provider_address'))[:40]}"
            )
    print(
        "\n  A/B는 좌표를 보지 않고도 규칙 산물임이 확정된다. "
        "C만 제3의 독립 수단(정지오코딩)으로 개별 확인이 필요하다."
    )


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
    print_text_axis_report(rows)
    print(f"\nmanifest 저장: {OUT} ({len(rows)} rows)")


if __name__ == "__main__":
    asyncio.run(main())

