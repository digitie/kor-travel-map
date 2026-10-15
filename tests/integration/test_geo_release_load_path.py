"""적재 경로의 geo 재해석 — stale·무쓰기·빈 답 가드·override·토큰 조건(ADR-109, T-GR-03).

실제 provider 변환기(``standard_data`` 축제, ``kor_travel_concierge``)에 가짜 역지오코더를 꽂아 "geo
릴리스 A → B"를 흉내 낸다. 같은 payload를 두 번 적재하되 두 번째에는 run 토큰과 geo 답만 바꾼다.

세션은 테스트마다 롤백된다(``migrated_session``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.dto import Address, Coordinate
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra import feature_identity
from kortravelmap.infra.feature_geocode_stamp_repo import get_stamp, upsert_stamps
from kortravelmap.infra.feature_repo import (
    find_unchanged_active_source_entities,
    load_bundles,
)
from kortravelmap.infra.integrity_violation_repo import (
    create_data_integrity_violation,
    find_fresh_open_findings,
)
from kortravelmap.providers.kor_travel_concierge import (
    KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
    KOR_TRAVEL_CONCIERGE_SOURCE_ENTITY_TYPE,
    kor_travel_concierge_items_to_bundles,
)
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto import FeatureBundle

pytestmark = pytest.mark.integration

_FETCHED = datetime(2026, 10, 16, tzinfo=UTC)
VERSION_A = "dv1-" + "a" * 32
VERSION_B = "dv1-" + "b" * 32
TOKEN_A = "dd1-" + "1" * 32
TOKEN_B = "dd1-" + "2" * 32
REF_A = DatasetRef(version_token=VERSION_A, data_token=TOKEN_A)
REF_B = DatasetRef(version_token=VERSION_B, data_token=TOKEN_B)
_REVERSE = GeoApplied(reverse=True, geocode=False)


def _geo(*, road_name_code: str = "115603118001", zipcode: str = "07237") -> Address:
    return Address(
        legal="서울특별시 영등포구 여의도동",
        admin="여의동",
        bjd_code="1156011000",
        admin_dong_code="1156054000",
        sigungu_code="11560",
        sido_code="11",
        road_name_code=road_name_code,
        zipcode=zipcode,
        sido_name="서울특별시",
        sigungu_name="영등포구",
    )


class _FakeReverse:
    """좌표 → 고정 답. ``answer``가 None이면 빈 답(geo 부분장애)."""

    def __init__(self, answer: Address | None) -> None:
        self.answer = answer
        self.calls = 0

    async def __call__(self, coord: Coordinate) -> Address | None:
        self.calls += 1
        return self.answer


@dataclass(frozen=True)
class _Festival:
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


async def _festival(
    seed: str, reverse: _FakeReverse, *, description: str = "축제"
) -> FeatureBundle:
    item = _Festival(
        fstvl_nm="geo 릴리스 축제",
        opar="여의도공원",
        fstvl_start_date=date(2026, 10, 1),
        fstvl_end_date=date(2026, 10, 9),
        fstvl_co=description,
        rdnmadr=f"서울특별시 영등포구 여의공원로 120 ({seed})",
        lnmadr="서울특별시 영등포구 여의도동 8",  # provider 원문 legal — 빈 답에도 남는다
        latitude=37.5263,
        longitude=126.9239,
        reference_date=date(2026, 9, 1),
        instt_nm="서울특별시 영등포구",
    )
    return (
        await cultural_festivals_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=_FETCHED,
            reverse_geocoder=reverse,
        )
    )[0]


def _ctx(ref: DatasetRef | None, *, observed: frozenset[str] = frozenset()) -> GeoLoadContext:
    return GeoLoadContext(geo_applied=_REVERSE, current_dataset=ref, observed_data_tokens=observed)


async def _feature_id(session: AsyncSession, bundle: FeatureBundle) -> str:
    identity = await feature_identity.resolve_feature_identity(session, bundle.feature.feature_id)
    assert identity is not None
    return identity.feature_id


async def _row(session: AsyncSession, feature_id: str) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT row_revision, legal_dong_code, road_name_code, address "
                    "FROM feature.features WHERE feature_id = CAST(:id AS uuid)"
                ),
                {"id": feature_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def _stamp_row(session: AsyncSession, feature_id: str) -> tuple[Any, ...] | None:
    row = (
        await session.execute(
            text(
                "SELECT geo_version_token, geo_data_token, reverse_outcome, stamped_at "
                "FROM feature.feature_geocode_stamps WHERE feature_id = CAST(:id AS uuid)"
            ),
            {"id": feature_id},
        )
    ).first()
    return None if row is None else tuple(row)


async def _load_a(session: AsyncSession, seed: str) -> tuple[FeatureBundle, str]:
    bundle = await _festival(seed, _FakeReverse(_geo()))
    result = await load_bundles(session, [bundle], geo=_ctx(REF_A))
    assert result.geo_stamps_written == 1
    feature_id = await _feature_id(session, bundle)
    stamp = await get_stamp(session, feature_id)
    assert stamp is not None
    assert (stamp.geo_data_token, stamp.reverse_outcome) == (TOKEN_A, "called")
    return bundle, feature_id


async def test_same_values_under_new_token_advance_only_the_stamp(
    migrated_session: AsyncSession,
) -> None:
    _, feature_id = await _load_a(migrated_session, "same-values")
    before = await _row(migrated_session, feature_id)

    again = await _festival("same-values", _FakeReverse(_geo()))
    result = await load_bundles(migrated_session, [again], geo=_ctx(REF_B))

    assert result.geo_stale_unchanged == 1
    assert result.features_updated == 0
    assert (await _row(migrated_session, feature_id))["row_revision"] == before["row_revision"]
    stamp = await get_stamp(migrated_session, feature_id)
    assert stamp is not None
    assert stamp.geo_data_token == TOKEN_B


async def test_only_road_name_code_changed_is_rewritten(migrated_session: AsyncSession) -> None:
    _, feature_id = await _load_a(migrated_session, "road-name-code")
    before = await _row(migrated_session, feature_id)

    again = await _festival("road-name-code", _FakeReverse(_geo(road_name_code="115603118999")))
    result = await load_bundles(migrated_session, [again], geo=_ctx(REF_B))

    after = await _row(migrated_session, feature_id)
    assert result.geo_stale_rewritten == 1
    assert after["row_revision"] == before["row_revision"] + 1
    assert after["road_name_code"] == "115603118999"
    stamp = await get_stamp(migrated_session, feature_id)
    assert stamp is not None
    assert stamp.geo_data_token == TOKEN_B


@pytest.mark.parametrize(
    "ref",
    [None, DatasetRef(version_token=VERSION_B, data_token=None)],
    ids=["none", "no-data-token"],
)
async def test_no_current_token_writes_nothing(
    migrated_session: AsyncSession, ref: DatasetRef | None
) -> None:
    _, feature_id = await _load_a(migrated_session, f"no-token-{ref is None}")
    before_row = await _row(migrated_session, feature_id)
    before_stamp = await _stamp_row(migrated_session, feature_id)

    again = await _festival(
        f"no-token-{ref is None}", _FakeReverse(_geo(road_name_code="115603118999"))
    )
    result = await load_bundles(migrated_session, [again], geo=_ctx(ref))

    assert result.geo_stamps_written == 0
    assert result.geo_stale_rewritten == result.geo_stale_unchanged == 0
    assert await _row(migrated_session, feature_id) == before_row
    assert await _stamp_row(migrated_session, feature_id) == before_stamp


async def test_mid_run_dataset_switch_never_produces_fresh_looking_stamps(
    migrated_session: AsyncSession,
) -> None:
    """run 토큰은 B인데 응답이 다른 토큰을 냈다(전환을 가로지른 run) — 스탬프도 stale 분기도 "
    "없다."""
    _, feature_id = await _load_a(migrated_session, "mid-run-switch")
    before_stamp = await _stamp_row(migrated_session, feature_id)

    again = await _festival("mid-run-switch", _FakeReverse(_geo(road_name_code="115603118999")))
    result = await load_bundles(
        migrated_session, [again], geo=_ctx(REF_B, observed=frozenset({TOKEN_A, TOKEN_B}))
    )

    assert result.geo_stamps_written == 0
    assert await _stamp_row(migrated_session, feature_id) == before_stamp

    # 새 행도 마찬가지 — 전환을 가로지른 run이 만든 행은 스탬프가 없다(stale로 남아 다시 계획된다).
    fresh = await _festival("mid-run-switch-new", _FakeReverse(_geo()))
    result = await load_bundles(
        migrated_session, [fresh], geo=_ctx(REF_B, observed=frozenset({TOKEN_A}))
    )
    assert result.geo_stamps_written == 0
    assert await get_stamp(migrated_session, await _feature_id(migrated_session, fresh)) is None


async def test_empty_answer_guard_keeps_stored_columns(migrated_session: AsyncSession) -> None:
    """geo 빈 답 + provider 원문 legal 있음(standard_data) — 덮지도 스탬프도 하지 않는다."""
    _, feature_id = await _load_a(migrated_session, "empty-guard")
    before_row = await _row(migrated_session, feature_id)
    before_stamp = await _stamp_row(migrated_session, feature_id)

    again = await _festival("empty-guard", _FakeReverse(None))
    assert again.feature.address.legal is not None  # 원문 legal은 남아 있다 — 판정 집합 밖
    result = await load_bundles(migrated_session, [again], geo=_ctx(REF_B))

    assert result.geo_empty_guarded == 1
    assert await _row(migrated_session, feature_id) == before_row
    assert await _stamp_row(migrated_session, feature_id) == before_stamp


async def test_empty_answer_guard_on_changed_payload_keeps_only_address(
    migrated_session: AsyncSession,
) -> None:
    _, feature_id = await _load_a(migrated_session, "empty-guard-changed")
    before = await _row(migrated_session, feature_id)

    again = await _festival("empty-guard-changed", _FakeReverse(None), description="바뀐 설명")
    result = await load_bundles(migrated_session, [again], geo=_ctx(REF_B))

    after = await _row(migrated_session, feature_id)
    assert result.geo_empty_guarded == 1
    assert after["legal_dong_code"] == before["legal_dong_code"] == "1156011000"
    assert after["address"] == before["address"]


async def test_override_mismatch_is_a_finding_once_and_not_a_rewrite(
    migrated_session: AsyncSession,
) -> None:
    _, feature_id = await _load_a(migrated_session, "override")
    before = await _row(migrated_session, feature_id)
    # 사람이 도로명코드를 고정했다 — 열과, 같은 값을 담은 address jsonb 둘 다(address에도 코드가
    # 있다).
    stored_address = before["address"]
    if isinstance(stored_address, str):
        stored_address = json.loads(stored_address)
    for path, value in (
        ("core.road_name_code", "115603118001"),
        ("core.address", stored_address),
    ):
        await migrated_session.execute(
            text(
                "INSERT INTO ops.feature_overrides (feature_id, field_path, override_value, status)"
                "VALUES (CAST(:id AS uuid), :path, CAST(:value AS jsonb), 'active')"
            ),
            {"id": feature_id, "path": path, "value": json.dumps(value)},
        )

    again = await _festival("override", _FakeReverse(_geo(road_name_code="115603118999")))
    first = await load_bundles(migrated_session, [again], geo=_ctx(REF_B))
    second = await load_bundles(migrated_session, [again], geo=_ctx(REF_B))

    assert first.geo_override_stale_findings == 1
    assert second.geo_override_stale_findings == 0
    # override가 있는 열만 달랐다 — 비교에서 빼므로 다시 쓰지 않는다(row_revision 불변).
    # 의도적 빨강(2): override 열을 비교에 넣으면 여기서 row_revision이 전진한다.
    assert (await _row(migrated_session, feature_id))["row_revision"] == before["row_revision"]
    count = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM ops.data_integrity_violations "
                "WHERE violation_type = 'address_override_geo_stale' "
                "AND feature_id = CAST(:id AS uuid) AND payload ->> 'geo_data_token' = :token"
            ),
            {"id": feature_id, "token": TOKEN_B},
        )
    ).scalar_one()
    assert count == 1


async def test_no_geo_context_writes_no_stamps(migrated_session: AsyncSession) -> None:
    """geo를 배선하지 않은 경로(price 적재는 ``load_bundles(session, bundles)``)는 스탬프가 "
    "0이다."""
    bundle = await _festival("no-geo", _FakeReverse(_geo()))
    result = await load_bundles(migrated_session, [bundle])
    assert result.geo_stamps_written == 0
    assert await get_stamp(migrated_session, await _feature_id(migrated_session, bundle)) is None


@pytest.mark.parametrize(
    ("stamp", "current", "unchanged"),
    [
        (("called", REF_A), TOKEN_B, False),
        (("called", REF_A), TOKEN_A, True),
        (("not_called", REF_A), TOKEN_B, True),
        (("called", REF_A), None, True),
        (None, TOKEN_B, False),
        (None, None, True),
    ],
    ids=[
        "called-old",
        "called-current",
        "not-called-old",
        "token-none",
        "unstamped",
        "unstamped-none",
    ],
)
async def test_unchanged_entities_respect_the_stamp_token(
    migrated_session: AsyncSession,
    stamp: tuple[str, DatasetRef] | None,
    current: str | None,
    unchanged: bool,
) -> None:
    seed = f"cte-{stamp is None}-{current}-{unchanged}"
    bundle = await _festival(seed, _FakeReverse(_geo()))
    await load_bundles(migrated_session, [bundle])
    feature_id = await _feature_id(migrated_session, bundle)
    if stamp is not None:
        outcome, ref = stamp
        await upsert_stamps(migrated_session, current=ref, outcomes={feature_id: outcome})  # type: ignore[dict-item]
    record = bundle.source_record
    found = await find_unchanged_active_source_entities(
        migrated_session,
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        payload_hashes={record.source_entity_id: record.raw_payload_hash},
        current_data_token=current,
    )
    assert (record.source_entity_id in found) is unchanged


async def test_unresolvable_marker_is_trusted_only_under_its_token(
    migrated_session: AsyncSession,
) -> None:
    bundle = await _festival("marker", _FakeReverse(_geo()))
    await load_bundles(migrated_session, [bundle])
    key = "mois-unresolvable-test:marker"
    record_key = bundle.source_record.source_record_key
    await create_data_integrity_violation(
        migrated_session,
        violation_type="mois_reverse_geocode_unresolvable_test",
        severity="info",
        message="test marker",
        payload={"dedupe_key": key, "source_record_key": record_key, "geo_data_token": TOKEN_A},
    )

    async def fresh(fields: dict[str, str] | None) -> frozenset[str]:
        return await find_fresh_open_findings(
            migrated_session,
            violation_type="mois_reverse_geocode_unresolvable_test",
            expected_source_record_keys={key: record_key},
            max_age_days=30,
            expected_payload_fields=fields,
        )

    assert await fresh({"geo_data_token": TOKEN_A}) == {key}
    assert await fresh({"geo_data_token": TOKEN_B}) == frozenset()
    assert await fresh(None) == {key}


def _concierge_item(*, token: str | None, legal_dong_code: str | None) -> dict[str, Any]:
    address: dict[str, Any] = {
        "official_address": "제주특별자치도 서귀포시 성산읍",
        "road_address": None,
        "legal_dong_code": legal_dong_code,
        "sido_code": None,
        "sigungu_code": None,
    }
    if token is not None:
        address["geo_data_token"] = token
    return {
        "export_id": "ytpc_geo_1",
        "candidate_id": 77001,
        "operation": "upsert",
        "schema_version": 1,
        "place": {
            "name": "성산일출봉 geo",
            "description": "geo 토큰 테스트",
            "category_label": "관광지",
            "category_code_suggestion": "01010100",
            "longitude": 126.9410,
            "latitude": 33.4580,
            "address": address,
        },
        "youtube": {"video_id": "geo-1", "video_url": "https://www.youtube.com/watch?v=geo-1"},
        "evidence": {"confidence_score": 0.9},
        "source_record": {
            "provider": KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
            "dataset_key": "kor_travel_concierge_youtube_place_candidates",
            "source_entity_type": KOR_TRAVEL_CONCIERGE_SOURCE_ENTITY_TYPE,
            "source_entity_id": "77001",
            "raw_payload_hash": f"sha256:{(token or 'none')[-8:].rjust(64, '0')}",
        },
        "updated_at": "2026-10-16T00:00:00Z",
    }


def _jeju_geo() -> Address:
    return Address(
        bjd_code="5013025300",
        admin_dong_code="5013025000",
        sigungu_code="50130",
        sido_code="50",
        admin="성산읍",
        zipcode="63643",
        sido_name="제주특별자치도",
        sigungu_name="서귀포시",
    )


class _ObservedFake:
    def __init__(self, answer: Address | None) -> None:
        self.answer = answer

    async def observe(self, coord: Coordinate) -> Any:
        from kortravelmap.geocoding import ReverseGeocodeObservation

        return ReverseGeocodeObservation(self.answer, ())

    async def __call__(self, coord: Coordinate) -> Address | None:
        return self.answer


async def _concierge_bundle(
    *, payload_token: str | None, current: str | None, legal_dong_code: str | None
) -> FeatureBundle:
    bundles = await kor_travel_concierge_items_to_bundles(
        [_concierge_item(token=payload_token, legal_dong_code=legal_dong_code)],  # type: ignore[list-item]
        fetched_at=_FETCHED,
        reverse_geocoder=_ObservedFake(_jeju_geo()),  # type: ignore[arg-type]
        current_data_token=current,
    )
    return bundles[0]


async def test_concierge_token_only_change_is_not_became_current(
    migrated_session: AsyncSession,
) -> None:
    first = await _concierge_bundle(payload_token=TOKEN_A, current=TOKEN_A, legal_dong_code=None)
    await load_bundles(migrated_session, [first], geo=_ctx(REF_A))
    feature_id = await _feature_id(migrated_session, first)
    before = await _row(migrated_session, feature_id)

    second = await _concierge_bundle(payload_token=TOKEN_B, current=TOKEN_B, legal_dong_code=None)
    assert second.source_record.raw_payload_hash == first.source_record.raw_payload_hash
    result = await load_bundles(migrated_session, [second], geo=_ctx(REF_B))

    assert result.source_records_inserted == 0  # 같은 record — became_current 아님
    assert (await _row(migrated_session, feature_id))["row_revision"] == before["row_revision"]
    stamp = await get_stamp(migrated_session, feature_id)
    assert stamp is not None
    assert (stamp.geo_data_token, stamp.reverse_outcome) == (TOKEN_B, "called")


async def test_concierge_payload_code_trusted_only_under_the_current_token() -> None:
    stale_code = "5013025900"  # payload가 옛 토큰으로 캐시한 코드
    trusted = await _concierge_bundle(
        payload_token=TOKEN_B, current=TOKEN_B, legal_dong_code=stale_code
    )
    distrusted = await _concierge_bundle(
        payload_token=TOKEN_A, current=TOKEN_B, legal_dong_code=stale_code
    )
    legacy = await _concierge_bundle(
        payload_token=TOKEN_A, current=None, legal_dong_code=stale_code
    )

    assert trusted.feature.address.bjd_code == stale_code
    assert distrusted.feature.address.bjd_code == "5013025300"  # geo bjd 채택
    assert legacy.feature.address.bjd_code == stale_code  # kwarg 생략 = 종전(payload 우선)


# -- 빈 답 가드: 원문 legal을 채우는 provider 셋 모두(acceptance §T-GR-03 의도적 빨강 1) -------


@dataclass(frozen=True)
class _HeritageKey:
    ccba_kdcd: str
    ccba_asno: str
    ccba_ctcd: str

    @property
    def natural_key(self) -> str:
        return f"{self.ccba_kdcd}-{self.ccba_asno}-{self.ccba_ctcd}"


@dataclass(frozen=True)
class _HeritageItem:
    key: _HeritageKey
    name_ko: str
    category: str | None = None
    region: str | None = None
    sigungu: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    location_text: str | None = None
    designated_at: str | None = None
    owner: str | None = None
    image_url: str | None = None
    geom_wkt: str | None = None
    boundary_source: str | None = None


async def _heritage(reverse: _FakeReverse) -> FeatureBundle:
    from kortravelmap.providers.krheritage import heritage_items_to_bundles

    item = _HeritageItem(
        key=_HeritageKey("11", "990001", "11"),
        name_ko="geo 릴리스 유적",
        longitude=126.9239,
        latitude=37.5263,
        location_text="서울특별시 영등포구 여의도동 8",  # 원문 legal — geo 빈 답에도 남는다
    )
    return (
        await heritage_items_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=_FETCHED,
            reverse_geocoder=reverse,
        )
    )[0]


async def test_empty_answer_guard_holds_for_krheritage(migrated_session: AsyncSession) -> None:
    first = await _heritage(_FakeReverse(_geo()))
    await load_bundles(migrated_session, [first], geo=_ctx(REF_A))
    feature_id = await _feature_id(migrated_session, first)
    before_row = await _row(migrated_session, feature_id)
    before_stamp = await _stamp_row(migrated_session, feature_id)

    again = await _heritage(_FakeReverse(None))
    assert again.feature.address.legal is not None
    result = await load_bundles(migrated_session, [again], geo=_ctx(REF_B))

    assert result.geo_empty_guarded == 1
    assert await _row(migrated_session, feature_id) == before_row
    assert await _stamp_row(migrated_session, feature_id) == before_stamp


async def test_empty_answer_guard_holds_for_concierge(migrated_session: AsyncSession) -> None:
    async def bundle(answer: Address | None) -> FeatureBundle:
        return (
            await kor_travel_concierge_items_to_bundles(
                [_concierge_item(token=None, legal_dong_code=None)],  # type: ignore[list-item]
                fetched_at=_FETCHED,
                reverse_geocoder=_ObservedFake(answer),  # type: ignore[arg-type]
            )
        )[0]

    first = await bundle(_jeju_geo())
    await load_bundles(migrated_session, [first], geo=_ctx(REF_A))
    feature_id = await _feature_id(migrated_session, first)
    before_row = await _row(migrated_session, feature_id)
    before_stamp = await _stamp_row(migrated_session, feature_id)

    again = await bundle(None)
    assert again.feature.address.legal is not None  # official_address 원문
    result = await load_bundles(migrated_session, [again], geo=_ctx(REF_B))

    assert result.geo_empty_guarded == 1
    assert await _row(migrated_session, feature_id) == before_row
    assert await _stamp_row(migrated_session, feature_id) == before_stamp
