"""T-VN-H25A — 미연결 curation 항목 evidence manifest.

**읽기 전용.** CSV도 DB도 바꾸지 않는다.

각 미연결 항목에 대해 이름·주소 단서로 후보 Feature를 찾고, 근거와 confidence를 남긴다.
좌표 근접만으로 자동 승인하지 않는다 — 이름 일치가 없으면 후보로 올리되 승인하지 않는다.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re
from collections import Counter
from pathlib import Path

import asyncpg

CSV_DIR = Path(os.environ.get("CSV_DIR", "/workspace/resources/curations"))
DSN = os.environ["DSN"].replace("+asyncpg", "")
OUT = os.environ.get("OUT", "/out/h25a-unlinked-manifest.json")

_PAREN = re.compile(r"[（(].*?[)）]")


def norm(s: object) -> str:
    t = _PAREN.sub("", str(s or ""))
    return "".join(t.split()).lower()


def load_rows() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(CSV_DIR.glob("*.csv")):
        if path.name == "template.csv":
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                r["_csv"] = path.name
                rows.append(r)
    return rows


async def candidates_for(
    conn: asyncpg.Connection, name: str, hint: str, region: str
) -> list[dict]:
    """이름 기반 후보. 주소 단서가 있으면 가산점만 주고 단독 근거로 쓰지 않는다."""
    if not name.strip():
        return []
    rows = await conn.fetch(
        """
        select feature_id, name, status,
               coalesce(address->>'road', address->>'legal', '') as addr,
               sigungu_code
        from feature.features
        where status = 'active' and replace(name, ' ', '') = replace($1, ' ', '')
        limit 20
        """,
        name.strip(),
    )
    if not rows:
        rows = await conn.fetch(
            """
            select feature_id, name, status,
                   coalesce(address->>'road', address->>'legal', '') as addr,
                   sigungu_code
            from feature.features
            where status = 'active'
              and replace(name, ' ', '') ilike replace($1, ' ', '')
            limit 20
            """,
            f"%{name.strip()}%",
        )
    # 이름 완전일치 후보 수(=모호성)와 region 일치를 두 축으로 쓴다.
    #
    # ``address_hint``는 공식 CSV 486행 **전부 비어 있어**(실측) 판정 축이 될 수 없다.
    # 이걸 high의 필수 조건으로 두면 high는 구조적으로 도달 불가가 되고, "high 0건"은
    # 데이터가 아니라 채점 함수의 성질이 된다. 실제로 존재하는 축만 쓴다.
    exact = [r for r in rows if norm(r["name"]) == norm(name)]
    out = []
    for r in rows:
        is_exact = norm(r["name"]) == norm(name)
        addr = r["addr"] or ""
        region_state = (
            "unknown" if not region else ("match" if region in addr else "mismatch")
        )
        if is_exact and len(exact) == 1 and region_state == "match":
            conf, why = "high", "이름 완전일치 + 유일 후보 + region 일치"
        elif is_exact and len(exact) == 1 and region_state == "unknown":
            conf, why = "review", "이름 완전일치·유일 후보이나 region 단서 없음"
        elif is_exact and region_state == "mismatch":
            conf, why = "low", f"이름은 같으나 region 불일치(CSV={region})"
        elif is_exact:
            conf, why = "review", f"이름 완전일치이나 후보 {len(exact)}건으로 모호"
        else:
            conf, why = "low", "이름 부분일치만"
        out.append(
            {
                "feature_id": r["feature_id"],
                "name": r["name"],
                "address": addr,
                "sigungu_code": r["sigungu_code"],
                "exact_name_candidates": len(exact),
                "region_state": region_state,
                "confidence": conf,
                "reason": why,
            }
        )
    order = {"high": 0, "review": 1, "low": 2}
    return sorted(out, key=lambda c: order[c["confidence"]])[:5]


async def main() -> None:
    rows = load_rows()
    unlinked = [r for r in rows if not (r.get("feature_id") or "").strip()]
    print(f"CSV 행 {len(rows)} | 미연결 {len(unlinked)}")

    conn = await asyncpg.connect(DSN)
    entries = []
    try:
        db_null = await conn.fetchval(
            "select count(*) from feature.curation_items where feature_id is null"
        )
        db_dangling = await conn.fetchval(
            "select count(*) from feature.curation_items t "
            "where t.feature_id is not null and not exists "
            "(select 1 from feature.features f where f.feature_id = t.feature_id)"
        )
        print(f"DB curation_items: feature_id NULL {db_null} | dangling {db_dangling}")

        for i, r in enumerate(unlinked):
            name = (r.get("place_name") or "").strip()
            hint = (r.get("address_hint") or "").strip()
            try:
                meta = json.loads(r.get("metadata_json") or "{}")
            except Exception:  # noqa: BLE001
                meta = {}
            region = str(meta.get("region") or "").strip()
            cands = await candidates_for(conn, name, hint, region)
            top = cands[0]["confidence"] if cands else "none"
            entries.append(
                {
                    "csv": r["_csv"],
                    "collection_key": r.get("collection_key"),
                    "source_item_key": r.get("source_item_key"),
                    "source_component_key": r.get("source_component_key"),
                    "place_name": name,
                    "address_hint": hint or None,
                    "region": region or None,
                    "official_ordinal": r.get("official_ordinal"),
                    "top_confidence": top,
                    "unresolved_reason": (
                        None
                        if top in ("high",)
                        else (
                            "후보 없음 — 이름으로 active feature를 찾지 못함"
                            if top == "none"
                            else "자동 승인 불가 — 주소 단서로 확정되지 않음"
                        )
                    ),
                    "candidates": cands,
                }
            )
            if (i + 1) % 50 == 0:
                print(f"  ... {i + 1}/{len(unlinked)}")
    finally:
        await conn.close()

    dist = Counter(e["top_confidence"] for e in entries)
    print("\n=== 미연결 항목 후보 등급 분포 ===")
    for k in ("high", "review", "low", "none"):
        if dist.get(k):
            print(f"  {dist[k]:4d}  {k}")

    print("\n=== high (자동 승인 후보) 표본 10건 ===")
    for e in [x for x in entries if x["top_confidence"] == "high"][:10]:
        c = e["candidates"][0]
        print(f"  {e['place_name']} → {c['feature_id']} | {c['name']} | {c['address'][:34]}")

    print("\n=== none (후보 없음) 표본 10건 ===")
    for e in [x for x in entries if x["top_confidence"] == "none"][:10]:
        print(f"  {e['csv']} | {e['place_name']} | hint={e['address_hint']}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": {
                    "csv_rows": len(rows),
                    "unlinked_csv_rows": len(unlinked),
                    "db_curation_items_null_feature_id": db_null,
                    "db_curation_items_dangling": db_dangling,
                    "confidence_distribution": dict(dist),
                },
                "entries": entries,
            },
            f,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\nmanifest 저장: {OUT} ({len(entries)} entries)")


if __name__ == "__main__":
    asyncio.run(main())
