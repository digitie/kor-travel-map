"""T-VN-H25B — DB에는 링크됐으나 공식 CSV가 비어 있는 항목을 특정한다. **읽기 전용.**

H25A가 집계로만 확인한 8건(CSV linked 217 vs DB linked 225)을 항목 단위로 짚는다.
component 행이 ``source_item_key``를 공유하므로 단건 조인 대신
(collection_key, source_item_key) 묶음의 **feature_id 집합**을 비교한다.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
from collections import defaultdict
from pathlib import Path

import asyncpg

CSV_DIR = Path(os.environ.get("CSV_DIR", "/workspace/resources/curations"))
DSN = os.environ["DSN"].replace("+asyncpg", "")
OUT = os.environ.get("OUT", "/out/h25b-backfill.json")


def csv_groups() -> dict[tuple[str, str], dict]:
    groups: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"fids": set(), "rows": [], "csv": None}
    )
    for path in sorted(CSV_DIR.glob("*.csv")):
        if path.name == "template.csv":
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                key = (
                    (r.get("collection_key") or "").strip(),
                    (r.get("source_item_key") or "").strip(),
                )
                g = groups[key]
                g["csv"] = path.name
                fid = (r.get("feature_id") or "").strip()
                if fid:
                    g["fids"].add(fid)
                g["rows"].append(
                    {
                        "component": (r.get("source_component_key") or "").strip(),
                        "place_name": r.get("place_name"),
                        "feature_id": fid or None,
                        "official_ordinal": r.get("official_ordinal"),
                    }
                )
    return groups


async def main() -> None:
    groups = csv_groups()
    conn = await asyncpg.connect(DSN)
    try:
        db = await conn.fetch(
            """
            select cc.collection_key, ci.external_item_id, ci.place_name,
                   ci.feature_id, ci.sort_order, ci.status, ci.archived_at
            from feature.curation_items ci
            join feature.curation_collections cc on cc.collection_id = ci.collection_id
            where cc.collection_key = any($1::text[])
            """,
            sorted({k[0] for k in groups}),
        )
        print(f"CSV 묶음 {len(groups)} | DB 항목 {len(db)}")

        db_groups: dict[tuple[str, str], list] = defaultdict(list)
        for r in db:
            db_groups[(r["collection_key"], r["external_item_id"])].append(r)

        extra = []
        for key, g in sorted(groups.items()):
            rows = db_groups.get(key, [])
            db_fids = {r["feature_id"] for r in rows if r["feature_id"]}
            missing_in_csv = db_fids - g["fids"]
            if not missing_in_csv:
                continue
            for fid in sorted(missing_in_csv):
                hit = next((r for r in rows if r["feature_id"] == fid), None)
                extra.append(
                    {
                        "csv": g["csv"],
                        "collection_key": key[0],
                        "source_item_key": key[1],
                        "db_place_name": hit["place_name"] if hit else None,
                        "db_feature_id": fid,
                        "db_status": hit["status"] if hit else None,
                        "db_archived": bool(hit and hit["archived_at"]),
                        "csv_rows": g["rows"],
                    }
                )

        print(f"\n=== DB에만 있는 링크: {len(extra)}건 ===")
        for e in extra:
            blanks = [r for r in e["csv_rows"] if not r["feature_id"]]
            print(
                f"  {e['csv']} | {e['source_item_key']} | {e['db_place_name']} "
                f"→ {e['db_feature_id']} (status={e['db_status']}, "
                f"archived={e['db_archived']}, CSV 빈 행 {len(blanks)}/{len(e['csv_rows'])})"
            )

        # 반대 방향도 본다 — CSV에만 있고 DB에 없는 링크
        reverse = []
        for key, g in sorted(groups.items()):
            rows = db_groups.get(key, [])
            db_fids = {r["feature_id"] for r in rows if r["feature_id"]}
            only_csv = g["fids"] - db_fids
            for fid in sorted(only_csv):
                reverse.append({"key": key, "feature_id": fid, "csv": g["csv"]})
        print(f"\n=== CSV에만 있는 링크: {len(reverse)}건 ===")
        for r in reverse[:10]:
            print(f"  {r['csv']} | {r['key'][1]} → {r['feature_id']}")

        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(
                {"db_only": extra, "csv_only": reverse},
                f,
                ensure_ascii=False,
                indent=1,
            )
        print(f"\n저장: {OUT}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
