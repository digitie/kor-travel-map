"""T-VN-H25A 기준선 — 공식 CSV의 feature_id 중 실제로 없는 것을 실데이터로 재확인한다.

**읽기 전용**. CSV도 DB도 바꾸지 않는다 (task 문구: "이 단계에서는 CSV/DB target을 바꾸지 않는다").
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
from collections import Counter
from pathlib import Path

import asyncpg

CSV_DIR = Path(os.environ.get("CSV_DIR", "/workspace/resources/curations"))
DSN = os.environ["DSN"].replace("+asyncpg", "")


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


async def main() -> None:
    rows = load_rows()
    with_fid = [r for r in rows if (r.get("feature_id") or "").strip()]
    unique = sorted({r["feature_id"].strip() for r in with_fid})
    print(f"CSV 행 {len(rows)} | feature_id 보유 {len(with_fid)} | 고유 {len(unique)}")
    print("CSV별 행수:", dict(Counter(r["_csv"] for r in rows)))

    conn = await asyncpg.connect(DSN)
    try:
        found = await conn.fetch(
            "select feature_id, status, name from feature.features "
            "where feature_id = any($1::text[])",
            unique,
        )
        found_map = {r["feature_id"]: r for r in found}
        missing = [f for f in unique if f not in found_map]
        print(f"\n존재 {len(found_map)} / 부재 **{len(missing)}** (고유 {len(unique)})")
        print("존재하는 것의 status 분포:", dict(Counter(r["status"] for r in found)))

        # 부재 feature_id가 과거에 존재했는지 — merge/lifecycle 흔적 조회
        print("\n=== 부재 feature_id의 흔적 조회 ===")
        for table, col in (
            ("feature.feature_merges", "source_feature_id"),
            ("feature.feature_merges", "target_feature_id"),
            ("feature.source_links", "feature_id"),
        ):
            try:
                n = await conn.fetchval(
                    f"select count(*) from {table} where {col} = any($1::text[])",
                    missing,
                )
                print(f"  {table}.{col}: {n}건")
            except Exception as exc:  # noqa: BLE001
                print(f"  {table}.{col}: 조회 불가 ({type(exc).__name__})")

        # 부재 항목의 CSV 측 단서
        by_fid: dict[str, list[dict]] = {}
        for r in with_fid:
            by_fid.setdefault(r["feature_id"].strip(), []).append(r)
        print("\n=== 부재 항목 표본 12건 (CSV 단서) ===")
        for fid in missing[:12]:
            r = by_fid[fid][0]
            meta = {}
            try:
                meta = json.loads(r.get("metadata_json") or "{}")
            except Exception:  # noqa: BLE001
                pass
            print(
                f"  {fid} | {r['_csv']} | {r.get('place_name')} | "
                f"addr={r.get('address_hint') or '-'} | "
                f"conf={meta.get('feature_match_confidence')}"
            )

        # confidence 분포 (부재 vs 존재)
        def conf_of(r: dict) -> str:
            try:
                return json.loads(r.get("metadata_json") or "{}").get(
                    "feature_match_confidence", "-"
                )
            except Exception:  # noqa: BLE001
                return "-"

        miss_set = set(missing)
        print("\n부재 항목 confidence 분포:", dict(Counter(
            conf_of(by_fid[f][0]) for f in missing
        )))
        print("존재 항목 confidence 분포:", dict(Counter(
            conf_of(by_fid[f][0]) for f in unique if f not in miss_set
        )))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
