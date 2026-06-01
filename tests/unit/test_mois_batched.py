"""``test_mois_batched`` — streaming 배치 helper + FeatureLoadResult.merge (순수).

mois Step A streaming 적재의 메모리 바운드 배치 분할(``_batched``)과 결과 누적
(``FeatureLoadResult.merge``)을 DB 없이 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from krtour.map.infra.feature_repo import FeatureLoadResult
from krtour.map.mois import _batched


@dataclass(frozen=True)
class _Rec:
    service_slug: str = "general_restaurants"


def test_batched_exact_multiple() -> None:
    items = [_Rec() for _ in range(6)]
    batches = list(_batched(items, 2))
    assert [len(b) for b in batches] == [2, 2, 2]


def test_batched_remainder() -> None:
    items = [_Rec() for _ in range(5)]
    batches = list(_batched(items, 2))
    assert [len(b) for b in batches] == [2, 2, 1]


def test_batched_smaller_than_size() -> None:
    items = [_Rec(), _Rec()]
    assert [len(b) for b in _batched(items, 10)] == [2]


def test_batched_empty() -> None:
    assert list(_batched([], 3)) == []


def test_batched_preserves_order_and_content() -> None:
    items = [_Rec(service_slug=str(i)) for i in range(5)]
    flat = [r for batch in _batched(items, 2) for r in batch]
    assert [r.service_slug for r in flat] == ["0", "1", "2", "3", "4"]


def test_feature_load_result_merge() -> None:
    a = FeatureLoadResult(bundles_total=2, features_inserted=2, source_records_inserted=2)
    b = FeatureLoadResult(
        bundles_total=3, features_inserted=1, features_updated=2,
        source_links_inserted=3,
    )
    merged = a.merge(b)
    assert merged.bundles_total == 5
    assert merged.features_inserted == 3
    assert merged.features_updated == 2
    assert merged.source_records_inserted == 2
    assert merged.source_links_inserted == 3


def test_feature_load_result_merge_identity() -> None:
    empty = FeatureLoadResult()
    r = FeatureLoadResult(bundles_total=4, features_inserted=4)
    assert empty.merge(r) == r
    assert r.merge(empty) == r
