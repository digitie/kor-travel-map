"""T-VN-H28 회복 검증 — 새 규칙으로 실제 후보가 살아나는가.

before(main) / after(branch) 두 코드로 **같은 live export**를 돌려 drop 수를 비교한다.
비밀은 출력하지 않는다.
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
    quarantine: list = []

    async with httpx.AsyncClient(base_url=GEO, timeout=30.0) as http:
        client = KorTravelGeoRestClient(http, api_key=GKEY)
        bundles = await kor_travel_concierge_items_to_bundles(
            items,
            fetched_at=datetime.now(UTC),
            reverse_geocoder=kor_travel_geo_reverse_geocoder(client),
            quarantine=quarantine,
        )

    print(f"export items : {len(items)}")
    print(f"bundles      : {len(bundles)}  (건별 격리 {len(quarantine)}건)")

    summary = validate_feature_bundles_address(bundles)
    by_code = Counter(i.code for i in summary.issues)
    print(f"issues       : {summary.issue_count}  {dict(by_code)}")
    print(f"error(전체)  : {summary.error_count}")
    print(f"blocking     : {len(summary.blocking_issues)}  ← 실제 drop 대상")
    print(f"evidence     : {summary.evidence_grade_counts}")

    dropped = {i.feature_id for i in summary.blocking_issues}
    print(f"\n적재되는 후보: {len(bundles) - len(dropped)} / {len(bundles)}")

    # 교차검증이 실제로 이뤄진 비율
    dual = summary.evidence_grade_counts.get("dual", 0)
    print(f"코드 교차검증 성립: {dual}/{len(bundles)} ({dual * 100 // max(len(bundles), 1)}%)")

    conflicts = [i for i in summary.issues if i.code.startswith("admin_code_conflict")]
    print(f"행정코드 불일치(warning): {len(conflicts)}")
    for c in conflicts[:10]:
        print(f"  {c.code} | {c.message}")


if __name__ == "__main__":
    asyncio.run(main())
