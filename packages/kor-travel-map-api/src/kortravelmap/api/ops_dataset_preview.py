"""fixture-only dataset preview 실행 경계 (#678).

기존 ``etl_live.py``의 raw HTTP→로컬 dataclass adapter는 ADR-044의 provider public
client+typed model 경계를 만족하지 않으므로 신규 ops 제품 API에서 제거한다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Final

from kortravelmap.api.etl_fixtures import run_fixture_preview

__all__ = [
    "PREVIEW_DEFAULT_MAX_ITEMS",
    "PREVIEW_MAX_ITEMS_LIMIT",
    "PREVIEW_TIMEOUT_SECONDS",
    "DatasetPreviewResult",
    "run_dataset_fixture_preview",
]

PREVIEW_DEFAULT_MAX_ITEMS: Final[int] = 20
PREVIEW_MAX_ITEMS_LIMIT: Final[int] = 100
PREVIEW_TIMEOUT_SECONDS: Final[float] = 5.0


@dataclass(frozen=True)
class DatasetPreviewResult:
    provider: str
    dataset: str
    variant: str
    description: str
    items: tuple[dict[str, Any], ...]
    total_items: int
    max_items: int

    @property
    def truncated(self) -> bool:
        return self.total_items > len(self.items)


async def run_dataset_fixture_preview(
    provider: str,
    dataset: str,
    *,
    max_items: int = PREVIEW_DEFAULT_MAX_ITEMS,
) -> DatasetPreviewResult:
    """fixture 변환 결과를 최대 ``max_items``개만 응답한다.

    timeout은 coroutine이 제어권을 양보하는 구간에 적용된다. ``max_items``는 응답
    크기 cap이며 fixture 변환 자체의 CPU 비용을 줄인다고 주장하지 않는다. 외부 API
    호출 budget은 구조적으로 0이다.
    """
    if not 1 <= max_items <= PREVIEW_MAX_ITEMS_LIMIT:
        raise ValueError(
            f"max_items must be between 1 and {PREVIEW_MAX_ITEMS_LIMIT}"
        )
    async with asyncio.timeout(PREVIEW_TIMEOUT_SECONDS):
        raw = await run_fixture_preview(provider, dataset)
    raw_items = raw.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("fixture preview items must be a list")
    items = tuple(dict(item) for item in raw_items[:max_items])
    return DatasetPreviewResult(
        provider=str(raw["provider"]),
        dataset=str(raw["dataset"]),
        variant=str(raw["variant"]),
        description=str(raw["description"]),
        items=items,
        total_items=len(raw_items),
        max_items=max_items,
    )
