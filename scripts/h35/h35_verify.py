"""T-VN-H35 배포 후 실증. 읽기 전용. 범위 0064~0072.

**반증 가능성**: 각 항목은 배포 전 baseline에서 **다른 값**이 나온다. 이번 사전 검토에서
prod(0063)에 직접 돌려 확인했다. baseline에서도 같은 값이 나오는 항목은 게이트가 아니라
**회귀 감시**로 따로 분류한다 — 그런 걸 통과 근거로 쓰면 배포가 실패해도 통과한다.
"""

import asyncio
import os
import sys

import asyncpg

# (라벨, SQL, 기대값, baseline 실측값)
GATES: list[tuple[str, str, str, str]] = [
    (
        "alembic head",
        "select version_num from alembic_version",
        "0072_curation_provenance",
        "0063_pipeline_root_id",
    ),
    (
        "신규 테이블 10개 (0070·0071·0072)",
        """select count(*)::text from information_schema.tables
            where (table_schema='ops' and table_name in
                   ('domain_commands','domain_command_results','backup_command_executions',
                    'offline_upload_command_executions','integrity_observation_scopes',
                    'integrity_observation_runs','integrity_finding_observations'))
               or (table_schema='feature' and table_name in
                   ('curation_import_batches','curation_import_rows','curation_link_decisions'))""",
        "10",
        "0",
    ),
    (
        "신규 컬럼 3개",
        """select count(*)::text from information_schema.columns
            where (table_schema='ops' and table_name='offline_uploads'
                   and column_name='delete_command_id')
               or (table_schema='feature' and table_name='curation_items'
                   and column_name in ('current_import_row_id','accepted_link_decision_id'))""",
        "3",
        "0",
    ),
    (
        "dedupe 인덱스 (0067)",
        """select count(*)::text from pg_indexes
            where schemaname='ops' and indexname='uq_violations_open_dedupe_key'""",
        "1",
        "0",
    ),
    (
        "last_seen_at 컬럼 (0068)",
        """select count(*)::text from information_schema.columns
            where table_schema='ops' and table_name='data_integrity_violations'
              and column_name='last_seen_at'""",
        "1",
        "0",
    ),
    (
        "weather_metric_series (0069)",
        """select count(*)::text from information_schema.tables
            where table_schema='feature' and table_name='weather_metric_series'""",
        "1",
        "0",
    ),
    (
        "append-only 트리거 6개 (0072)",
        """select count(*)::text from pg_trigger
            where not tgisinternal
              and (tgname like 'trg_curation_%_append_only'
                   or tgname like 'trg_curation_%_no_truncate')""",
        "6",
        "0",
    ),
    (
        "invalid 인덱스 없음",
        """select count(*)::text from pg_index i
            join pg_class c on c.oid=i.indexrelid
            join pg_namespace n on n.oid=c.relnamespace
            where not i.indisvalid and n.nspname in ('feature','ops','provider_sync')""",
        "0",
        "0",  # baseline도 0 — 아래 WATCH로 분류하지 않고 게이트로 두되 그 한계를 표기
    ),
    (
        "0072 backfill 정합: decision 없는 링크 0",
        """select count(*)::text from feature.curation_items
            where feature_id is not null and accepted_link_decision_id is null""",
        "0",
        "(컬럼 부재)",
    ),
]

# 배포 전에도 같은 값이 나오는 것 — **게이트가 아니다.** 회귀 감시로만 본다.
WATCH: list[tuple[str, str]] = [
    (
        "오링크 3건 미연결 유지 (baseline도 0 — 반증 불가)",
        """select count(*)::text from feature.curation_items
            where external_item_id = any(array['kt100-2023-2024-025','kt100-2025-2026-024',
                                               'kt100-2025-2026-036'])
              and feature_id is not null""",
    ),
    (
        "legacy_unattributed decision 수 (= 링크된 item 수여야 함)",
        """select count(*)::text from feature.curation_link_decisions
            where match_basis='legacy_unattributed'""",
    ),
    (
        "공개 노출 가능 링크 (trusted)",
        """select count(*)::text from feature.curation_items i
            where i.feature_id is not null and i.archived_at is null
              and exists (select 1 from feature.curation_link_decisions d
                           where d.decision_id = i.accepted_link_decision_id
                             and d.decision_kind='accepted'
                             and d.match_basis <> 'legacy_unattributed')""",
    ),
]

# ---------------------------------------------------------------------------
# 공개 표면 게이트 (T-VN-H35 / PR #910 답변 반영)
#
# **이전 게이트는 `GET /v1/curations/collections` 200만 봤다.** 그러면 0072가 공개
# 표면을 3,000건 날려도 **200이 나오므로 통과한다** — "실패해도 통과하는 기준"이다.
# 이 저장소가 반복해 지적받은 그 형태를 내가 다시 만들었다.
#
# 그래서 응답 코드가 아니라 **의미 수치**를 잰다. 임계값은 배포 직전 같은 쿼리로
# 채취한 pre 값이며, 사전에 하드코딩하지 않는다 — 0065의 재정규화·source_present·
# public Feature 상태 필터가 pre 값 자체를 바꾸기 때문이다(#910 답변 지적).
SURFACE: list[tuple[str, str]] = [
    (
        "public item 총계",
        """select count(*)::text from feature.curation_items i
            join feature.curation_collections c on c.collection_id = i.collection_id
            where i.archived_at is null and c.visibility = 'public'""",
    ),
    (
        "public collection 총계",
        """select count(*)::text from feature.curation_collections
            where visibility = 'public' and status = 'published'""",
    ),
    (
        "표본 Feature-group: 국립세종수목원을 담은 curation 수",
        """select count(*)::text from feature.curation_items i
            where i.feature_id = 'f_global_p_2eddbdc1ef5a0c00' and i.archived_at is null""",
    ),
    (
        "link-audit 잔여: decision 없는 링크",
        """select count(*)::text from feature.curation_items
            where feature_id is not null and archived_at is null
              and accepted_link_decision_id is null""",
    ),
    (
        "link-audit 잔여: legacy_unattributed로만 뒷받침된 링크",
        """select count(*)::text from feature.curation_items i
            join feature.curation_link_decisions d
              on d.decision_id = i.accepted_link_decision_id
            where i.archived_at is null and d.match_basis = 'legacy_unattributed'""",
    ),
]


async def main() -> None:
    conn = await asyncpg.connect(os.environ["DSN"])
    failed = 0
    try:
        print("=== 게이트 (배포 전 baseline과 다른 값이 나와야 한다) ===")
        for label, sql, expected, baseline in GATES:
            try:
                got = str(await conn.fetchval(sql))
            except Exception as exc:  # noqa: BLE001
                got = f"(오류: {type(exc).__name__})"
            ok = got == expected
            mark = "OK  " if ok else "★FAIL"
            weak = "  [주의: baseline과 기대값이 같아 반증력이 약하다]"
            note = "" if baseline != expected else weak
            print(f"  {mark} {label}: {got} (기대 {expected} / baseline {baseline}){note}")
            if not ok:
                failed += 1

        print("\n=== 회귀 감시 (게이트 아님 — 값만 기록) ===")
        for label, sql in WATCH:
            try:
                got = str(await conn.fetchval(sql))
            except Exception as exc:  # noqa: BLE001
                got = f"(오류: {type(exc).__name__})"
            print(f"       {label}: {got}")

        # 공개 표면 — 배포 전/후를 **같은 쿼리로** 재서 대조한다. 이 값을 기록해 두지
        # 않으면 "200이니 통과"로 대량 의미 손실을 놓친다.
        print("\n=== 공개 표면 수치 (배포 전/후 대조용 — 반드시 양쪽에서 채취) ===")
        for label, sql in SURFACE:
            try:
                got = str(await conn.fetchval(sql))
            except Exception as exc:  # noqa: BLE001
                got = f"(오류: {type(exc).__name__})"
            print(f"       {label}: {got}")
        print(
            "\n  ⚠ 이 수치는 자동 판정하지 않는다 — 임계값을 하드코딩하면 0065의 재정규화·"
            "source_present·\n"
            "     public Feature 상태 필터 때문에 정상 배포가 실패로 읽힌다.\n"
            "     **배포 직전 같은 스크립트로 pre 값을 채취해 사람이 대조한다.**"
        )
    finally:
        await conn.close()

    print()
    if failed:
        print(f"=== ★ 게이트 {failed}건 실패 ===")
        sys.exit(1)
    print("=== 전 게이트 통과 ===")


asyncio.run(main())
