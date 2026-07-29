"""T-VN-H33 — curation_items 오링크를 끊고 ledger에 남긴다.

H25B가 정지오코딩으로 확인한 오링크 3건이 DB에 남아 **공개 REST로 노출되고 있었다**
(`/v1/curations/features/{feature_id}`는 public 라우터다). 한국관광100선의 "남이섬"이
서울 중구 사무소를, "청남대"가 전남 영암 시설을 가리켰다.

**왜 UPDATE 한 방이 아니라 이 스크립트인가**

1. *가드가 필요하다.* 대상 행의 현재 `feature_id`가 우리가 오링크라고 판정한 바로 그
   값일 때만 끊는다. 그 사이 누가 올바른 feature로 다시 링크했다면 건드리면 안 된다.
   가드에 걸린 행은 건너뛰고 **왜 건너뛰었는지 출력한다** — 조용한 no-op은 성공처럼 보인다.
2. *근거를 데이터에 남긴다.* `metadata.feature_match_status`를 되돌리고 사유를 적어,
   나중에 "왜 비어 있지?"가 다시 링크로 이어지지 않게 한다.
3. *ledger에 방출한다.* H30A의 `ops.data_integrity_violations`에 finding으로 남겨
   `/admin/issues`에서 보이게 한다. 고친 직후이므로 `resolved`로 닫되, 무엇이 어떻게
   틀렸는지는 payload에 남는다.

**재링크되지 않는 이유**: 공식 CSV import는 `feature_id = EXCLUDED.feature_id`로
COALESCE 없이 덮어쓴다(`curation_repo`). 커밋된 CSV의 이 3행은 `feature_id`가 비어 있으므로
다음 import가 다시 링크하지 않는다. 이 스크립트는 그 상태를 앞당길 뿐이다.

기본은 **dry-run**이다. 실제 쓰기는 ``--apply``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import asyncpg

# (collection_key, external_item_id) -> (오링크 feature_id, 사유)
#
# feature_id를 가드로 쓴다. H25B에서 정지오코딩으로 각각 확인한 값이다.
MISLINKS: dict[tuple[str, str], tuple[str, str]] = {
    ("korean-tourism-100:2023-2024", "kt100-2023-2024-025"): (
        "f_1114010100_p_a11c2e739c5676d2",
        "남이섬 → 서울 중구(11140) 사무소. 정지오코딩은 강원 춘천(51110)",
    ),
    ("korean-tourism-100:2025-2026", "kt100-2025-2026-024"): (
        "f_1114010100_p_a11c2e739c5676d2",
        "남이섬 → 서울 중구(11140) 사무소. 정지오코딩은 강원 춘천(51110)",
    ),
    ("korean-tourism-100:2025-2026", "kt100-2025-2026-036"): (
        "f_4683025328_p_a45038d401d8d1bd",
        "청남대 → 전남 영암(46830). 정지오코딩은 충북 청주(43111)",
    ),
}

_SELECT_SQL = """
select ci.curation_item_id, ci.external_item_id, ci.place_name, ci.feature_id,
       ci.metadata, cc.collection_key,
       f.name as feature_name,
       coalesce(f.address->>'road', f.address->>'legal', '') as feature_addr
  from feature.curation_items ci
  join feature.curation_collections cc on cc.collection_id = ci.collection_id
  left join feature.features f on f.feature_id = ci.feature_id
 where cc.collection_key = $1 and ci.external_item_id = $2
"""

_UNLINK_SQL = """
update feature.curation_items
   set feature_id = null,
       metadata = $2::jsonb,
       updated_at = now()
 where curation_item_id = $1
   and feature_id = $3
returning curation_item_id
"""

# finding 방출. **`ON CONFLICT`를 쓰지 않는다** — 두 번 실측으로 막혔다.
#
# 1. dedupe arbiter인 부분 유니크 인덱스(0067)의 술어는
#    ``status IN ('open','acknowledged') AND payload ? 'dedupe_key'``다.
#    곧바로 ``status='resolved'``로 INSERT하면 그 행은 인덱스 대상이 아니라 arbiter 추론이
#    실패한다.
# 2. 그래서 open으로 upsert하도록 고쳤더니 **같은 오류가 또 났다**. 원인은 다른 데 있었다 —
#    **prod alembic head가 `0063_pipeline_root_id`라 0067이 아예 적용된 적이 없다.**
#    H30A가 만든 dedupe 인덱스는 prod에 존재하지 않는다.
#
# 덧붙여 ``source_record_key``에는 ``provider_sync.source_records``로 FK가 걸려 있어
# curation item 키를 넣을 수 없다(실측: ForeignKeyViolation). NULL로 두고 payload의
# ``external_item_id``에만 남긴다 — ledger는 provider 적재를 전제로 설계된 테이블이다.
#
# 그러니 dedupe를 **응용단에서** 한다: dedupe_key로 먼저 찾아보고 있으면 UPDATE, 없으면
# INSERT. 인덱스가 있든 없든 맞게 동작하고, 나중에 0067이 적용돼도 그대로 옳다.
# (동시성 방어는 인덱스가 하는 일이라 여기선 얻지 못한다. 이 스크립트는 단발 운영 도구다.)
_FIND_EXISTING_SQL = """
select issue_id::text
  from ops.data_integrity_violations
 where payload ->> 'dedupe_key' = $1
 order by detected_at desc
 limit 1
"""

_INSERT_FINDING_SQL = """
insert into ops.data_integrity_violations (
    provider, dataset_key, source_record_key, feature_id,
    violation_type, severity, message, payload, status, resolved_at
) values (
    'curation', $1, null, $2,
    'curation_feature_region_mismatch', 'error', $3,
    jsonb_strip_nulls($4::jsonb), 'resolved', now() at time zone 'UTC'
)
returning issue_id::text
"""

_UPDATE_FINDING_SQL = """
update ops.data_integrity_violations
   set message = $2,
       payload = jsonb_strip_nulls($3::jsonb),
       status = 'resolved',
       resolved_at = now() at time zone 'UTC'
 where issue_id = $1::uuid
returning issue_id::text
"""


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다 (기본은 dry-run)")
    args = ap.parse_args()

    dsn = os.environ["DSN"].replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        db = await conn.fetchval("select current_database()")
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"DB={db} mode={mode}\n")

        unlinked = 0
        skipped = 0
        for (collection_key, item_key), (expected_fid, reason) in MISLINKS.items():
            rows = await conn.fetch(_SELECT_SQL, collection_key, item_key)
            if not rows:
                print(f"  건너뜀 {item_key}: 해당 curation_item 없음")
                skipped += 1
                continue
            for row in rows:
                current = row["feature_id"]
                if current is None:
                    print(f"  건너뜀 {item_key}: 이미 미연결")
                    skipped += 1
                    continue
                if current != expected_fid:
                    # 가드. 우리가 판정한 오링크가 아니면 손대지 않는다.
                    print(
                        f"  ★ 건너뜀 {item_key}: feature_id가 예상과 다름 "
                        f"(현재 {current}, 예상 {expected_fid}) — 그 사이 재링크됐을 수 있다"
                    )
                    skipped += 1
                    continue

                print(
                    f"  대상 {item_key} ({row['place_name']}) → "
                    f"{row['feature_name']} | {row['feature_addr'][:44]}"
                )

                meta = row["metadata"]
                if isinstance(meta, str):
                    meta = json.loads(meta or "{}")
                meta = dict(meta or {})
                meta["feature_match_status"] = "unresolved"
                meta.pop("feature_match_confidence", None)
                meta["feature_match_reasons"] = [
                    f"T-VN-H33: 오링크 해제. {reason}. "
                    f"해제 전 링크 대상은 {expected_fid}였다."
                ]

                payload = {
                    "dedupe_key": f"curation_mislink:{collection_key}:{item_key}",
                    "collection_key": collection_key,
                    "external_item_id": item_key,
                    "place_name": row["place_name"],
                    "unlinked_feature_id": expected_fid,
                    "unlinked_feature_name": row["feature_name"],
                    "unlinked_feature_address": row["feature_addr"],
                    "reason": reason,
                    "task": "T-VN-H33",
                    "remediation": "feature_id를 NULL로 되돌렸다",
                    "public_exposure": (
                        "/v1/curations/features/{feature_id} (공개 라우터)로 노출되고 있었다"
                    ),
                }
                message = f"curation 링크가 다른 지역을 가리킨다: {row['place_name']} — {reason}"

                if not args.apply:
                    print("    (dry-run) unlink + finding 방출 예정")
                    unlinked += 1
                    continue

                async with conn.transaction():
                    done = await conn.fetchval(
                        _UNLINK_SQL,
                        row["curation_item_id"],
                        json.dumps(meta, ensure_ascii=False),
                        expected_fid,
                    )
                    if done is None:
                        # 가드 재확인. SELECT와 UPDATE 사이에 바뀌었으면 여기서 걸린다.
                        print("    ★ UPDATE가 0행 — 동시 변경. 건너뜀")
                        skipped += 1
                        continue
                    payload_json = json.dumps(payload, ensure_ascii=False)
                    existing = await conn.fetchval(
                        _FIND_EXISTING_SQL, payload["dedupe_key"]
                    )
                    if existing is None:
                        issue_id = await conn.fetchval(
                            _INSERT_FINDING_SQL,
                            collection_key,
                            expected_fid,
                            message,
                            payload_json,
                        )
                        how = "신규"
                    else:
                        issue_id = await conn.fetchval(
                            _UPDATE_FINDING_SQL, existing, message, payload_json
                        )
                        how = "갱신"
                print(f"    unlink 완료. finding={issue_id} ({how}, resolved)")
                unlinked += 1

        print(f"\n{'해제' if args.apply else '해제 예정'} {unlinked}행 / 건너뜀 {skipped}행")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
