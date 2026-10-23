"""payload·좌표·geo 토큰이 그대로인 행은 역지오코딩하지 않고 저장값을 다시 쓴다(ADR-116).

비-MOIS 적재는 run마다 모든 좌표를 역지오코딩했지만, payload가 같고 스탬프가 현재 토큰인 행의 새
답은 ``load_bundle``이 쓰지 않는다. 이 모듈은 그 행에 한해 저장 주소 열을 역지오코더의 답으로
돌려준다.

역지오코더는 좌표만 받으므로 어느 record의 호출인지 모른다. 그래서 변환을 감싼다(asset마다의 코드가
아니라 이 한 곳 — asset은 변환 호출을 :func:`transform_reusing_stored_geo`에 넘길 뿐이다):

1. **pass 0** — geo를 부르지 않는 빈 답 대역으로 변환해 행의 identity·record key·좌표만 얻는다.
2. **조회** — 재사용 조건을 만족하는 행과 저장 주소 열을 한 번에 읽는다(``lookup`` — fence 없는
   읽기).
3. **좌표 표** — 좌표(provider 캐시와 같은 6자리 키)를 쓰는 행이 **전부** 조건을 만족하고 저장값이
   **모두 같을 때만** 그 좌표의 답을 저장 ``address``로 정한다. pass 0의 요청 좌표가 행 좌표 집합
   밖이면 표를 만들지 않는다.
4. **pass 1** — 표의 좌표는 저장값, 나머지는 실제 geo로 답하는 역지오코더로 다시 변환한다.
5. **사후 확인** — 저장값을 받은 bundle의 주소 유도 열이 저장값과 정확히 같고 차단 검증 issue가
   없어야 한다. 어긋난 좌표는 표에서 빼고 다시 변환한다(그래도 어긋나면 표 없이 — 재사용 전과 같은
   경로).

결과 bundle의 재사용 행은 저장된 주소 열과 같은 값을 갖는다 — 적재가 그 행을 쓰지
않고(``row_revision`` 불변), 스탬프는 이미 현재 토큰이다.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Final

from kortravelmap.dagster.validation import (
    DROPPABLE_ISSUE_CODES,
    validate_feature_bundle_address,
)
from pydantic import ValidationError

from kortravelmap.dto import Address
from kortravelmap.geocoding import (
    ObservedReverseGeocoder,
    ReverseGeocodeObservation,
    cached_reverse_geocoder,
    coord_cache_key,
)
from kortravelmap.infra.feature_geocode_load import address_column_values

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from kortravelmap.dto import Coordinate, FeatureBundle
    from kortravelmap.geocoding import GeoCallStats, ReverseGeocoder

__all__ = ["MAX_REUSE_TRANSFORMS", "transform_reusing_stored_geo"]

#: pass 0 뒤 실제 변환 횟수 상한 — 표 → 어긋난 좌표를 뺀 표 → 표 없음.
MAX_REUSE_TRANSFORMS: Final[int] = 3

CoordKey = tuple[str, str]


class _EmptyAnswers:
    """pass 0 대역 — geo를 부르지 않고 언제나 빈 답, 요청 좌표만 기록한다."""

    def __init__(self) -> None:
        self.requested: set[CoordKey] = set()

    async def observe(self, coord: Coordinate) -> ReverseGeocodeObservation:
        self.requested.add(coord_cache_key(coord))
        return ReverseGeocodeObservation(None)

    async def __call__(self, coord: Coordinate) -> Address | None:
        return (await self.observe(coord)).address


class _StoredOrLive:
    """표의 좌표는 저장값으로, 나머지는 실제 geo로 답한다. 저장값으로 답한 좌표를 센다."""

    def __init__(
        self, table: Mapping[CoordKey, ReverseGeocodeObservation], live: ReverseGeocoder
    ) -> None:
        self._table = table
        self._live = live
        self.served: set[CoordKey] = set()

    async def observe(self, coord: Coordinate) -> ReverseGeocodeObservation:
        key = coord_cache_key(coord)
        stored = self._table.get(key)
        if stored is not None:
            self.served.add(key)
            return stored
        if isinstance(self._live, ObservedReverseGeocoder):
            return await self._live.observe(coord)
        address = await self._live(coord)
        names = (address.sigungu_name,) if address is not None and address.sigungu_name else ()
        return ReverseGeocodeObservation(address, names)

    async def __call__(self, coord: Coordinate) -> Address | None:
        return (await self.observe(coord)).address


def _reusable_shape(bundle: FeatureBundle) -> bool:
    """재사용 후보가 될 수 있는 bundle — 좌표·natural key가 있고 geo 관측을 따로 싣지 않는다.

    ``admin_evidence``(후보 시군구·관측 코드)·``geo_attempt``(MOIS)는 원 geo 답의 일부를 싣는다 —
    저장 주소 열로는 재현할 수 없다.
    """
    return (
        bundle.feature.coord is not None
        and bool(bundle.feature.provider_natural_key)
        and bundle.admin_evidence is None
        and bundle.geo_attempt is None
    )


def _normalized(values: Mapping[str, Any]) -> str:
    """저장값(주소 유도 열) 비교 키 — ``address``는 ``Address`` 왕복으로 필드 집합을 맞춘다.

    행이 쓰인 뒤 ``Address``에 필드가 더해졌으면 저장 jsonb에 그 키가 없다. 왕복하지 않으면 같은
    값을 "다르다"로 본다.
    """
    normalized = dict(values)
    normalized["address"] = json.loads(
        Address.model_validate(values.get("address") or {}).model_dump_json()
    )
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)


def _stored_answer(values: Mapping[str, Any]) -> ReverseGeocodeObservation:
    address = Address.model_validate(values.get("address") or {})
    names = (address.sigungu_name,) if address.sigungu_name else ()
    return ReverseGeocodeObservation(address, names)


def _key(bundle: FeatureBundle) -> CoordKey | None:
    coord = bundle.feature.coord
    return coord_cache_key(coord) if coord is not None else None


def _coordinate_table(
    drafts: Sequence[FeatureBundle],
    stored: Mapping[str, Mapping[str, Any]],
) -> dict[CoordKey, ReverseGeocodeObservation]:
    """좌표 → 저장 답. 그 좌표의 행이 전부 재사용 가능하고 저장값이 모두 같은 좌표만 든다."""
    members: dict[CoordKey, list[FeatureBundle]] = defaultdict(list)
    for bundle in drafts:
        key = _key(bundle)
        if key is not None:
            members[key].append(bundle)
    table: dict[CoordKey, ReverseGeocodeObservation] = {}
    for key, rows in members.items():
        values = [stored.get(row.source_record.source_record_key) for row in rows]
        if any(value is None for value in values) or not all(map(_reusable_shape, rows)):
            continue
        present = [value for value in values if value is not None]
        try:
            distinct = {_normalized(value) for value in present}
            answer = _stored_answer(present[0])
        except (ValidationError, TypeError, ValueError):
            # 지금의 ``Address``가 받지 않는 옛 저장값 — 재사용하지 않고 geo에 묻는다(그 행은
            # fallback으로 센다).
            continue
        if len(distinct) == 1:
            table[key] = answer
    return table


def _mismatched(
    bundles: Sequence[FeatureBundle],
    served: set[CoordKey],
    stored: Mapping[str, Mapping[str, Any]],
) -> set[CoordKey]:
    """저장 답을 받았는데 결과가 저장값과 다르거나 차단 issue가 생긴 좌표."""
    bad: set[CoordKey] = set()
    for bundle in bundles:
        key = _key(bundle)
        if key is None or key not in served:
            continue
        values = stored.get(bundle.source_record.source_record_key)
        if values is None or _normalized(values) != _normalized(
            address_column_values(bundle.feature.address)
        ):
            bad.add(key)
            continue
        issues = validate_feature_bundle_address(bundle).issues
        if any(
            issue.severity == "error" and issue.code in DROPPABLE_ISSUE_CODES for issue in issues
        ):
            bad.add(key)
    return bad


def _count(
    bundles: Sequence[FeatureBundle],
    served: set[CoordKey],
    stored: Mapping[str, Mapping[str, Any]],
    stats: GeoCallStats | None,
    *,
    disabled: bool,
) -> None:
    if stats is None:
        return
    if disabled:
        # 안전망이 이 변환의 재사용을 껐다 — "재사용할 것이 없었다"(fallback 0)와 구별되게 센다.
        stats.reuse["disabled"] += sum(1 for bundle in bundles if bundle.feature.coord is not None)
    skipped = geocoded = fallback = 0
    for bundle in bundles:
        key = _key(bundle)
        if key is None:
            continue
        if key in served:
            skipped += 1
            continue
        geocoded += 1
        if bundle.source_record.source_record_key in stored:
            fallback += 1
    stats.record_reuse(skipped=skipped, geocoded=geocoded, fallback=fallback)


async def transform_reusing_stored_geo(
    transform: Callable[[ReverseGeocoder], Awaitable[list[FeatureBundle]]],
    *,
    live: ReverseGeocoder,
    lookup: Callable[[Sequence[FeatureBundle]], Awaitable[Mapping[str, Mapping[str, Any]]]],
    stats: GeoCallStats | None = None,
) -> list[FeatureBundle]:
    """``transform(reverse_geocoder)``을 저장값 재사용과 함께 돌린다(ADR-116).

    ``transform``은 같은 입력으로 몇 번 불려도 같은 결과를 내는 순수 변환이어야 한다(부수효과 없음 —
    concierge처럼 격리 목록을 채우는 변환은 넘기지 않는다). ``live``는 run의 실제 역지오코더,
    ``lookup``은 재사용 조건을 만족하는 행의 ``source_record_key → 저장 주소 유도 열``을 돌려준다.
    ``stats``가 있으면 행 단위 계수를 더한다.
    """
    probe = _EmptyAnswers()
    disabled = False
    try:
        drafts = await transform(probe)
    # 빈 답을 견디지 못하는 변환은 재사용하지 않는다 — 실제 경로가 판정한다.
    except Exception:  # noqa: BLE001
        drafts, disabled = [], True
    row_coords = {key for key in map(_key, drafts) if key is not None}
    if not probe.requested <= row_coords:
        # provider가 행 좌표가 아닌 점을 물었다 — 어느 행의 답인지 가를 수 없다(ADR-116 결정 2
        # 안전망).
        drafts, disabled = [], True
    candidates = [bundle for bundle in drafts if _reusable_shape(bundle)]
    stored: Mapping[str, Mapping[str, Any]] = await lookup(candidates) if candidates else {}
    table = _coordinate_table(drafts, stored) if stored else {}
    del drafts, candidates  # 큰 목록 적재(주차장 1.7만 건)에서 bundle 두 벌을 같이 들지 않는다

    # 재시도가 실제 geo를 다시 부르지 않게 이 호출 동안 실제 답을 기억한다(provider 캐시는 변환마다
    # 새로 생긴다).
    remembered = cached_reverse_geocoder(live)
    bundles: list[FeatureBundle] = []
    served: set[CoordKey] = set()
    for attempt in range(MAX_REUSE_TRANSFORMS):
        geocoder = _StoredOrLive(table, remembered)
        bundles = await transform(geocoder)
        served = geocoder.served
        bad = _mismatched(bundles, served, stored)
        if not bad:
            break
        # 저장값에 대해 provider 병합이 멱등이 아니거나 검증이 막는 좌표 — 그 좌표는 geo에 묻는다.
        # 두 번째도 어긋나면(변환이 결정적이지 않다) 표 없이 한 번 더 — 재사용 전과 같은 경로다.
        table = (
            {} if attempt >= 1 else {key: value for key, value in table.items() if key not in bad}
        )
    _count(bundles, served, stored, stats, disabled=disabled)
    return bundles
