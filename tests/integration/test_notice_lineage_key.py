"""notice 계보 key 저장 계약 (T-VN-37, ADR-087/088).

이 파일이 있는 이유: 저장 경로가 **한 번도 실행되지 않은 채** 나간 적이 있다.
마이그레이션 backfill만 검증하고 writer를 돌려보지 않아서, 같은 bind 파라미터를
INSERT 값(varchar)과 CASE(text) 양쪽에 써서 생긴 ``AmbiguousParameterError``를
적대 리뷰가 잡을 때까지 몰랐다. 그 오류는 notice뿐 아니라 **모든 provider의 모든
source record 쓰기**를 죽인다.

계보 key의 정본은 **DB**에 있고, T-VN-33이 그 자리를 record에서
``provider_sync.source_entity_heads``로 옮겼다: ``provider_sync.notice_lineage_key``
함수를 BEFORE INSERT/UPDATE 트리거가 호출해 head의 컬럼을 채우고, 애플리케이션은
그 컬럼을 읽기만 한다. 고정하는 것:

1. writer가 ``lineage_key``를 **주지 않아도** 트리거가 채운다.
2. KREX/KMA 전용 계보 규칙과 그 밖의 fallback이 각각 맞는 값을 만든다.
3. DB 정본 == 애플리케이션이 H35 고정 세대 replay에 쓰는 재계산 식. 갈리면
   리허설이 재생하는 표면이 현행 표면과 다른 계보로 묶인다. 값이 *틀린* 경우는
   NULL과 달리 fallback으로 막을 수 없다(값은 write-once다).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto.source import SourceRecord
from kortravelmap.infra import feature_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 8, 6, 12, 0, tzinfo=_KST)

# T-VN-33 이후 provider/dataset pair는 catalog에 있어야 writer가 resolve한다.
# notice 규칙 **밖**의 scope 대표로 실제 seed된 MOIS pair를 쓴다.
_NON_NOTICE_DATASET = "mois_license_features_bulk"


async def _lineage_of(session: AsyncSession, *, entity_id: str) -> str:
    """entity의 현재 head가 들고 있는 계보 key."""
    return (
        await session.execute(
            text(
                "SELECT head.lineage_key"
                " FROM provider_sync.source_entity_heads AS head"
                " JOIN provider_sync.source_entities AS entity"
                "   ON entity.source_entity_key = head.source_entity_key"
                " WHERE entity.source_entity_id = :i"
            ),
            {"i": entity_id},
        )
    ).scalar_one()


async def _insert_record(
    session: AsyncSession,
    *,
    key: str,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    raw_data: dict[str, Any],
    observed_at: datetime = _NOW,
) -> str:
    """프로덕션 writer를 **그대로** 실행하고 트리거가 넣은 계보 key를 읽는다."""
    entity_id = f"ENT-{key}"
    payload_hash = make_payload_hash(raw_data)
    await feature_repo.upsert_source_record(
        session,
        SourceRecord(
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=source_entity_type,
            source_entity_id=entity_id,
            raw_data=raw_data,
            raw_payload_hash=payload_hash,
            fetched_at=observed_at,
            imported_at=observed_at,
            source_record_key=make_source_record_key(
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
                source_entity_id=entity_id,
                raw_payload_hash=payload_hash,
            ),
        ),
    )
    return await _lineage_of(session, entity_id=entity_id)


@pytest.mark.parametrize(
    ("label", "provider", "dataset_key", "source_entity_type", "raw_data", "expected"),
    [
        (
            "krex",
            "python-krex-api",
            "krex_traffic_notices",
            "traffic_notice",
            {"occurred_date": "2026-08-01", "route_no": "1", "point_name": "p"},
            "2026-08-01::1::p",
        ),
        (
            # 대소문자·공백 정규화가 계보를 가른다 — 같은 사건이 두 계보가 되면
            # 밀려난 공지가 되살아난다.
            "krex-normalized",
            "python-krex-api",
            "krex_traffic_notices",
            "traffic_notice",
            {"occurred_date": " 2026-08-01 ", "route_no": "AB", "point_name": "Foo Bar"},
            "2026-08-01::ab::foo bar",
        ),
        (
            "kma-phenomenon",
            "python-kma-api",
            "kma_weather_alerts",
            "weather_alert",
            {"region_code": "L1010000", "phenomenon": "호우"},
            "L1010000::호우",
        ),
        (
            # phenomenon이 없으면 alert_type으로 물러난다. 이 분기는 prod 데이터에
            # KMA 특보가 아직 0행이라 실데이터로는 한 번도 실행된 적이 없다.
            "kma-alert-type-fallback",
            "python-kma-api",
            "kma_weather_alerts",
            "weather_alert",
            {"region_code": "L1010000", "alert_type": "강풍"},
            "L1010000::강풍",
        ),
        (
            # notice 전용 규칙이 없는 scope도 **값을 갖는다**. T-VN-33 이후 head는
            # 유효 계보를 통째로 물화한다 — 읽는 쪽이
            # COALESCE(head.lineage_key, entity.source_entity_id)로 물러나면 두
            # 테이블에 걸친 식이 되어 어떤 단일 인덱스도 받지 못한다.
            "non-notice",
            "python-mois-api",
            _NON_NOTICE_DATASET,
            "license_place",
            {"a": 1},
            "ENT-lin-non-notice",
        ),
        (
            # 계보 구성요소가 전부 비면 entity id로 물러난다.
            "krex-empty",
            "python-krex-api",
            "krex_traffic_notices",
            "traffic_notice",
            {"occurred_date": "  ", "route_no": ""},
            "ENT-lin-krex-empty",
        ),
    ],
)
async def test_writer_stores_lineage_key(
    migrated_session: AsyncSession,
    label: str,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    raw_data: dict[str, Any],
    expected: str,
) -> None:
    """writer가 실제로 실행되고, 트리거가 모든 scope에 맞는 계보 key를 남긴다."""
    stored = await _insert_record(
        migrated_session,
        key=f"lin-{label}",
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        raw_data=raw_data,
    )
    assert stored == expected


async def test_writer_does_not_supply_lineage_key(
    migrated_session: AsyncSession,
) -> None:
    """writer SQL은 ``lineage_key``를 쓰지 않는다 — 파생의 정본은 DB다.

    애플리케이션이 값을 넣기 시작하면 DB 함수와 갈릴 수 있고, 그 불일치는 어떤
    제약도 잡아주지 못한다. record writer뿐 아니라 컬럼이 실제로 사는 **head**
    writer도 마찬가지여야 한다.
    """
    assert "lineage_key" not in feature_repo._UPSERT_SOURCE_RECORD_SQL
    assert "lineage_key" not in feature_repo._UPSERT_SOURCE_ENTITY_HEAD_SQL


async def test_lineage_index_matches_the_read_expression(
    migrated_session: AsyncSession,
) -> None:
    """인덱스 식이 read 식과 다르면 인덱스가 **쓰이지 않는다** (ADR-087/088)."""
    definition = (
        await migrated_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes"
                " WHERE schemaname = 'provider_sync'"
                "   AND indexname = 'idx_source_entity_heads_lineage'"
            )
        )
    ).scalar_one()
    # 유효 계보가 컬럼 **하나로** 물화돼 있어야 단일 인덱스가 read를 받는다.
    assert "(lineage_key," in definition
    assert "COALESCE" not in definition
    assert feature_repo._lineage_sql("h", entity_alias="e") == "h.lineage_key"
    # 순서 두 열이 **이 순서로, DESC**여야 한다. 계보에서 실제로 경쟁하는 행은
    # entity당 current head 하나뿐이고 그것이 그 계보의 observed_at 최댓값이라,
    # ASC면 패자의 스캔 범위 맨 끝에 놓여 EXISTS가 이력을 전부 소비한다.
    # 부분 문자열 검사로는 순서도 방향도 못 잡는다.
    tail = definition[definition.index("(lineage_key,") :]
    assert "observed_at DESC" in tail
    assert tail.index("observed_at DESC") < tail.index("current_source_record_key DESC")


async def test_lineage_trigger_is_enable_always(
    migrated_session: AsyncSession,
) -> None:
    """``session_replication_role = replica``에서도 파생이 돌아야 한다.

    백업 복원 드릴이 fence 우회에 그 role을 쓴다 — 기본 ``ENABLE ORIGIN``이면
    그 세션의 쓰기에서 계보 파생이 통째로 빠진다.
    """
    enabled = (
        await migrated_session.execute(
            text(
                "SELECT tgenabled::text FROM pg_trigger"
                " WHERE tgname = 'trg_source_entity_head_lineage_key'"
            )
        )
    ).scalar_one()
    assert enabled == "A"


async def test_head_advance_recomputes_lineage_key(
    migrated_session: AsyncSession,
) -> None:
    """payload가 바뀌면 계보도 따라간다 — 값이 낡은 채 남지 않는다.

    T-VN-33 이후 record는 immutable이라 payload 변경은 **새 record**가 되고 head가
    그쪽으로 전진한다. 그 전진에서 계보를 다시 계산하지 않으면 head는 옛 계보를
    든 채로 남는다 — 트리거의 ``UPDATE OF``에 ``current_source_record_key``가 빠지면
    실제로 그렇게 된다.
    """
    first = await _insert_record(
        migrated_session,
        key="lin-repay",
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        raw_data={"occurred_date": "2026-08-03", "route_no": "7"},
    )
    assert first == "2026-08-03::7"
    updated = await _insert_record(
        migrated_session,
        key="lin-repay",
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        raw_data={"occurred_date": "2026-08-04", "route_no": "8"},
        observed_at=_NOW + timedelta(hours=1),
    )
    assert updated == "2026-08-04::8"


async def test_direct_write_to_lineage_key_is_corrected(
    migrated_session: AsyncSession,
) -> None:
    """파생 컬럼을 **직접** 써도 트리거가 되돌린다.

    트리거의 ``UPDATE OF`` 목록에 ``lineage_key`` 자신이 없으면 이 문장이 트리거를
    타지 않아 거짓 값이 그대로 남고, 밀려난 공지가 공개 표면에 되살아난다.
    NOT NULL은 "비어 있지 않다"만 보장하지 "맞다"를 보장하지 않는다.
    """
    await _insert_record(
        migrated_session,
        key="lin-tamper",
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        raw_data={"occurred_date": "2026-08-05", "route_no": "3"},
    )
    await migrated_session.execute(
        text(
            "UPDATE provider_sync.source_entity_heads AS head"
            " SET lineage_key = 'TAMPERED'"
            " FROM provider_sync.source_entities AS entity"
            " WHERE entity.source_entity_key = head.source_entity_key"
            "   AND entity.source_entity_id = :i"
        ),
        {"i": "ENT-lin-tamper"},
    )
    stored = await _lineage_of(migrated_session, entity_id="ENT-lin-tamper")
    assert stored == "2026-08-05::3"


async def test_production_upsert_preserves_the_derived_value(
    migrated_session: AsyncSession,
) -> None:
    """재관측(같은 payload 재적재)이 계보를 망가뜨리지 않는다.

    프로덕션 head 문장은 ``INSERT ... ON CONFLICT (source_entity_key) DO UPDATE``이고
    충돌해도 BEFORE INSERT arm이 돈다 — 그래서 "트리거를 안 탄다"가 아니라
    "값이 그대로다"를 고정한다. 여기서 값이 흔들리면 폴링마다 계보가 바뀐다.
    """
    first = await _insert_record(
        migrated_session,
        key="lin-hot",
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        raw_data={"occurred_date": "2026-08-06", "route_no": "4"},
    )
    second = await _insert_record(
        migrated_session,
        key="lin-hot",
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        raw_data={"occurred_date": "2026-08-06", "route_no": "4"},
        observed_at=_NOW + timedelta(hours=1),
    )
    assert first == second == "2026-08-06::4"


async def test_trigger_watches_exactly_the_lineage_inputs(
    migrated_session: AsyncSession,
) -> None:
    """``UPDATE OF`` 목록 == {현재 record 포인터, 파생 컬럼 자신}.

    ``observed_at``만 전진하는 재관측 UPDATE는 계보 입력이 아니다 — 목록에 들어가면
    폴링마다 head 전 행에서 함수가 도는데, 그 함수는 entity·dataset·record 3-join이다.
    반대로 ``current_source_record_key``가 빠지면 payload 교체가 계보를 낡은 채 남긴다.
    """
    watched = {
        row[0]
        for row in (
            await migrated_session.execute(
                text(
                    "SELECT event_object_column"
                    " FROM information_schema.triggered_update_columns"
                    " WHERE trigger_schema = 'provider_sync'"
                    "   AND trigger_name = 'trg_source_entity_head_lineage_key'"
                )
            )
        ).all()
    }
    assert watched == {"current_source_record_key", "lineage_key"}


async def test_db_lineage_function_matches_frozen_replay_expression(
    migrated_session: AsyncSession,
) -> None:
    """DB 정본 == H35 고정 세대 replay가 쓰는 재계산 식 (전 행 대조).

    replay는 컬럼이 없던 0079 세대를 재생하므로 애플리케이션 식을 쓴다. 두 벌이
    갈리면 리허설이 재생하는 표면이 현행 표면과 다른 계보로 묶인다.
    """
    for label, provider, dataset_key, entity_type, raw in (
        (
            "k",
            "python-krex-api",
            "krex_traffic_notices",
            "traffic_notice",
            {"occurred_date": "2026-08-02", "route_no": "9", "direction": "북"},
        ),
        (
            "w",
            "python-kma-api",
            "kma_weather_alerts",
            "weather_alert",
            {"region_code": "L1010000", "alert_type": "강풍"},
        ),
        ("o", "python-mois-api", _NON_NOTICE_DATASET, "license_place", {}),
    ):
        await _insert_record(
            migrated_session,
            key=f"lin-fn-{label}",
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=entity_type,
            raw_data=raw,
        )
    recomputed_sql = feature_repo._notice_lineage_sql(
        "record", entity_alias="entity", dataset_alias="dataset"
    )
    total, mismatched = (
        await migrated_session.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE"
                "   provider_sync.notice_lineage_key(head)"
                f"     IS DISTINCT FROM ({recomputed_sql})"
                "   OR head.lineage_key"
                "     IS DISTINCT FROM provider_sync.notice_lineage_key(head))"
                " FROM provider_sync.source_entity_heads AS head"
                " JOIN provider_sync.source_entities AS entity"
                "   ON entity.source_entity_key = head.source_entity_key"
                " JOIN provider_sync.provider_datasets AS dataset"
                "   ON dataset.provider_dataset_id = entity.provider_dataset_id"
                " JOIN provider_sync.source_records AS record"
                "   ON record.source_record_key = head.current_source_record_key"
            )
        )
    ).one()
    assert total > 0, "대조할 record가 없으면 이 테스트는 공허하다"
    assert mismatched == 0
