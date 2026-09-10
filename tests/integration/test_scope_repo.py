"""``infra.scope_repo`` feature update request scope resolver 통합 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Final

import pytest
from sqlalchemy import text

from kortravelmap.dto import SourceRecord
from kortravelmap.infra import feature_repo, scope_repo
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)

#: 존재하지 않는 Feature를 가리키는 well-formed UUIDv7.
#:
#: T-VN-39 재키 뒤 resolver는 요청 id를 ``unnest(CAST(:feature_ids AS uuid[]))``로 받는다.
#: 예전에 쓰던 ``"missing"`` 같은 문자열은 이제 "없는 id"가 아니라 22P02다 — "모르는
#: id는 조용히 빠진다"를 재려면 **형태는 옳고 행만 없어야** 한다. 그래서 상수로 둔다:
#: 우연히 존재할 수 있는 값을 그때그때 만들어 쓰면 이 축이 조용히 흔들린다.
_ABSENT_FEATURE_ID: Final[str] = "00000000-0000-7000-8000-00005c09e001"

_REFRESH_MEMBERSHIP_SQL = """
SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
FROM provider_sync.provider_dataset_operation_scopes AS scope
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = scope.provider_dataset_id
 AND operation.operation_key = scope.operation_key
 AND operation.operation_kind = scope.operation_kind
WHERE dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND scope.operation_kind = 'refresh'
  AND (
      CAST(:sync_scope AS text) IS NULL
      OR scope.sync_scope = CAST(:sync_scope AS text)
  )
  AND dataset.is_active
  AND operation.is_enabled
ORDER BY scope.sync_scope, scope.operation_key
LIMIT 1
"""


async def _refresh_membership(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str | None = None,
) -> tuple[int, str, str]:
    """catalog에서 활성 refresh membership triple을 읽는다.

    T-VN-33 이후 scope identity는 ``provider_dataset_id + sync_scope +
    operation_key``다 — 자연키 pair는 표시용 projection일 뿐이라 테스트도
    catalog(0089 seed)에서 실제 triple을 읽어 쓴다.
    """

    row = (
        await session.execute(
            text(_REFRESH_MEMBERSHIP_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
            },
        )
    ).one()
    return int(row.provider_dataset_id), str(row.sync_scope), str(row.operation_key)


@dataclass(frozen=True)
class _Festival:
    """`CulturalFestivalItem` Protocol 만족 — provider 실모델 필드명 (#374)."""

    fstvl_nm: str | None
    opar: str | None = None
    fstvl_start_date: date | None = None
    fstvl_end_date: date | None = None
    fstvl_co: str | None = None
    mnnst_nm: str | None = None
    auspc_instt_nm: str | None = None
    suprt_instt_nm: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    relate_info: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None


async def _bundle(
    seed: str,
    *,
    lon: str = "126.9239",
    lat: str = "37.5263",
    bjd_code: str = "1156011000",
    sigungu_code: str = "11560",
):
    # 자연키는 name::address 파생(#374) — seed를 이름에 넣어 feature 구분.
    # bjd_code/sigungu_code는 변환 입력이 아니라 _load()의 직접 UPDATE 값.
    del bjd_code, sigungu_code
    item = _Festival(
        fstvl_nm=f"스코프 테스트 축제 {seed}",
        opar="테스트 공원",
        fstvl_start_date=date(2026, 4, 5),
        fstvl_end_date=date(2026, 4, 12),
        fstvl_co="scope resolver 테스트용 fixture.",
        mnnst_nm="영등포구청",
        phone_number="02-2670-3114",
        rdnmadr="서울특별시 영등포구 여의공원로 120",
        lnmadr="서울특별시 영등포구 여의도동 8",
        latitude=float(lat),
        longitude=float(lon),
        reference_date=date(2026, 3, 1),
        instt_nm="서울특별시 영등포구",
    )
    return (
        await cultural_festivals_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=_FETCHED,
        )
    )[0]


@dataclass(frozen=True)
class _Loaded:
    """적재된 provider Feature 하나 — 정본 키와 그것을 낳은 원천 기록.

    T-VN-39 재키 뒤 ``feature.features.feature_id``는 서버가 발급한 UUIDv7이고, DTO의
    ``Feature.feature_id``는 provider 라이브러리가 유도한 legacy ``f_*`` **주소**일
    뿐이다(ADR-098). scope resolver는 정본 키만 받고 정본 키만 돌려주므로 테스트도
    bundle이 아니라 적재 결과를 들고 다닌다 — bundle을 그대로 돌려주면
    ``bundle.feature.feature_id``가 어느 축인지 호출부에서 보이지 않는다.
    """

    feature_id: str
    legacy_feature_id: str
    source_record: SourceRecord


async def _canonical_feature_id(session: AsyncSession, legacy_feature_id: str) -> str:
    """provider가 유도한 legacy 주소 ``f_*``에서 정본 키(uuid의 text 표기)로 간다.

    309 재키가 사본 컬럼 ``features.feature_uuid``를 영구히 없앴으므로 legacy 문자열에서
    정본 키로 가는 유일한 입구가 alias 등록부다. ``feature_aliases.alias``는 재키 뒤에도
    text로 남는 세 자리 중 하나라 여기서 text 비교가 맞다. provider 생성 wrapper가 그
    행을 심으므로 provider 경로로 적재한 Feature에만 쓸 수 있다(ADR-098 결정 6) —
    ``test_feature_identity_boundary._canonical_uuid_for_alias``와 같은 규약이다.
    """

    return str(
        (
            await session.execute(
                text(
                    "SELECT CAST(alias_row.feature_id AS text)"
                    " FROM feature.feature_aliases AS alias_row"
                    " WHERE alias_row.alias = :alias"
                    "   AND alias_row.alias_kind = 'legacy_feature_id'"
                ),
                {"alias": legacy_feature_id},
            )
        ).scalar_one()
    )


async def _load(
    session: AsyncSession,
    seed: str,
    **kwargs: str,
) -> _Loaded:
    sigungu_code = kwargs.get("sigungu_code", "11560")
    bjd_code = kwargs.get("bjd_code", "1156011000")
    bundle = await _bundle(seed, **kwargs)
    await feature_repo.load_bundle(session, bundle)
    legacy_feature_id = bundle.feature.feature_id
    feature_id = await _canonical_feature_id(session, legacy_feature_id)
    await session.execute(
        text(
            """
            UPDATE feature.features
            SET sigungu_code = :sigungu_code,
                sido_code = :sido_code,
                legal_dong_code = :bjd_code
            WHERE feature_id = CAST(:feature_id AS uuid)
            """
        ),
        {
            "feature_id": feature_id,
            "sigungu_code": sigungu_code,
            "sido_code": bjd_code[:2],
            "bjd_code": bjd_code,
        },
    )
    await session.flush()
    return _Loaded(
        feature_id=feature_id,
        legacy_feature_id=legacy_feature_id,
        source_record=bundle.source_record,
    )


async def test_resolve_feature_ids_filters_existing_and_preserves_order(
    migrated_session: AsyncSession,
) -> None:
    first = await _load(migrated_session, "SCOPE-ID-1", sigungu_code="11110")
    second = await _load(migrated_session, "SCOPE-ID-2", sigungu_code="11140")

    result = await scope_repo.resolve_feature_ids(
        migrated_session,
        [
            _ABSENT_FEATURE_ID,
            second.feature_id,
            first.feature_id,
            second.feature_id,
        ],
    )

    assert result.feature_ids == (
        second.feature_id,
        first.feature_id,
    )
    assert result.feature_count == 2
    assert result.sigungu_codes == ("11110", "11140")
    assert result.matched_scope()["feature_count"] == 2
    assert result.provider_datasets[0].feature_count == 2


async def test_count_feature_ids_excludes_retired_features_from_provider_counts(
    migrated_session: AsyncSession,
) -> None:
    active = await _load(migrated_session, "SCOPE-ID-COUNT-ACTIVE", sigungu_code="11110")
    retired = await _load(migrated_session, "SCOPE-ID-COUNT-RETIRED", sigungu_code="11140")
    await migrated_session.execute(
        text(
            """
            UPDATE feature.features
            SET lifecycle_state = 'retired',
                publication_state = 'suppressed'
            WHERE feature_id = CAST(:feature_id AS uuid)
            """
        ),
        {"feature_id": retired.feature_id},
    )
    await migrated_session.flush()

    result = await scope_repo.count_features_matching_scope(
        migrated_session,
        {
            "type": "feature_ids",
            "feature_ids": [
                active.feature_id,
                retired.feature_id,
            ],
        },
        preview_limit=10,
    )

    provider_dataset_id, sync_scope, operation_key = await _refresh_membership(
        migrated_session,
        provider=active.source_record.provider,
        dataset_key=active.source_record.dataset_key,
    )

    assert result.feature_ids == (active.feature_id,)
    assert result.feature_count == 1
    assert result.provider_datasets == (
        scope_repo.ProviderDatasetScope(
            provider=active.source_record.provider,
            dataset_key=active.source_record.dataset_key,
            feature_count=1,
            provider_dataset_id=provider_dataset_id,
            sync_scope=sync_scope,
            operation_key=operation_key,
        ),
    )


async def test_resolve_center_radius_uses_coord_5179_distance(
    migrated_session: AsyncSession,
) -> None:
    near = await _load(
        migrated_session,
        "SCOPE-RADIUS-NEAR",
        lon="126.9239",
        lat="37.5263",
        sigungu_code="11560",
    )
    await _load(
        migrated_session,
        "SCOPE-RADIUS-FAR",
        lon="129.0756",
        lat="35.1796",
        bjd_code="2611010100",
        sigungu_code="26110",
    )

    result = await scope_repo.resolve_center_radius(
        migrated_session,
        lon=126.9239,
        lat=37.5263,
        radius_km=1.0,
    )

    assert result.feature_ids == (near.feature_id,)
    assert result.sigungu_codes == ("11560",)
    assert result.matched_scope()["provider_datasets"][0]["feature_count"] == 1


async def test_count_center_radius_uses_limited_preview_and_full_counts(
    migrated_session: AsyncSession,
) -> None:
    loaded = [
        await _load(
            migrated_session,
            f"SCOPE-RADIUS-COUNT-{index}",
            lon="126.9239",
            lat="37.5263",
            sigungu_code="11560",
        )
        for index in range(3)
    ]

    result = await scope_repo.count_features_matching_scope(
        migrated_session,
        {
            "type": "center_radius",
            "center": {"lon": 126.9239, "lat": 37.5263},
            "radius_km": 1.0,
        },
        preview_limit=1,
    )

    provider_dataset_id, sync_scope, operation_key = await _refresh_membership(
        migrated_session,
        provider=loaded[0].source_record.provider,
        dataset_key=loaded[0].source_record.dataset_key,
    )

    assert result.feature_count == 3
    assert len(result.feature_ids) == 1
    assert set(result.feature_ids) <= {row.feature_id for row in loaded}
    assert result.provider_datasets == (
        scope_repo.ProviderDatasetScope(
            provider=loaded[0].source_record.provider,
            dataset_key=loaded[0].source_record.dataset_key,
            feature_count=3,
            provider_dataset_id=provider_dataset_id,
            sync_scope=sync_scope,
            operation_key=operation_key,
        ),
    )
    matched = result.matched_scope()
    assert matched["feature_count"] == 3
    assert matched["feature_preview_count"] == 1
    assert matched["feature_preview_limit"] == 1
    assert matched["feature_preview_truncated"] is True


async def test_resolve_bbox_and_provider_dataset(
    migrated_session: AsyncSession,
) -> None:
    loaded = await _load(migrated_session, "SCOPE-BBOX", sigungu_code="11560")

    bbox = await scope_repo.resolve_bbox(
        migrated_session,
        min_lon=126.8,
        min_lat=37.4,
        max_lon=127.0,
        max_lat=37.7,
    )
    assert loaded.feature_id in bbox.feature_ids

    provider_dataset_id, sync_scope, operation_key = await _refresh_membership(
        migrated_session,
        provider=loaded.source_record.provider,
        dataset_key=loaded.source_record.dataset_key,
    )
    provider_scope = await scope_repo.resolve_provider_dataset(
        migrated_session,
        provider_dataset_id=provider_dataset_id,
        sync_scope=sync_scope,
        operation_key=operation_key,
    )
    assert loaded.feature_id in provider_scope.feature_ids
    assert provider_scope.provider_datasets == (
        scope_repo.ProviderDatasetScope(
            provider=loaded.source_record.provider,
            dataset_key=loaded.source_record.dataset_key,
            feature_count=1,
            provider_dataset_id=provider_dataset_id,
            sync_scope=sync_scope,
            operation_key=operation_key,
        ),
    )


async def test_count_provider_dataset_uses_limited_preview_and_full_count(
    migrated_session: AsyncSession,
) -> None:
    loaded = [
        await _load(
            migrated_session,
            f"SCOPE-PROVIDER-COUNT-{index}",
            sigungu_code="11560",
        )
        for index in range(3)
    ]
    provider = loaded[0].source_record.provider
    dataset_key = loaded[0].source_record.dataset_key
    provider_dataset_id, sync_scope, operation_key = await _refresh_membership(
        migrated_session,
        provider=provider,
        dataset_key=dataset_key,
    )

    result = await scope_repo.count_features_matching_scope(
        migrated_session,
        {
            "type": "provider_dataset",
            "provider_dataset_id": provider_dataset_id,
            "sync_scope": sync_scope,
            "operation_key": operation_key,
        },
        preview_limit=1,
    )

    assert result.feature_count == 3
    assert len(result.feature_ids) == 1
    assert set(result.feature_ids) <= {row.feature_id for row in loaded}
    assert result.provider_datasets == (
        scope_repo.ProviderDatasetScope(
            provider=provider,
            dataset_key=dataset_key,
            feature_count=3,
            provider_dataset_id=provider_dataset_id,
            sync_scope=sync_scope,
            operation_key=operation_key,
        ),
    )
    assert result.matched_scope()["feature_preview_truncated"] is True


async def test_count_provider_dataset_surfaces_requested_pair_at_zero_features(
    migrated_session: AsyncSession,
) -> None:
    """primary-source feature가 0건인 membership도 preview는 요청 triple을 노출한다.

    executor와 동일한 WYSIWYG 계약 — 아직 feature가 적재되지 않은 dataset(예:
    ``kma_ultra_short_nowcast``)을 대상으로 update request를 미리보기하면
    ``matched_scope.provider_datasets``에 요청한 canonical membership
    (``provider_dataset_id + sync_scope + operation_key``)이 ``feature_count=0``으로
    포함되어야 한다(preview == execute; UI preview 결과가 execute 대상 membership을
    그대로 노출). ``dataset_wide``가 아닌 ``target_grids`` scope를 골라 요청한
    ``sync_scope``가 그대로 반향되는지도 함께 고정한다.
    """
    provider_dataset_id, sync_scope, operation_key = await _refresh_membership(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_ultra_short_nowcast",
        sync_scope="target_grids",
    )

    result = await scope_repo.count_features_matching_scope(
        migrated_session,
        {
            "type": "provider_dataset",
            "provider_dataset_id": provider_dataset_id,
            "sync_scope": sync_scope,
            "operation_key": operation_key,
        },
        preview_limit=5,
    )

    assert sync_scope == "target_grids"
    assert result.feature_count == 0
    assert result.feature_ids == ()
    assert result.provider_datasets == (
        scope_repo.ProviderDatasetScope(
            provider="python-kma-api",
            dataset_key="kma_ultra_short_nowcast",
            feature_count=0,
            provider_dataset_id=provider_dataset_id,
            sync_scope=sync_scope,
            operation_key=operation_key,
        ),
    )
    assert result.matched_scope()["provider_datasets"] == [
        {
            "provider_dataset_id": provider_dataset_id,
            "sync_scope": sync_scope,
            "operation_key": operation_key,
            "provider": "python-kma-api",
            "dataset_key": "kma_ultra_short_nowcast",
            "feature_count": 0,
        }
    ]


async def test_resolve_sigungu_by_radius_uses_injected_kraddr_resolver(
    migrated_session: AsyncSession,
) -> None:
    included = await _load(
        migrated_session,
        "SCOPE-SIGUNGU-IN",
        bjd_code="1114010100",
        sigungu_code="11140",
    )
    await _load(
        migrated_session,
        "SCOPE-SIGUNGU-OUT",
        bjd_code="1111010100",
        sigungu_code="11110",
    )
    seen: list[dict[str, float]] = []

    async def resolver(*, lon: float, lat: float, radius_km: float) -> tuple[str, ...]:
        seen.append({"lon": lon, "lat": lat, "radius_km": radius_km})
        return ("11140", "99999", "11140")

    result = await scope_repo.resolve_sigungu_by_radius(
        migrated_session,
        lon=126.978,
        lat=37.5665,
        radius_km=3.0,
        sigungu_resolver=resolver,
    )

    assert seen == [{"lon": 126.978, "lat": 37.5665, "radius_km": 3.0}]
    assert result.feature_ids == (included.feature_id,)
    assert result.sigungu_codes == ("11140",)


async def test_count_features_matching_scope_dispatches(
    migrated_session: AsyncSession,
) -> None:
    loaded = await _load(migrated_session, "SCOPE-DISPATCH", sigungu_code="11560")

    result = await scope_repo.count_features_matching_scope(
        migrated_session,
        {"type": "feature_ids", "feature_ids": [loaded.feature_id]},
    )
    assert result.feature_count == 1

    with pytest.raises(ValueError, match="unsupported scope type"):
        await scope_repo.count_features_matching_scope(
            migrated_session,
            {"type": "unknown"},
        )


async def test_count_sigungu_scope_requires_resolver(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="requires sigungu_resolver"):
        await scope_repo.count_features_matching_scope(
            migrated_session,
            {
                "type": "sigungu_by_radius",
                "center": {"lon": 126.978, "lat": 37.5665},
                "radius_km": 3.0,
            },
        )


async def test_resolve_cache_target_keys_uses_active_targets(
    migrated_session: AsyncSession,
) -> None:
    near = await _load(
        migrated_session,
        "SCOPE-TARGET-NEAR",
        lon="126.9780",
        lat="37.5665",
        sigungu_code="11140",
    )
    await _load(
        migrated_session,
        "SCOPE-TARGET-FAR",
        lon="129.0756",
        lat="35.1796",
        bjd_code="2611010100",
        sigungu_code="26110",
    )
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="external-app",
        target_key="poi-1",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    await upsert_poi_cache_target(
        migrated_session,
        external_system="external-app",
        target_key="poi-disabled",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
        update_enabled=False,
    )

    result = await scope_repo.resolve_cache_target_keys(
        migrated_session,
        external_system="external-app",
        target_keys=["poi-1", "missing", "poi-disabled"],
    )

    assert result.feature_ids == (near.feature_id,)
    assert result.cache_targets[0].target_id == target.target_id
    assert result.cache_target_matches[0].target_id == target.target_id
    assert result.cache_target_matches[0].relation == "within_radius"
    assert result.matched_scope()["target_count"] == 3
    assert result.matched_scope()["active_target_count"] == 1
    assert result.matched_scope()["skipped_missing_keys"] == ["missing"]
    assert result.matched_scope()["skipped_disabled_keys"] == ["poi-disabled"]


# --------------------------------------------------------------------------- #
# active dataset / enabled operation 가드 (T-VN-33)
#
# scope resolver는 feature를 찾는 일과 "그 feature를 어느 refresh membership이
# 갱신할 수 있는가"를 분리한다. 후자의 활성 술어가 사라지면 비활성 dataset이나
# disabled operation이 request의 실행 대상 목록에 그대로 실린다 — 아래 회귀가
# 없으면 그 술어를 전부 지워도 이 파일은 통과한다.
# --------------------------------------------------------------------------- #


async def _deactivate_membership(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    operation_key: str,
    axis: str,
) -> None:
    if axis == "dataset":
        statement = """
            UPDATE provider_sync.provider_datasets
            SET is_active = false
            WHERE provider_dataset_id = :provider_dataset_id
        """
        params: dict[str, object] = {"provider_dataset_id": provider_dataset_id}
    else:
        statement = """
            UPDATE provider_sync.provider_dataset_operations
            SET is_enabled = false
            WHERE provider_dataset_id = :provider_dataset_id
              AND operation_key = :operation_key
              AND operation_kind = 'refresh'
        """
        params = {
            "provider_dataset_id": provider_dataset_id,
            "operation_key": operation_key,
        }
    result = await session.execute(text(statement), params)
    assert result.rowcount == 1
    await session.flush()


@pytest.mark.parametrize("axis", ["dataset", "operation"])
async def test_matched_provider_datasets_exclude_deactivated_membership(
    migrated_session: AsyncSession,
    axis: str,
) -> None:
    """feature는 그대로 잡히되 refresh membership 목록에서만 빠진다.

    네 갈래 projection SQL(feature_ids / center_radius / bbox / sigungu_codes)이
    같은 술어를 각자 들고 있어 한 갈래만 검증하면 나머지 셋이 무방비다.
    """
    loaded = await _load(migrated_session, f"SCOPE-GUARD-{axis}", sigungu_code="11560")
    feature_id = loaded.feature_id
    provider_dataset_id, _sync_scope, operation_key = await _refresh_membership(
        migrated_session,
        provider=loaded.source_record.provider,
        dataset_key=loaded.source_record.dataset_key,
    )

    before = await scope_repo.resolve_feature_ids(migrated_session, [feature_id])
    assert [scope.provider_dataset_id for scope in before.provider_datasets] == [
        provider_dataset_id
    ]

    await _deactivate_membership(
        migrated_session,
        provider_dataset_id=provider_dataset_id,
        operation_key=operation_key,
        axis=axis,
    )

    by_ids = await scope_repo.resolve_feature_ids(migrated_session, [feature_id])
    assert by_ids.feature_ids == (feature_id,)
    assert by_ids.provider_datasets == ()

    async def _sigungu_resolver(*, lon: float, lat: float, radius_km: float) -> tuple[str, ...]:
        del lon, lat, radius_km
        return ("11560",)

    for scope_payload in (
        {
            "type": "center_radius",
            "center": {"lon": 126.9239, "lat": 37.5263},
            "radius_km": 1.0,
        },
        {
            "type": "bbox",
            "min_lon": 126.8,
            "min_lat": 37.4,
            "max_lon": 127.0,
            "max_lat": 37.7,
        },
        {
            "type": "sigungu_by_radius",
            "center": {"lon": 126.9239, "lat": 37.5263},
            "radius_km": 1.0,
        },
        {"type": "feature_ids", "feature_ids": [feature_id]},
    ):
        counted = await scope_repo.count_features_matching_scope(
            migrated_session,
            scope_payload,
            sigungu_resolver=_sigungu_resolver,
        )
        assert counted.feature_count >= 1, scope_payload["type"]
        assert counted.provider_datasets == (), scope_payload["type"]
        # 빈 목록은 payload에서 키 자체가 빠진다(``ScopeResolution.matched_scope``).
        assert "provider_datasets" not in counted.matched_scope(), scope_payload["type"]


@pytest.mark.parametrize("axis", ["dataset", "operation"])
async def test_provider_dataset_scope_rejects_deactivated_membership(
    migrated_session: AsyncSession,
    axis: str,
) -> None:
    """direct scope는 비활성 membership을 조용히 빈 결과로 넘기지 않고 거부한다."""
    loaded = await _load(
        migrated_session, f"SCOPE-GUARD-DIRECT-{axis}", sigungu_code="11560"
    )
    provider_dataset_id, sync_scope, operation_key = await _refresh_membership(
        migrated_session,
        provider=loaded.source_record.provider,
        dataset_key=loaded.source_record.dataset_key,
    )
    await _deactivate_membership(
        migrated_session,
        provider_dataset_id=provider_dataset_id,
        operation_key=operation_key,
        axis=axis,
    )

    with pytest.raises(
        ValueError, match="provider_dataset scope does not resolve an active refresh membership"
    ):
        await scope_repo.resolve_provider_dataset(
            migrated_session,
            provider_dataset_id=provider_dataset_id,
            sync_scope=sync_scope,
            operation_key=operation_key,
        )

    with pytest.raises(
        ValueError, match="provider_dataset scope does not resolve an active refresh membership"
    ):
        await scope_repo.count_features_matching_scope(
            migrated_session,
            {
                "type": "provider_dataset",
                "provider_dataset_id": provider_dataset_id,
                "sync_scope": sync_scope,
                "operation_key": operation_key,
            },
        )
