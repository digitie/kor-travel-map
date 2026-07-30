"""T-VN-H33 — curation_items 오링크를 원자적으로 끊고 ledger에 남긴다.

H25B가 확인한 3건만 현재 ``feature_id``를 가드로 잠근 뒤 해제한다. H36이 이름 단독
자동 링크를 막았으므로 해제는 durable하며 finding은 증거를 보존한 ``resolved`` 상태다.
대상 row lock, guarded UPDATE, finding 기록은 항목별 한 transaction이다. ledger 기록이
실패하면 unlink도 함께 rollback한다. 이미 해제된 행은 ledger가 없으면 resolved 증거를
재구성하고, 올바른 Feature로 재연결된 행은 신규 finding 없이 기존 finding만 정규화한다.

기본은 **dry-run**이다. 실제 쓰기는 ``--apply``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import asyncpg

# (collection_key, external_item_id, external_component_id) ->
# (오링크 feature_id, 사유)
#
# feature_id를 가드로 쓴다. H25B에서 정지오코딩으로 각각 확인한 값이다.
MISLINKS: dict[tuple[str, str, str], tuple[str, str]] = {
    ("korean-tourism-100:2023-2024", "kt100-2023-2024-025", "primary"): (
        "f_1114010100_p_a11c2e739c5676d2",
        "남이섬 → 서울 중구(11140) 사무소. 정지오코딩은 강원 춘천(51110)",
    ),
    ("korean-tourism-100:2025-2026", "kt100-2025-2026-024", "primary"): (
        "f_1114010100_p_a11c2e739c5676d2",
        "남이섬 → 서울 중구(11140) 사무소. 정지오코딩은 강원 춘천(51110)",
    ),
    ("korean-tourism-100:2025-2026", "kt100-2025-2026-036", "primary"): (
        "f_4683025328_p_a45038d401d8d1bd",
        "청남대 → 전남 영암(46830). 정지오코딩은 충북 청주(43111)",
    ),
}

_SELECT_SQL = """
select ci.curation_item_id, ci.external_item_id, ci.external_component_id,
       ci.place_name, ci.feature_id, ci.metadata, cc.collection_key,
       f.name as feature_name,
       coalesce(f.address->>'road', f.address->>'legal', '') as feature_addr
  from feature.curation_items ci
  join feature.curation_collections cc on cc.collection_id = ci.collection_id
  left join feature.features f on f.feature_id = ci.feature_id
 where cc.collection_key = $1
   and ci.external_item_id = $2
   and ci.external_component_id = $3
   and ci.archived_at is null
"""

_SELECT_FOR_UPDATE_SQL = _SELECT_SQL + "\n for update of ci"

_UNLINK_SQL = """
update feature.curation_items
   set feature_id = null,
       metadata = $2::jsonb,
       updated_at = now()
 where curation_item_id = $1
   and feature_id = $3
returning curation_item_id
"""

_LOCK_FINDING_SQL = """
select pg_advisory_xact_lock(hashtextextended($1, 0))
"""

_FIND_EXISTING_SQL = """
select issue_id::text
  from ops.data_integrity_violations
 where payload ->> 'dedupe_key' = any($1::text[])
   and violation_type = 'curation_feature_region_mismatch'
 order by detected_at desc
 limit 1
"""

_INSERT_FINDING_SQL = """
insert into ops.data_integrity_violations (
    provider, dataset_key, source_record_key, feature_id,
    violation_type, severity, message, payload, status, resolved_at
) values (
    'curation', $1, null, null,
    'curation_feature_region_mismatch', 'warning', $2,
    jsonb_strip_nulls($3::jsonb), 'resolved', now()
)
returning issue_id::text
"""

_UPDATE_FINDING_SQL = """
update ops.data_integrity_violations
   set provider = 'curation',
       dataset_key = $4,
       source_record_key = null,
       feature_id = null,
       violation_type = 'curation_feature_region_mismatch',
       severity = 'warning',
       message = $2,
       payload = jsonb_strip_nulls($3::jsonb),
       status = 'resolved',
       resolved_at = coalesce(resolved_at, now())
 where issue_id = $1::uuid
returning issue_id::text
"""


def _finding_payload(
    *,
    collection_key: str,
    item_key: str,
    component_key: str,
    expected_fid: str,
    reason: str,
    row: object,
    outcome: str,
) -> dict[str, object]:
    return {
        "dedupe_key": (
            f"curation_mislink:{collection_key}:{item_key}:{component_key}"
        ),
        "collection_key": collection_key,
        "external_item_id": item_key,
        "external_component_id": component_key,
        "place_name": row["place_name"],  # type: ignore[index]
        "unlinked_feature_id": expected_fid,
        "reason": reason,
        "task": "T-VN-H33",
        "outcome": outcome,
        "remediation": "잘못된 feature_id를 NULL로 되돌리고 H36 자동 재링크 방지를 적용했다",
        "public_exposure": (
            "/v1/curations/features/{feature_id} 표면에서 잘못 노출된 이력을 보존한다"
        ),
        "durability": (
            "durable — H36이 address_hint 없는 이름 단독 후보를 자동 링크하지 않는다"
        ),
    }


async def run(conn: object, *, apply: bool) -> None:
    """연결 하나에서 대상 전부를 처리한다. 항목별 transaction이 복구 경계다."""

    db = await conn.fetchval("select current_database()")  # type: ignore[attr-defined]
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"DB={db} mode={mode}\n")

    unlinked = 0
    already = 0
    guarded = 0
    emitted = 0
    for (
        collection_key,
        item_key,
        component_key,
    ), (expected_fid, reason) in MISLINKS.items():
        finding_result: tuple[str, str] | None = None
        async with conn.transaction():  # type: ignore[attr-defined]
            rows = await conn.fetch(  # type: ignore[attr-defined]
                _SELECT_FOR_UPDATE_SQL if apply else _SELECT_SQL,
                collection_key,
                item_key,
                component_key,
            )
            if not rows:
                print(
                    f"  ★ {item_key}/{component_key}: 해당 curation_item 없음"
                )
                guarded += 1
                continue
            if len(rows) != 1:
                raise RuntimeError(
                    f"{item_key}/{component_key}: active identity가 {len(rows)}행이다"
                )

            # membership의 정확한 identity는 collection + item + component다.
            # item만 조회하면 NULL인 형제 component를 대상 해제 이력으로 오인한다.
            targets = [r for r in rows if r["feature_id"] == expected_fid]

            if not targets:
                already_unlinked = rows[0]["feature_id"] is None
                if already_unlinked:
                    print(f"  이미 해제됨 {item_key}/{component_key}")
                    already += 1
                else:
                    print(
                        f"  ★ 건너뜀 {item_key}/{component_key}: "
                        f"지목한 오링크({expected_fid})를 가진 행이 없다 "
                        f"— 현재 링크를 보존한다"
                    )
                    guarded += 1
                if apply:
                    dedupe_key = (
                        f"curation_mislink:{collection_key}:{item_key}:"
                        f"{component_key}"
                    )
                    legacy_dedupe_key = (
                        f"curation_mislink:{collection_key}:{item_key}"
                    )
                    await conn.fetchval(_LOCK_FINDING_SQL, dedupe_key)  # type: ignore[attr-defined]
                    existing = await conn.fetchval(  # type: ignore[attr-defined]
                        _FIND_EXISTING_SQL,
                        [dedupe_key, legacy_dedupe_key],
                    )
                    # 지목한 오링크가 이미 NULL이면 실제 해제 이력이 있으므로 ledger가
                    # 유실된 clone/복구 상태에서도 resolved 증거를 재구성한다. 반대로
                    # 올바른 non-null 링크로 바뀐 guard 상태는 기존 finding만 닫고 신규
                    # finding을 만들지 않는다.
                    if existing is not None or already_unlinked:
                        outcome = (
                            "already_unlinked"
                            if already_unlinked
                            else "guarded_current_link_preserved"
                        )
                        payload = _finding_payload(
                            collection_key=collection_key,
                            item_key=item_key,
                            component_key=component_key,
                            expected_fid=expected_fid,
                            reason=reason,
                            row=rows[0],
                            outcome=outcome,
                        )
                        message = (
                            "curation 오링크 해소 상태를 재검증했다: "
                            f"{payload['place_name']} — {reason}"
                        )
                        payload_json = json.dumps(payload, ensure_ascii=False)
                        if existing is None:
                            issue_id = await conn.fetchval(  # type: ignore[attr-defined]
                                _INSERT_FINDING_SQL,
                                collection_key,
                                message,
                                payload_json,
                            )
                            how = "신규 finding 재구성"
                        else:
                            issue_id = await conn.fetchval(  # type: ignore[attr-defined]
                                _UPDATE_FINDING_SQL,
                                existing,
                                message,
                                payload_json,
                                collection_key,
                            )
                            how = "기존 finding resolved 정규화"
                        print(
                            f"    finding={issue_id} ({how}, resolved)"
                        )
                        emitted += 1
                continue

            payload = _finding_payload(
                collection_key=collection_key,
                item_key=item_key,
                component_key=component_key,
                expected_fid=expected_fid,
                reason=reason,
                row=targets[0],
                outcome="unlinked",
            )
            message = f"curation 링크가 다른 지역을 가리킨다: {payload['place_name']} — {reason}"

            for row in targets:
                print(
                    f"  대상 {item_key}/{component_key} ({row['place_name']}) → "
                    f"{row['feature_name']} | {row['feature_addr'][:44]}"
                )
                payload.setdefault("unlinked_features", [])
                payload["unlinked_features"].append(  # type: ignore[union-attr]
                    {
                        "feature_id": expected_fid,
                        "feature_name": row["feature_name"],
                        "feature_address": row["feature_addr"],
                    }
                )

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

                if not apply:
                    print("    (dry-run) unlink 예정")
                    unlinked += 1
                    continue

                done = await conn.fetchval(  # type: ignore[attr-defined]
                    _UNLINK_SQL,
                    row["curation_item_id"],
                    json.dumps(meta, ensure_ascii=False),
                    expected_fid,
                )
                if done is None:
                    raise RuntimeError(
                        f"{item_key}: row lock 뒤 guarded UPDATE가 0행이다"
                    )
                print("    unlink 완료")
                unlinked += 1

            if not apply:
                print("    (dry-run) finding resolved 기록 예정")
                emitted += 1
                continue

            payload_json = json.dumps(payload, ensure_ascii=False)
            await conn.fetchval(_LOCK_FINDING_SQL, payload["dedupe_key"])  # type: ignore[attr-defined]
            existing = await conn.fetchval(  # type: ignore[attr-defined]
                _FIND_EXISTING_SQL,
                [
                    payload["dedupe_key"],
                    f"curation_mislink:{collection_key}:{item_key}",
                ],
            )
            if existing is None:
                issue_id = await conn.fetchval(  # type: ignore[attr-defined]
                    _INSERT_FINDING_SQL, collection_key, message, payload_json
                )
                how = "신규"
            else:
                issue_id = await conn.fetchval(  # type: ignore[attr-defined]
                    _UPDATE_FINDING_SQL,
                    existing,
                    message,
                    payload_json,
                    collection_key,
                )
                how = "갱신"
            finding_result = (str(issue_id), how)
            emitted += 1

        if finding_result is not None:
            issue_id, how = finding_result
            print(f"    finding={issue_id} ({how}, resolved)")

    verb = "해제" if apply else "해제 예정"
    print(
        f"\n{verb} {unlinked}행 / 이미 해제 {already}건 / 가드 {guarded}건 / "
        f"finding {emitted}건(resolved)"
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다 (기본은 dry-run)")
    args = ap.parse_args()

    dsn = os.environ["DSN"].replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        await run(conn, apply=args.apply)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
