"""``kortravelmap.core.retention`` — 이력을 두지 않는(latest-only) dataset 정책의 정본 (ADR-114).

kor-travel-transport가 수집·보관하는 데이터는 Map이 이력을 다시 쌓지 않는다(소유자 결정 2026-10-23).
이 모듈이 **그 정책의 유일한 자리**다. 적재·maintenance·API는 모두 여기서 묻는다.

- :data:`LATEST_ONLY_DATASETS` — ``(provider, dataset_key)``. 이 dataset은
  - price fact를 series당 현재 winner 하나만 남기고(``price_repo.prune_superseded_price_facts``),
  - source record를 entity head만 남기며, 아무 Feature에도 묶이지 않은 entity를 지우고
    (``retention_repo.prune_latest_only_lineage``),
  - 가격 추이를 Map DB가 아니라 transport에서 읽는다(API ``transport_price_history``).
- :data:`ENDED_NOTICE_DELETE_AFTER` — 종료(``valid_end_time``) 뒤 이 기간이 지나면 notice Feature를
  **실제로 지우는** dataset별 override. 다른 notice는 ``purge_expired_notices``의 1년 retire 그대로다.

dataset은 번호가 아니라 ``(provider, dataset_key)``로 고른다 — ``provider_dataset_id``는 DB마다 다르다.
키 문자열은 ``providers.kor_travel_transport``의 ``DATASET_KEY_*``와 같아야 한다. ``core``는 ``providers``를
import할 수 없으므로(의존 방향) 단위 검사(``tests/unit/test_core_retention.py``)가 둘을 대조한다.

DB에도 fence가 있다(migration 410). 그것은 **provider 단위**(``kor-travel-transport``)라 이 목록을 다시
적지 않는다 — 다른 provider의 불변 이력(ADR-089)이 코드 실수로 지워지지 않게 하는 안전망이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType
from typing import Final

__all__ = [
    "ENDED_NOTICE_DELETE_AFTER",
    "LATEST_ONLY_DATASETS",
    "LATEST_ONLY_PROVIDER",
    "ended_notice_delete_after",
    "is_latest_only",
]

LATEST_ONLY_PROVIDER: Final[str] = "kor-travel-transport"
"""migration 410의 DB fence가 허용하는 유일한 provider. 아래 목록은 모두 이 provider여야 한다."""

LATEST_ONLY_DATASETS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        (LATEST_ONLY_PROVIDER, "transport_fuel_stations"),
        (LATEST_ONLY_PROVIDER, "transport_fuel_prices"),
        (LATEST_ONLY_PROVIDER, "transport_rest_areas"),
        (LATEST_ONLY_PROVIDER, "transport_rest_area_fuel_prices"),
        (LATEST_ONLY_PROVIDER, "transport_highway_incidents"),
        (LATEST_ONLY_PROVIDER, "transport_airports"),
    }
)
"""이력을 두지 않는 dataset. transport 출처 전부(ADR-114 결정 1)."""

ENDED_NOTICE_DELETE_AFTER: Final[Mapping[tuple[str, str], timedelta]] = MappingProxyType(
    {
        # 고속도로 돌발: 종료 1일 뒤 Feature·identity·lineage를 지운다. 다시 나타나면 새 identity다.
        (LATEST_ONLY_PROVIDER, "transport_highway_incidents"): timedelta(days=1),
    }
)
"""종료 뒤 notice Feature를 실제로 지우는 dataset별 유예(ADR-114 결정 4)."""


def is_latest_only(provider: str, dataset_key: str) -> bool:
    """``(provider, dataset_key)``가 이력을 두지 않는 dataset인가."""
    return (provider, dataset_key) in LATEST_ONLY_DATASETS


def ended_notice_delete_after(provider: str, dataset_key: str) -> timedelta | None:
    """종료 notice를 지우는 유예. override가 없으면 ``None``(일반 1년 retire를 따른다)."""
    return ENDED_NOTICE_DELETE_AFTER.get((provider, dataset_key))
