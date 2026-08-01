"""0072/0073 curation link provenance 회귀 (T-VN-H40).

`0072`는 기존 link을 전부 `legacy_unattributed`로 이관하는데 공개 표면은 그 근거를
신뢰하지 않는다. 격리 restore clone 실측에서 배포 후 공개 노출 가능 link이
**3,266 → 0**이 됐다. `0073`이 두 가지를 고친다:

1. **일회성** — 근거가 실재하는 concierge projection link을 `source_rule`로 승격
2. **지속** — 앞으로 만들어지는 projection link에도 같은 근거를 붙인다

여기서 고정하는 축:

- 승격 조건을 만족하는 link은 공개 표면에 **보인다** (H40의 본 문제)
- 조건을 만족하지 못하면 **승격하지 않는다** (`0072`의 fail-close 유지)
- 같은 link을 반복 갱신해도 decision이 **쌓이지 않는다** (`0067` dedupe 계열 사고)
- link 대상이 바뀌면 새 decision이 **직전 것을 잇는다** (이력 단절 없음)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from alembic import command
from kortravelmap.infra.curation_link_basis import trusted_basis_sql
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_PRE_REVISION = "0072_curation_provenance"
_TARGET_REVISION = "0074_curation_item_rekey_cascade"

_SOURCE_KEY = "h40:sr:concierge-001"
_SOURCE_KEY_ALT = "h40:sr:concierge-002"
_PROVIDER = "kor-travel-concierge-youtube"
_DATASET = "youtube_place_candidates"  # `0031`이 심어 둔 concierge curated_source
_FEATURE = "feature:h40-primary"
_FEATURE_ALT = "feature:h40-alternate"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _fresh_database(pg_container: Any) -> str:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"curation_provenance_{uuid4().hex}"
    admin_engine = make_async_engine(admin_dsn)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'CREATE DATABASE "{database}"'))
    finally:
        await admin_engine.dispose()
    return make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)


_SEED_SQL = """
INSERT INTO feature.features (feature_id, kind, name, category, detail, status)
VALUES
    (:feature, 'place', 'H40 기본 장소', '01070100', '{}'::jsonb, 'active'),
    (:feature_alt, 'place', 'H40 대체 장소', '01070100', '{}'::jsonb, 'active');

INSERT INTO provider_sync.source_entities (
    source_entity_key, provider, dataset_key,
    source_entity_type, source_entity_id, first_seen_at, last_seen_at
)
VALUES
    ('h40:se:001', :provider, :dataset, 'place', 'h40-001', now(), now()),
    ('h40:se:002', :provider, :dataset, 'place', 'h40-002', now(), now());

INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, provider, dataset_key,
    source_entity_type, source_entity_id,
    raw_name, raw_data, raw_payload_hash, fetched_at, imported_at
)
VALUES
    (:source_key, 'h40:se:001', :provider, :dataset,
     'place', 'h40-001', 'H40 원본', '{}'::jsonb, 'hash-001', now(), now()),
    (:source_key_alt, 'h40:se:002', :provider, :dataset,
     'place', 'h40-002', 'H40 원본 2', '{}'::jsonb, 'hash-002', now(), now());

INSERT INTO feature.curated_themes (
    theme_slug, theme_name, theme_description, theme_group,
    default_curated, visibility, metadata
) VALUES ('h40-theme', 'H40 테마', '', 'test', false, 'public', '{}'::jsonb);
"""
# concierge curated_source는 `0031`이 이미 심어 둔다. 여기서 또 넣으면
# provider가 둘이 되어 아래 INSERT ... SELECT의 cross join이 2행을 만든다.

_INSERT_PROJECTION_SQL = """
INSERT INTO feature.curated_features (
    theme_id, feature_id, source_id, source_record_key,
    curation_status, selection_origin, content_version, selected_by,
    display_title, display_summary, curation_relation, reuse_policy, metadata
)
SELECT
    theme.theme_id, :feature, source.source_id, :source_key,
    'curated', :selection_origin, :content_version, :selected_by,
    :title, 'H40 설명', 'nearby_option', 'manual_review', '{}'::jsonb
FROM feature.curated_themes AS theme, feature.curated_sources AS source
WHERE theme.theme_slug = 'h40-theme' AND source.provider = :provider
RETURNING curated_feature_id::text
"""

_LINK_STATE_SQL = f"""
SELECT
    item.curation_item_id::text AS curation_item_id,
    item.feature_id,
    decision.decision_id::text AS decision_id,
    decision.match_basis,
    decision.decision_kind,
    decision.resolver_version,
    decision.actor,
    decision.evidence,
    decision.supersedes_decision_id::text AS supersedes_decision_id,
    ({trusted_basis_sql("decision.match_basis")}
     AND decision.decision_kind = 'accepted'
     AND decision.curation_item_id = item.curation_item_id
     AND decision.feature_id = item.feature_id) AS publicly_trusted,
    (
        SELECT count(*)
        FROM feature.curation_link_decisions AS every_decision
        WHERE every_decision.curation_item_id = item.curation_item_id
    ) AS decision_count
FROM feature.curation_items AS item
LEFT JOIN feature.curation_link_decisions AS decision
  ON decision.decision_id = item.accepted_link_decision_id
WHERE COALESCE(item.legacy_projection_id, item.curation_item_id)
      = CAST(:projection_id AS uuid)
"""


async def _seed(engine: AsyncEngine) -> None:
    params = {
        "feature": _FEATURE,
        "feature_alt": _FEATURE_ALT,
        "source_key": _SOURCE_KEY,
        "source_key_alt": _SOURCE_KEY_ALT,
        "provider": _PROVIDER,
        "dataset": _DATASET,
    }
    async with engine.begin() as connection:
        for statement in filter(None, (part.strip() for part in _SEED_SQL.split(";"))):
            await connection.execute(text(statement), params)


async def _insert_projection(
    engine: AsyncEngine,
    *,
    feature: str = _FEATURE,
    selection_origin: str = "source_rule",
    source_key: str | None = _SOURCE_KEY,
    content_version: int = 7,
    selected_by: str | None = "concierge-sync",
    title: str = "H40 projection",
) -> str:
    async with engine.begin() as connection:
        return str(
            (
                await connection.execute(
                    text(_INSERT_PROJECTION_SQL),
                    {
                        "feature": feature,
                        "source_key": source_key,
                        "provider": _PROVIDER,
                        "selection_origin": selection_origin,
                        "content_version": content_version,
                        "selected_by": selected_by,
                        "title": title,
                    },
                )
            ).scalar_one()
        )


async def _link_state(engine: AsyncEngine, projection_id: str) -> Any:
    async with engine.connect() as connection:
        return (
            await connection.execute(text(_LINK_STATE_SQL), {"projection_id": projection_id})
        ).one()


async def test_source_rule_projection_becomes_publicly_trusted(
    pg_container: Any,
) -> None:
    """근거가 실재하는 projection link은 공개 표면이 신뢰한다 — H40의 본 문제."""
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        projection_id = await _insert_projection(engine)
        state = await _link_state(engine, projection_id)

        assert state.decision_id is not None, (
            "projection link에 decision이 붙지 않았다 — 0072 상태 그대로다"
        )
        assert state.match_basis == "source_rule"
        assert state.decision_kind == "accepted"
        assert state.publicly_trusted is True
        assert state.feature_id == _FEATURE
        # 근거는 재구성 가능한 값으로 채워져야 한다. 빈 문자열은 CHECK가 막지만
        # 'unknown' 류로 뭉개는 것은 CHECK가 막지 못하므로 여기서 고정한다.
        assert state.resolver_version == "source-rule-v7"
        assert state.actor == "concierge-sync"
        assert state.evidence["source_record_key"] == _SOURCE_KEY
        assert state.evidence["provider"] == _PROVIDER
        assert state.evidence["dataset_key"] == _DATASET
        assert state.evidence["selection_origin"] == "source_rule"
        assert state.decision_count == 1
    finally:
        await engine.dispose()


async def test_non_source_rule_projection_stays_unattributed(
    pg_container: Any,
) -> None:
    """검증 술어를 통과하지 못하면 승격하지 않는다 — 0072 fail-close 유지."""
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        # prod에 실재하는 경우다(selection_origin 분포: source_rule 3,043 / admin 1).
        projection_id = await _insert_projection(
            engine, selection_origin="admin", title="H40 admin projection"
        )
        state = await _link_state(engine, projection_id)

        assert state.decision_id is None
        assert state.decision_count == 0
    finally:
        await engine.dispose()


async def test_projection_without_source_record_stays_unattributed(
    pg_container: Any,
) -> None:
    """source record가 없으면 근거를 재구성할 수 없다 — 승격하지 않는다."""
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        projection_id = await _insert_projection(
            engine, source_key=None, title="H40 keyless projection"
        )
        state = await _link_state(engine, projection_id)

        assert state.decision_id is None
        assert state.decision_count == 0
    finally:
        await engine.dispose()


async def test_repeated_projection_updates_do_not_accumulate_decisions(
    pg_container: Any,
) -> None:
    """같은 link을 반복 갱신해도 decision은 쌓이지 않는다.

    decision 테이블은 append-only이고 트리거가 매번 발급하면 무한 증식한다
    (`0067` dedupe 사고와 같은 계열). 포인터 UPDATE로 인한 재진입도 여기서 함께 막힌다.
    """
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        projection_id = await _insert_projection(engine)
        first = await _link_state(engine, projection_id)
        assert first.decision_count == 1

        for revision in range(3):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE feature.curated_features "
                        "SET display_summary = :summary, updated_at = clock_timestamp() "
                        "WHERE curated_feature_id = CAST(:projection AS uuid)"
                    ),
                    {"summary": f"개정 {revision}", "projection": projection_id},
                )

        after = await _link_state(engine, projection_id)
        assert after.decision_count == 1, (
            f"갱신 3회에 decision이 {after.decision_count}건으로 늘었다"
        )
        assert after.decision_id == first.decision_id
        assert after.publicly_trusted is True
    finally:
        await engine.dispose()


async def test_backfill_promotes_only_verified_legacy_links(
    pg_container: Any,
) -> None:
    """0072가 이관해 둔 link 중 **검증을 통과한 것만** 승격한다.

    0072 상태를 그대로 만든 뒤 0073을 적용해 before/after를 직접 센다.
    """
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        verified_id = await _insert_projection(engine, title="H40 검증 통과")
        unverified_id = await _insert_projection(
            engine,
            feature=_FEATURE_ALT,
            source_key=_SOURCE_KEY_ALT,
            selection_origin="admin",
            title="H40 검증 실패",
        )

        # 0072 backfill이 기존 행에 한 것과 같은 상태를 만든다.
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    WITH inserted AS (
                        INSERT INTO feature.curation_link_decisions (
                            curation_item_id, feature_id, decision_kind,
                            match_basis, resolver_version, evidence, actor
                        )
                        SELECT item.curation_item_id, item.feature_id, 'accepted',
                               'legacy_unattributed', 'pre-0072-unknown',
                               jsonb_build_object(
                                   'migration', '0072_curation_provenance'
                               ),
                               'migration:0072'
                        FROM feature.curation_items AS item
                        WHERE item.feature_id IS NOT NULL
                          AND item.accepted_link_decision_id IS NULL
                        RETURNING decision_id, curation_item_id
                    )
                    UPDATE feature.curation_items AS item
                       SET accepted_link_decision_id = inserted.decision_id
                      FROM inserted
                     WHERE inserted.curation_item_id = item.curation_item_id
                    """
                )
            )

        before_verified = await _link_state(engine, verified_id)
        before_unverified = await _link_state(engine, unverified_id)
        assert before_verified.match_basis == "legacy_unattributed"
        assert before_verified.publicly_trusted is False, (
            "0072 상태에서 공개 표면이 이 link을 신뢰하면 H40 전제가 틀린 것이다"
        )
        assert before_unverified.match_basis == "legacy_unattributed"

        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
        engine = make_async_engine(dsn)

        after_verified = await _link_state(engine, verified_id)
        after_unverified = await _link_state(engine, unverified_id)

        assert after_verified.match_basis == "source_rule"
        assert after_verified.publicly_trusted is True
        assert after_verified.supersedes_decision_id == before_verified.decision_id, (
            "승격 decision이 직전 결정을 잇지 않아 이력이 끊겼다"
        )
        assert after_verified.evidence["migration"] == "0073_curation_source_rule"
        assert after_verified.decision_count == 2

        assert after_unverified.match_basis == "legacy_unattributed"
        assert after_unverified.publicly_trusted is False
        assert after_unverified.decision_count == 1
    finally:
        await engine.dispose()


async def test_backfill_is_idempotent_on_rerun(pg_container: Any) -> None:
    """0073을 내렸다 다시 올려도 decision이 중복 발급되지 않는다."""
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        projection_id = await _insert_projection(engine)
        assert (await _link_state(engine, projection_id)).decision_count == 1

        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION, downgrade=True)
        engine = make_async_engine(dsn)

        downgraded = await _link_state(engine, projection_id)
        assert downgraded.decision_id is None, "downgrade가 포인터를 되돌리지 않았다"
        async with engine.connect() as connection:
            allowed = (
                await connection.execute(
                    text(
                        # 물리 constraint 이름은 naming convention이 접두사를 겹쳐
                        # 만든다. 이름 대신 정의 내용으로 찾는다.
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid = "
                        "  'feature.curation_link_decisions'::regclass "
                        "  AND contype = 'c' "
                        "  AND pg_get_constraintdef(oid) LIKE '%match_basis%'"
                    )
                )
            ).scalar_one()
        assert "source_rule" not in allowed, "downgrade가 CHECK를 좁히지 않았다"

        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
        engine = make_async_engine(dsn)

        restored = await _link_state(engine, projection_id)
        assert restored.match_basis == "source_rule"
        assert restored.publicly_trusted is True
        assert restored.decision_count == 1, (
            f"재적용으로 decision이 {restored.decision_count}건이 됐다"
        )
    finally:
        await engine.dispose()


_REVOKE_SQL = """
WITH revocation AS (
    INSERT INTO feature.curation_link_decisions (
        curation_item_id, feature_id, decision_kind, match_basis,
        resolver_version, evidence, actor, supersedes_decision_id
    )
    SELECT item.curation_item_id, item.feature_id, 'revoked', 'forward_recovery',
           'feature-merge-v1',
           jsonb_build_object('operation', 'feature_merge_link_retarget'),
           'merge:test', item.accepted_link_decision_id
    FROM feature.curation_items AS item
    WHERE COALESCE(item.legacy_projection_id, item.curation_item_id)
          = CAST(:projection AS uuid)
    RETURNING curation_item_id
)
UPDATE feature.curation_items AS item
   SET accepted_link_decision_id = NULL
  FROM revocation
 WHERE revocation.curation_item_id = item.curation_item_id
"""

_APPEND_FORWARD_RECOVERY_SQL = """
WITH appended AS (
    INSERT INTO feature.curation_link_decisions (
        curation_item_id, feature_id, decision_kind, match_basis,
        resolver_version, evidence, actor, supersedes_decision_id
    )
    SELECT item.curation_item_id, item.feature_id, 'accepted',
           'forward_recovery', 'feature-merge-v1',
           jsonb_build_object('operation', 'feature_merge'),
           'merge:test', item.accepted_link_decision_id
    FROM feature.curation_items AS item
    WHERE COALESCE(item.legacy_projection_id, item.curation_item_id)
          = CAST(:projection AS uuid)
    RETURNING decision_id, curation_item_id
)
UPDATE feature.curation_items AS item
   SET accepted_link_decision_id = appended.decision_id
  FROM appended
 WHERE appended.curation_item_id = item.curation_item_id
"""

_SIMULATE_0072_BACKFILL_SQL = """
WITH inserted AS (
    INSERT INTO feature.curation_link_decisions (
        curation_item_id, feature_id, decision_kind,
        match_basis, resolver_version, evidence, actor
    )
    SELECT item.curation_item_id, item.feature_id, 'accepted',
           'legacy_unattributed', 'pre-0072-unknown',
           jsonb_build_object('migration', '0072_curation_provenance'),
           'migration:0072'
    FROM feature.curation_items AS item
    WHERE item.feature_id IS NOT NULL
      AND item.accepted_link_decision_id IS NULL
    RETURNING decision_id, curation_item_id
)
UPDATE feature.curation_items AS item
   SET accepted_link_decision_id = inserted.decision_id
  FROM inserted
 WHERE inserted.curation_item_id = item.curation_item_id
"""


async def test_trigger_does_not_resurrect_a_revoked_link(pg_container: Any) -> None:
    """merge가 끊은 link을 트리거가 되살리면 안 된다.

    merge는 link을 revoke할 때 revoked decision을 남기고
    `accepted_link_decision_id`를 NULL로 만든다(`merge_repo.py:507-512`).
    포인터가 비었다는 것을 "아무도 판단한 적 없다"로 읽으면, 그 뒤 어떤 갱신에서든
    트리거가 새 `source_rule` 승인을 발급해 그 취소를 덮는다.
    """
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        projection_id = await _insert_projection(engine)
        assert (await _link_state(engine, projection_id)).match_basis == "source_rule"

        async with engine.begin() as connection:
            await connection.execute(text(_REVOKE_SQL), {"projection": projection_id})
        assert (await _link_state(engine, projection_id)).decision_id is None

        # 취소 이후의 평범한 갱신 — 여기서 되살아나면 안 된다.
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE feature.curated_features "
                    "SET display_summary = '취소 이후 갱신', "
                    "    updated_at = clock_timestamp() "
                    "WHERE curated_feature_id = CAST(:projection AS uuid)"
                ),
                {"projection": projection_id},
            )

        after = await _link_state(engine, projection_id)
        assert after.decision_id is None, (
            "취소된 link이 다시 승인됐다 — 운영자 결정이 트리거에 덮였다"
        )
    finally:
        await engine.dispose()


async def test_backfill_does_not_resurrect_a_revoked_link(pg_container: Any) -> None:
    """일회성 backfill도 같은 축을 지켜야 한다.

    승인과 취소를 **한 transaction에서** 쓴다 — merge가 실제로 그렇게 한다. 그러면
    `decided_at`이 `now()`로 같아져 시각으로는 순서가 갈리지 않는다. 판정을
    `ORDER BY decided_at DESC, decision_id DESC`로 하면 v4 UUID가 tie-break를 하게 돼
    결과가 무작위가 된다(이 테스트가 실제로 그렇게 흔들렸다). 최신 결정은 supersedes
    사슬의 머리로 찾아야 한다.
    """
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        projection_id = await _insert_projection(engine)

        # 0072 backfill 상태를 만든 뒤 merge가 그 link을 끊은 상황을 재현한다.
        async with engine.begin() as connection:
            await connection.execute(text(_SIMULATE_0072_BACKFILL_SQL))
            await connection.execute(text(_REVOKE_SQL), {"projection": projection_id})

        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
        engine = make_async_engine(dsn)

        after = await _link_state(engine, projection_id)
        assert after.decision_id is None, "backfill이 취소된 link을 source_rule로 승격했다"
    finally:
        await engine.dispose()


async def test_downgrade_survives_a_supersedes_chain(pg_container: Any) -> None:
    """`source_rule` 결정을 이어받은 결정이 있어도 downgrade가 끝까지 간다.

    `supersedes_decision_id` FK는 ON DELETE RESTRICT다. merge가 `source_rule`
    결정을 이어 `forward_recovery`를 쌓으면, 단순 DELETE는 그 참조에 막혀
    downgrade 전체가 중단된다.
    """
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        projection_id = await _insert_projection(engine)
        state = await _link_state(engine, projection_id)
        assert state.match_basis == "source_rule"

        async with engine.begin() as connection:
            await connection.execute(
                text(_APPEND_FORWARD_RECOVERY_SQL), {"projection": projection_id}
            )
        chained = await _link_state(engine, projection_id)
        assert chained.match_basis == "forward_recovery"
        assert chained.supersedes_decision_id == state.decision_id

        await engine.dispose()
        # 여기서 RESTRICT에 막히면 downgrade가 통째로 실패한다.
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION, downgrade=True)
        engine = make_async_engine(dsn)

        async with engine.connect() as connection:
            leftover = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM feature.curation_link_decisions "
                        "WHERE match_basis = 'source_rule'"
                    )
                )
            ).scalar_one()
        assert leftover == 0, "downgrade가 source_rule 행을 남겼다"

        survivor = await _link_state(engine, projection_id)
        assert survivor.match_basis == "forward_recovery"
        assert survivor.supersedes_decision_id is None, "사슬이 삭제된 결정을 계속 가리킨다"
    finally:
        await engine.dispose()


_MERGE_SEED_SQL = """
INSERT INTO feature.features (feature_id, kind, name, category, detail, status)
VALUES
    (:master, 'place', 'H40 병합 master', '01070100', '{}'::jsonb, 'active'),
    (:loser, 'place', 'H40 병합 loser', '01070100', '{}'::jsonb, 'active');

INSERT INTO provider_sync.source_entities (
    source_entity_key, provider, dataset_key,
    source_entity_type, source_entity_id, first_seen_at, last_seen_at
)
VALUES
    ('h40:se:m', :provider, :dataset, 'place', 'h40-m', now(), now()),
    ('h40:se:l', :provider, :dataset, 'place', 'h40-l', now(), now());

INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, provider, dataset_key,
    source_entity_type, source_entity_id,
    raw_name, raw_data, raw_payload_hash, fetched_at, imported_at
)
VALUES
    (:srk_master, 'h40:se:m', :provider, :dataset, 'place', 'h40-m',
     'master', '{}'::jsonb, 'h-m', now(), now()),
    (:srk_loser, 'h40:se:l', :provider, :dataset, 'place', 'h40-l',
     'loser', '{}'::jsonb, 'h-l', now(), now());

INSERT INTO feature.curated_themes (
    theme_slug, theme_name, theme_description, theme_group,
    default_curated, visibility, metadata
) VALUES ('h40-merge-theme', 'H40 병합 테마', '', 'test', false, 'public', '{}'::jsonb);
"""

# prod와 같은 모양으로 넣는다 — `selection_origin='source_rule'` + 도달 가능한
# `source_record_key`. 기존 merge 픽스처는 전부 `'admin'`이라 0073 트리거가 한 번도
# 돌지 않는다. 그래서 merge 경로의 결함이 전부 green으로 통과했다.
_MERGE_PROJECTION_SQL = """
INSERT INTO feature.curated_features (
    theme_id, feature_id, source_id, source_record_key,
    curation_status, selection_origin, content_version, selected_by,
    display_title, display_summary, curation_relation, reuse_policy, metadata
)
SELECT theme.theme_id, :feature, source.source_id, :source_key,
       'curated', 'source_rule', 3, 'concierge-sync',
       :title, 'H40 병합', 'nearby_option', 'manual_review', '{}'::jsonb
FROM feature.curated_themes AS theme, feature.curated_sources AS source
WHERE theme.theme_slug = 'h40-merge-theme' AND source.provider = :provider
RETURNING curated_feature_id::text
"""


async def test_feature_merge_survives_source_rule_provenance(pg_container: Any) -> None:
    """`source_rule` provenance가 붙은 link을 가진 Feature도 병합할 수 있어야 한다.

    기존 merge 통합 테스트의 curated 픽스처는 **전부** `selection_origin='admin'`이라
    0073 트리거가 merge 경로에서 한 번도 발화하지 않는다. prod는 3,043건이
    `source_rule`이므로, 그 조합은 이 테스트가 생기기 전까지 어느 테스트도 밟지
    않은 채 배포될 뻔했다.

    T-VN-H41(`0074_curation_item_rekey_cascade`)이 고치기 전에는 여기서
    `fk_curation_link_decisions_item` 위반으로 실패했다 — merge의
    legacy-conflict detach가 `curation_item_id`를 재작성하는데 그 FK가
    `ON UPDATE NO ACTION`이었기 때문이다. 이제는:

    - 병합이 예외 없이 끝난다
    - 살아남은 link은 신뢰 근거를 **유지**한다 (포인터가 NULL이 되면 안 된다)
    """
    from kortravelmap.infra.merge_repo import apply_feature_merge

    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    master, loser = "feature:h40-merge-master", "feature:h40-merge-loser"
    try:
        params = {
            "master": master,
            "loser": loser,
            "provider": _PROVIDER,
            "dataset": _DATASET,
            "srk_master": "h40:sr:merge-master",
            "srk_loser": "h40:sr:merge-loser",
        }
        async with engine.begin() as connection:
            for statement in filter(None, (part.strip() for part in _MERGE_SEED_SQL.split(";"))):
                await connection.execute(text(statement), params)
            for feature, key, title in (
                (master, "h40:sr:merge-master", "master projection"),
                (loser, "h40:sr:merge-loser", "loser projection"),
            ):
                await connection.execute(
                    text(_MERGE_PROJECTION_SQL),
                    {
                        "feature": feature,
                        "source_key": key,
                        "provider": _PROVIDER,
                        "title": title,
                    },
                )

        # 두 link 모두 source_rule 근거를 갖고 출발하는지 확인한다.
        async with engine.connect() as connection:
            trusted_before = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM feature.curation_items AS item "
                        "JOIN feature.curation_link_decisions AS d "
                        "  ON d.decision_id = item.accepted_link_decision_id "
                        "WHERE d.match_basis = 'source_rule' "
                        "  AND item.feature_id IN (:master, :loser)"
                    ),
                    {"master": master, "loser": loser},
                )
            ).scalar_one()
        assert trusted_before == 2, (
            f"출발 상태가 prod와 다르다 — source_rule link {trusted_before}건"
        )

        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as session:
            outcome = await apply_feature_merge(
                session,
                master_id=master,
                loser_id=loser,
                merged_by="h40-test",
                reason="H40 provenance 병합 회귀",
            )
            await session.commit()
        assert outcome.master_feature_id == master

        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT item.curation_item_id::text, item.feature_id, "
                        "       d.match_basis, d.decision_kind "
                        "FROM feature.curation_items AS item "
                        "LEFT JOIN feature.curation_link_decisions AS d "
                        "  ON d.decision_id = item.accepted_link_decision_id "
                        "WHERE item.feature_id = :master "
                        "  AND item.archived_at IS NULL "
                        "  AND item.source_present"
                    ),
                    {"master": master},
                )
            ).all()

        assert rows, "병합 후 master에 활성 link이 하나도 남지 않았다"
        orphaned = [r for r in rows if r.match_basis is None]
        assert not orphaned, (
            "병합이 살아남은 link의 신뢰 근거를 지웠다 — "
            f"근거 없는 link {len(orphaned)}건. 공개 표면에서 조용히 사라진다."
        )
        for row in rows:
            assert row.decision_kind == "accepted"
    finally:
        await engine.dispose()


_REKEY_ONE_ITEM_SQL = """
UPDATE feature.curation_items
   SET curation_item_id = CAST(:new_id AS uuid),
       legacy_projection_id = NULL,
       updated_at = now()
 WHERE curation_item_id = CAST(:old_id AS uuid)
"""


async def test_curation_item_rekey_carries_decision_history(pg_container: Any) -> None:
    """T-VN-H41 — item PK 재작성이 decision을 참조 무결성 위반 없이 따라가야 한다.

    merge의 legacy-conflict detach가 실제로 실행하는 것과 같은 모양의 UPDATE를
    직접 재현한다. `apply_feature_merge()`를 통째로 부르는 위 테스트보다 좁게,
    "PK 재작성 그 자체"와 그 캐스케이드만 검증한다 — 이 경로가 바로 append-only
    예외가 통과시켜야 하는 유일한 긍정 사례다.
    """
    from uuid import uuid4

    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        projection_id = await _insert_projection(engine)
        before = await _link_state(engine, projection_id)
        assert before.match_basis == "source_rule"

        new_id = str(uuid4())
        async with engine.begin() as connection:
            await connection.execute(
                text(_REKEY_ONE_ITEM_SQL),
                {"old_id": projection_id, "new_id": new_id},
            )

        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT item.curation_item_id::text, "
                        "       decision.curation_item_id::text AS decision_item_id, "
                        "       decision.match_basis "
                        "FROM feature.curation_items AS item "
                        "LEFT JOIN feature.curation_link_decisions AS decision "
                        "  ON decision.decision_id = item.accepted_link_decision_id "
                        "WHERE item.curation_item_id = CAST(:new_id AS uuid)"
                    ),
                    {"new_id": new_id},
                )
            ).one()
        assert row.curation_item_id == new_id
        assert row.decision_item_id == new_id, (
            "decision이 재작성된 item을 따라가지 않았다 — 캐스케이드가 끊겼다"
        )
        assert row.match_basis == "source_rule"
    finally:
        await engine.dispose()


async def test_append_only_exception_never_widens_beyond_curation_item_id(
    pg_container: Any,
) -> None:
    """append-only 예외는 `curation_item_id` **하나만** 바뀔 때만 통과해야 한다.

    T-VN-H41의 FK CASCADE는 부모 키 재작성을 자식 테이블에 실어 나르기 위해
    append-only 트리거에 예외를 냈다. 그 예외가 넓어지면(다른 컬럼도 같이 바뀌는
    UPDATE까지 통과하거나, 값이 실제로 바뀌지 않은 no-op까지 통과하면)
    `curation_link_decisions`의 append-only 계약이 사실상 무력화된다.

    긍정 사례(진짜 재작성 캐스케이드가 통과하는 것)는
    `test_curation_item_rekey_carries_decision_history`가 이미 증명한다. 여기서는
    **거부돼야 하는** 세 갈래만 고정한다.
    """
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        projection_id = await _insert_projection(engine)
        state = await _link_state(engine, projection_id)
        assert state.decision_id is not None

        # (1) curation_item_id를 같은 값으로 "바꾸는" no-op — 실제로는 안 바뀌었으므로
        #     여전히 거부돼야 한다. 예외가 SET 절의 컬럼 이름(문법)이 아니라 값의
        #     실제 변화(의미)로 판정되는지 확인한다.
        with pytest.raises(Exception, match="append-only"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE feature.curation_link_decisions "
                        "SET curation_item_id = curation_item_id "
                        "WHERE decision_id = CAST(:decision_id AS uuid)"
                    ),
                    {"decision_id": state.decision_id},
                )

        # (2) curation_item_id와 함께 다른 컬럼도 바뀌는 UPDATE — 여전히 거부돼야 한다.
        with pytest.raises(Exception, match="append-only"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE feature.curation_link_decisions "
                        "SET actor = 'attacker-controlled' "
                        "WHERE decision_id = CAST(:decision_id AS uuid)"
                    ),
                    {"decision_id": state.decision_id},
                )

        # (3) 순수 DELETE — 여전히 거부돼야 한다.
        with pytest.raises(Exception, match="append-only"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM feature.curation_link_decisions "
                        "WHERE decision_id = CAST(:decision_id AS uuid)"
                    ),
                    {"decision_id": state.decision_id},
                )
    finally:
        await engine.dispose()


async def test_0074_downgrade_reverts_fk_and_trigger(pg_container: Any) -> None:
    """0074만 내리면 rekey가 다시 막혀야 한다 — downgrade가 반쪽만 되돌리면 안 된다.

    FK는 되돌렸는데 트리거 함수는 그대로 두거나, 그 반대인 상태로 남으면
    관측 불가능한 절반짜리 downgrade가 된다. 0073은 내리지 않아 decision은
    그대로 살아 있는 채로, rekey가 다시 FK 위반으로 막히는지만 본다.
    """
    from uuid import uuid4

    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
    engine = make_async_engine(dsn)
    try:
        await _seed(engine)
        projection_id = await _insert_projection(engine)
        assert (await _link_state(engine, projection_id)).decision_id is not None

        await engine.dispose()
        await asyncio.to_thread(_run_alembic, dsn, "0073_curation_source_rule", downgrade=True)
        engine = make_async_engine(dsn)

        # decision은 그대로 살아 있어야 한다(0073은 안 내렸다) — rekey 시도의 전제.
        state = await _link_state(engine, projection_id)
        assert state.decision_id is not None

        new_id = str(uuid4())
        with pytest.raises(Exception, match="curation_link_decisions"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE feature.curation_items "
                        "SET curation_item_id = CAST(:new_id AS uuid), "
                        "    legacy_projection_id = NULL, updated_at = now() "
                        "WHERE curation_item_id = CAST(:old_id AS uuid)"
                    ),
                    {"old_id": projection_id, "new_id": new_id},
                )
    finally:
        await engine.dispose()
