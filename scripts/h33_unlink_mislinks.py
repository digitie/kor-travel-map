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

**⚠ 이 해제는 durable하지 않다 — 다음 공식 CSV import가 그대로 되살린다.**

초안은 여기에 *"CSV의 `feature_id`가 비어 있으니 import가 다시 링크하지 않는다"*고 적었다.
**틀렸다**(적대 리뷰 실측). `feature_id = EXCLUDED.feature_id`까지만 읽고 `EXCLUDED`에 무엇이
들어오는지 보지 않은 것이다. 빈 `feature_id`는 링크를 막는 게 아니라 **이름 자동매칭을 켠다**:

    -- curation_repo._RESOLVE_FEATURES_BATCH_SQL
    WHERE requested.feature_id IS NULL
      AND lower(f.name) = lower(requested.place_name)
      AND (requested.address_hint IS NULL OR ...)   -- 이 3행은 address_hint도 비어 있다

단일 매칭이면 그 id가 그대로 `EXCLUDED.feature_id`가 된다(`curations.py`의
`match = matches[0] if len(matches) == 1 else None`). prod에 `남이섬`·`청남대`라는 이름의
live feature는 **각각 하나뿐이고 그게 바로 틀린 그 feature**다. 커밋된 CSV의 빈 264행 중
단일 매칭으로 해석되는 건 정확히 이 3행뿐이고, 전부 방금 끊은 그 feature로 돌아간다.

게다가 import는 `metadata = EXCLUDED.metadata`로 무조건 덮으므로 아래에서 남기는 사유도
같이 지워진다. 그래서 finding을 `resolved`가 아니라 **`open`으로 남긴다** — 아직 안 끝났다.

근본 수정(리졸버에 지역 교차검증을 넣거나, import가 존중하는 "링크 금지" 표식)은
`T-VN-H36`이다. 그때까지 이 스크립트는 **증상 완화**이지 해결이 아니다.
다행히 지금 당장 되살아나지는 않는다 — prod는 alembic `0063`이라 HEAD의 import SQL이
참조하는 컬럼이 없어 import 자체가 실패한다. `T-VN-H35`가 마이그레이션을 적용하는 순간
되살아나므로, **H35보다 H36이 먼저**여야 한다.

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
   and ci.archived_at is null
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
# **`feature_id` 컬럼은 비운다.** `fk_data_integrity_violations_feature_id_features`가
# `ON DELETE CASCADE`라, 문제의 그 엉뚱한 feature를 지우는 순간(가장 자연스러운 후속 정리)
# "그 feature에 잘못 링크돼 있었다"는 기록이 통째로 사라진다. id는 payload에만 남긴다 —
# `source_record_key`를 비운 것과 같은 이유다.
_FIND_EXISTING_SQL = """
select issue_id::text
  from ops.data_integrity_violations
 where payload ->> 'dedupe_key' = $1
   and violation_type = 'curation_feature_region_mismatch'
 order by detected_at desc
 limit 1
"""

_INSERT_FINDING_SQL = """
insert into ops.data_integrity_violations (
    provider, dataset_key, source_record_key, feature_id,
    violation_type, severity, message, payload, status
) values (
    'curation', $1, null, null,
    'curation_feature_region_mismatch', 'error', $2,
    jsonb_strip_nulls($3::jsonb), 'open'
)
returning issue_id::text
"""

# 같은 dedupe_key를 **상태와 무관하게** 찾아 open으로 되돌린다.
# 0067 docstring은 "닫은 뒤 재발하면 새 행"을 의도하지만, 여기서는 애초에 닫지 않는다 —
# import가 되살릴 수 있는 한 이 finding은 계속 열려 있어야 한다. (이 경로는 이 스크립트가
# 먼저 `resolved`로 잘못 기록한 3행을 바로잡는 데도 쓰인다.)
_UPDATE_FINDING_SQL = """
update ops.data_integrity_violations
   set provider = 'curation',
       dataset_key = $4,
       source_record_key = null,
       feature_id = null,
       violation_type = 'curation_feature_region_mismatch',
       severity = 'error',
       message = $2,
       payload = jsonb_strip_nulls($3::jsonb),
       status = 'open',
       resolved_at = null
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
        already = 0
        guarded = 0
        emitted = 0
        for (collection_key, item_key), (expected_fid, reason) in MISLINKS.items():
            rows = await conn.fetch(_SELECT_SQL, collection_key, item_key)
            if not rows:
                print(f"  ★ {item_key}: 해당 curation_item 없음")
                guarded += 1
                continue

            # (collection_key, external_item_id)는 **유일하지 않다** — 같은 item에
            # external_component_id가 다른 형제 행이 있을 수 있다(prod에 19개 그룹 존재).
            # 형제가 다른 feature를 가리키는 건 정상이므로 가드에 걸려도 "동시 변경" 경보를
            # 울리면 안 된다. 우리가 지목한 feature를 가진 행만 대상으로 좁힌다.
            targets = [r for r in rows if r["feature_id"] == expected_fid]
            siblings = len(rows) - len(targets)
            if siblings:
                print(f"  참고 {item_key}: 형제 행 {siblings}건은 대상 아님(정상)")

            if not targets:
                if any(r["feature_id"] is None for r in rows):
                    print(f"  이미 해제됨 {item_key}")
                    already += 1
                else:
                    print(
                        f"  ★ 건너뜀 {item_key}: 지목한 오링크({expected_fid})를 가진 행이 없다 "
                        f"— 그 사이 재링크됐을 수 있다"
                    )
                    guarded += 1

            payload = {
                "dedupe_key": f"curation_mislink:{collection_key}:{item_key}",
                "collection_key": collection_key,
                "external_item_id": item_key,
                "place_name": (targets or rows)[0]["place_name"],
                "unlinked_feature_id": expected_fid,
                "reason": reason,
                "task": "T-VN-H33",
                "remediation": "feature_id를 NULL로 되돌렸다",
                "public_exposure": (
                    "/v1/curations/features/{feature_id} (공개 라우터)로 노출되고 있었다"
                ),
                "durability": (
                    "durable하지 않다 — 공식 CSV import가 빈 feature_id에 대해 이름 자동매칭을 "
                    "수행해 같은 feature로 되돌린다. 근본 수정은 T-VN-H36."
                ),
            }
            message = f"curation 링크가 다른 지역을 가리킨다: {payload['place_name']} — {reason}"

            for row in targets:
                print(
                    f"  대상 {item_key} ({row['place_name']}) → "
                    f"{row['feature_name']} | {row['feature_addr'][:44]}"
                )
                payload["unlinked_feature_name"] = row["feature_name"]
                payload["unlinked_feature_address"] = row["feature_addr"]

                meta = row["metadata"]
                if isinstance(meta, str):
                    meta = json.loads(meta or "{}")
                meta = dict(meta or {})
                meta["feature_match_status"] = "unresolved"
                # 링크를 정당화하던 키는 전부 걷어낸다. 하나라도 남으면 "왜 비어 있지?"가
                # 다시 링크로 이어진다. (H25B 계열 키 confidence/confidence_reason 포함.)
                for stale in (
                    "feature_match_confidence",
                    "feature_match_partial",
                    "confidence",
                    "confidence_reason",
                ):
                    meta.pop(stale, None)
                prior = meta.get("feature_match_reasons") or []
                meta["feature_match_reasons"] = [
                    f"T-VN-H33: 오링크 해제. {reason}. "
                    f"해제 전 링크 대상은 {expected_fid}였다.",
                    *[str(x) for x in prior],
                ]

                if not args.apply:
                    print("    (dry-run) unlink 예정")
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
                    # SELECT와 UPDATE 사이에 바뀐 경우에만 여기 온다.
                    print("    ★ UPDATE가 0행 — 동시 변경. 건너뜀")
                    guarded += 1
                    continue
                print("    unlink 완료")
                unlinked += 1

            # finding은 **이미 해제된 경우에도** 갱신한다. 문제가 durable하게 해결되지 않았고
            # (import가 되살린다), 이 스크립트가 처음에 잘못 기록한 resolved 행도 바로잡아야
            # 하므로, 해제 여부와 무관하게 open 상태로 유지한다.
            if not args.apply:
                print("    (dry-run) finding open 유지 예정")
                emitted += 1
                continue

            payload_json = json.dumps(payload, ensure_ascii=False)
            async with conn.transaction():
                existing = await conn.fetchval(_FIND_EXISTING_SQL, payload["dedupe_key"])
                if existing is None:
                    issue_id = await conn.fetchval(
                        _INSERT_FINDING_SQL, collection_key, message, payload_json
                    )
                    how = "신규"
                else:
                    issue_id = await conn.fetchval(
                        _UPDATE_FINDING_SQL,
                        existing,
                        message,
                        payload_json,
                        collection_key,
                    )
                    how = "갱신"
            print(f"    finding={issue_id} ({how}, open)")
            emitted += 1

        verb = "해제" if args.apply else "해제 예정"
        print(
            f"\n{verb} {unlinked}행 / 이미 해제 {already}건 / 가드 {guarded}건 / "
            f"finding {emitted}건(open)"
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
