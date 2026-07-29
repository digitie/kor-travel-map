"""T-VN-H36 — 자동 링크 금지의 실제 영향을 커밋된 CSV 전수로 잰다. **읽기 전용.**

AC: "정당한 링크를 과도하게 잃지 않는다 — 현재 링크 222건 중 이 변경으로 재현되지 않는
건이 몇 건인지 수치로 제시한다."

**반증 가능성**: 이 측정은 실패했다면 다른 결과가 나온다.
- 변경이 아무것도 안 막았다면 `blocked`가 0으로 나온다.
- 변경이 링크를 통째로 껐다면 `csv_specified`(CSV가 feature_id를 적은 행)가 0이 된다.
  그 값은 리졸버가 아니라 CSV 파일에서 오므로, 두 숫자가 같이 움직이지 않는다.
- 후보 분포(0건/1건/2건 이상)는 리졸버가 살아 있어야만 나온다 — 전부 0이면 조회가 죽은 것이다.

리졸버 SQL을 그대로 재생한다(`curation_repo._RESOLVE_FEATURES_BATCH_SQL`의 이름 브랜치).
prod 스키마와 배포 코드가 저장소 HEAD와 다를 수 있으므로 **DB만 보고** API는 부르지 않는다.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
from collections import Counter
from pathlib import Path

import asyncpg

CSV_DIR = Path(os.environ.get("CSV_DIR", "resources/curations"))
DSN = os.environ["DSN"].replace("+asyncpg", "")
OUT = os.environ.get("OUT", "/out/h36-link-impact.json")

# 리졸버의 이름 브랜치. address_hint가 비면 주소 필터는 통째로 참이 된다.
_NAME_BRANCH_SQL = """
select f.feature_id, f.name,
       coalesce(f.address->>'sido_name', '') as sido_name,
       coalesce(f.address->>'sido_code', '') as sido_code
  from feature.features f
 where lower(f.name) = lower($1)
   and f.deleted_at is null
   and f.status not in ('deleted', 'hidden')
   and ($2::text is null or f.address::text ilike '%' || $2 || '%')
 order by f.feature_id
 limit 15
"""


def rows() -> list[dict]:
    out: list[dict] = []
    for path in sorted(CSV_DIR.glob("*.csv")):
        if path.name == "template.csv":
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    meta = json.loads(r.get("metadata_json") or "{}")
                except Exception:  # noqa: BLE001
                    meta = {}
                out.append(
                    {
                        "csv": path.name,
                        "source_item_key": (r.get("source_item_key") or "").strip(),
                        "place_name": (r.get("place_name") or "").strip(),
                        "feature_id": (r.get("feature_id") or "").strip(),
                        "address_hint": (r.get("address_hint") or "").strip(),
                        "region": str(meta.get("region") or "").strip(),
                    }
                )
    return out


async def main() -> None:
    all_rows = rows()
    specified = [r for r in all_rows if r["feature_id"]]
    blank = [r for r in all_rows if not r["feature_id"]]
    print(f"CSV 전체 {len(all_rows)}행 | feature_id 지정 {len(specified)} | 빈 {len(blank)}")

    conn = await asyncpg.connect(DSN)
    try:
        print(f"DB={await conn.fetchval('select current_database()')}")

        # (1) 지정된 링크가 살아 있는가 — 이 변경은 이 경로를 건드리지 않는다.
        alive = 0
        for r in specified:
            ok = await conn.fetchval(
                "select 1 from feature.features where feature_id = $1"
                "   and deleted_at is null and status not in ('deleted','hidden')",
                r["feature_id"],
            )
            alive += 1 if ok else 0

        # (2) 빈 행에 대해 옛 규칙이 무엇을 자동 링크했을지 재생한다.
        dist: Counter[str] = Counter()
        blocked: list[dict] = []
        for r in blank:
            if not r["place_name"]:
                dist["place_name 없음"] += 1
                continue
            hits = await conn.fetch(
                _NAME_BRANCH_SQL, r["place_name"], r["address_hint"] or None
            )
            if not hits:
                dist["후보 0건"] += 1
                continue
            if len(hits) > 1:
                dist["후보 2건 이상(옛 규칙도 링크 안 함)"] += 1
                continue
            dist["후보 1건(옛 규칙이 자동 링크)"] += 1
            h = hits[0]
            region_ok: bool | None = None
            if r["region"] and h["sido_name"]:
                region_ok = r["region"] in h["sido_name"]
            blocked.append(
                {
                    **r,
                    "would_link_feature_id": h["feature_id"],
                    "would_link_name": h["name"],
                    "would_link_sido": h["sido_name"],
                    "region_agrees": region_ok,
                }
            )
    finally:
        await conn.close()

    print(f"\n지정 링크 {len(specified)}건 중 live: {alive} (이 변경과 무관한 경로)")
    print("\n빈 행 후보 분포:")
    for k, v in dist.most_common():
        print(f"  {v:>4}  {k}")

    agree = sum(1 for b in blocked if b["region_agrees"] is True)
    disagree = sum(1 for b in blocked if b["region_agrees"] is False)
    unknown = sum(1 for b in blocked if b["region_agrees"] is None)
    print(f"\n=== 이 변경으로 막히는 자동 링크: {len(blocked)}건 ===")
    print(f"  region 일치 {agree} / 불일치 {disagree} / 판정불가 {unknown}")
    for b in blocked:
        mark = {True: "일치", False: "★불일치", None: "region없음"}[b["region_agrees"]]
        print(
            f"  [{mark}] {b['source_item_key']} {b['place_name']} "
            f"(region={b['region'] or '-'}) → {b['would_link_name']} / {b['would_link_sido']}"
        )

    with open(OUT, "w", encoding="utf-8") as fh:  # noqa: ASYNC230  # 1회성 증거
        json.dump(
            {
                "summary": {
                    "csv_rows": len(all_rows),
                    "csv_specified": len(specified),
                    "csv_specified_alive": alive,
                    "csv_blank": len(blank),
                    "blank_candidate_distribution": dict(dist),
                    "blocked_autolinks": len(blocked),
                    "blocked_region_agrees": agree,
                    "blocked_region_disagrees": disagree,
                    "blocked_region_unknown": unknown,
                },
                "blocked": blocked,
            },
            fh,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
