"""T-VN-H25A 결정적 검증 — 전제와 refutation 중 무엇이 맞는가. **읽기 전용.**

적대 리뷰 2건이 지적한 세 가지를 실제 스키마로 확인한다.
  1. 158개가 curation이 요구하는 **usable** 상태인가 (status/deleted_at), 그리고 언제 생겼나.
     → 전제 측정 이후에 적재됐다면 전제와 refutation은 **양립**한다.
  2. 261개 NULL이 ``ON DELETE SET NULL`` cascade로 지워진 링크인가, 정말 미연결인가.
     → merge history / source_records 로 판별.
  3. 269 vs 261 — 공식 collection으로 범위를 좁히면 일치하는가.
"""

from __future__ import annotations

import asyncio
import csv
import os
from collections import Counter
from pathlib import Path

import asyncpg

CSV_DIR = Path(os.environ.get("CSV_DIR", "/workspace/resources/curations"))
DSN = os.environ["DSN"].replace("+asyncpg", "")


def csv_feature_ids() -> tuple[list[str], list[str]]:
    ids, keys = set(), set()
    for path in sorted(CSV_DIR.glob("*.csv")):
        if path.name == "template.csv":
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                fid = (r.get("feature_id") or "").strip()
                if fid:
                    ids.add(fid)
                ck = (r.get("collection_key") or "").strip()
                if ck:
                    keys.add(ck)
    return sorted(ids), sorted(keys)


async def main() -> None:
    ids, coll_keys = csv_feature_ids()
    conn = await asyncpg.connect(DSN)
    try:
        db = await conn.fetchval("select current_database()")
        head = await conn.fetchval("select version_num from alembic_version limit 1")
        total = await conn.fetchval("select count(*) from feature.features")
        print(f"DB={db} | alembic={head} | features={total}")
        print(f"CSV 고유 feature_id {len(ids)} | collection_key {coll_keys}\n")

        # ── 1. usable 상태인가 + 언제 생겼나 ────────────────────────────────
        cols = {
            r["column_name"]
            for r in await conn.fetch(
                "select column_name from information_schema.columns "
                "where table_schema='feature' and table_name='features'"
            )
        }
        has_del = "deleted_at" in cols
        sel = "feature_id, status, created_at" + (", deleted_at" if has_del else "")
        rows = await conn.fetch(
            f"select {sel} from feature.features where feature_id = any($1::text[])", ids
        )
        print(f"[1] 존재 {len(rows)}/{len(ids)}")
        print("    status:", dict(Counter(r["status"] for r in rows)))
        if has_del:
            print("    deleted_at NOT NULL:", sum(1 for r in rows if r["deleted_at"]))
        usable = [
            r
            for r in rows
            if r["status"] not in ("deleted", "hidden")
            and (not has_del or r["deleted_at"] is None)
        ]
        print(f"    curation이 링크 가능한(usable) 건수: {len(usable)}/{len(ids)}")
        after = [r for r in rows if str(r["created_at"])[:10] >= "2026-07-27"]
        print(f"    created_at >= 2026-07-27 인 건수: {len(after)}  ← 전제와 양립 여부")
        if rows:
            cs = sorted(str(r["created_at"])[:10] for r in rows)
            print(f"    created_at 범위: {cs[0]} ~ {cs[-1]}")

        # ── 2. 261 NULL이 cascade로 지워진 링크인가 ─────────────────────────
        print("\n[2] curation_items NULL의 성격")
        item_cols = {
            r["column_name"]
            for r in await conn.fetch(
                "select column_name from information_schema.columns "
                "where table_schema='feature' and table_name='curation_items'"
            )
        }
        print(f"    curation_items 컬럼: {sorted(item_cols)}")
        pick = [c for c in ("collection_id", "source_record_key") if c in item_cols]
        null_rows = await conn.fetch(
            f"select {', '.join(pick) or '1 as x'} "
            "from feature.curation_items where feature_id is null"
        )
        print(f"    전체 NULL: {len(null_rows)}")
        if "source_record_key" not in item_cols:
            print("    source_record_key 컬럼 없음 — provenance 축 불가")
            with_src = []
        else:
            with_src = [r for r in null_rows if r["source_record_key"]]
        print(f"    source_record_key 보유: {len(with_src)}")
        if with_src:
            keys = [r["source_record_key"] for r in with_src]
            linked = await conn.fetchval(
                "select count(*) from provider_sync.source_links "
                "where source_record_key = any($1::text[])",
                keys,
            )
            print(f"    → provider_sync.source_links에 연결 이력 있는 건: {linked}")
        # merge history: 지워진 loser가 있었는가
        try:
            mh = await conn.fetchval("select count(*) from ops.feature_merge_history")
            print(f"    ops.feature_merge_history 총 행: {mh}")
            loser_hit = await conn.fetchval(
                "select count(*) from ops.feature_merge_history "
                "where loser_feature_id = any($1::text[])",
                ids,
            )
            print(f"    158개 중 merge loser였던 적 있는 건: {loser_hit}")
        except Exception as exc:  # noqa: BLE001
            print(f"    ops.feature_merge_history 조회 실패: {type(exc).__name__}: {exc}")

        # ── 3. 269 vs 261 — 공식 collection 범위 ────────────────────────────
        print("\n[3] 공식 collection 범위 정합")
        try:
            scoped = await conn.fetch(
                """
                select c.collection_key,
                       count(*) filter (where i.feature_id is null) as unresolved,
                       count(*) filter (where i.feature_id is not null) as linked,
                       count(*) as total
                from feature.curation_items i
                join feature.curation_collections c on c.collection_id = i.collection_id
                where c.collection_key = any($1::text[])
                group by 1 order by 1
                """,
                coll_keys,
            )
            tu = tl = 0
            for r in scoped:
                print(
                    f"    {r['collection_key']}: 총 {r['total']} | "
                    f"linked {r['linked']} | unresolved {r['unresolved']}"
                )
                tu += r["unresolved"]
                tl += r["linked"]
            print(f"    합계: linked {tl} | unresolved {tu}  (CSV: 217 / 269)")
        except Exception as exc:  # noqa: BLE001
            print(f"    범위 조회 실패: {type(exc).__name__}: {exc}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
