"""전통시장·특화거리 asset 배선 — 공개 파일 snapshot의 은퇴 적재와 빈 snapshot 차단(#1459).

두 asset은 snapshot에 없는 장소를 **은퇴**시킨다. 그래서 (1) 정상 run은 은퇴·봉인 플래그로
``_load``를 부르고, (2) 원천 0행이나 변환 0건이면 ``_load``에 닿기 전에 실패해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from dagster import Failure

from kortravelmap.dagster import assets

_FETCHED = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Street:
    stret_nm: str | None = "광릉숲음식문화특화테마거리"
    stret_intrcn: str | None = None
    rdnmadr: str | None = "경기도 남양주시 진접읍 광릉수목원로 179-19"
    lnmadr: str | None = None
    latitude: float | None = 37.747
    longitude: float | None = 127.187
    stret_lt: float | None = None
    stor_number: int | None = None
    appn_year: int | None = None
    phone_number: str | None = None
    institution_nm: str | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None
    raw: Any = field(default_factory=dict)


@dataclass(frozen=True)
class _Market:
    mrkt_nm: str | None = "망원시장"
    mrkt_type: str | None = None
    rdnmadr: str | None = "서울특별시 마포구 망원로8길 7"
    lnmadr: str | None = None
    mrkt_estbl_cycle: str | None = None
    latitude: float | None = 37.557
    longitude: float | None = 126.906
    stor_number: int | None = None
    trtmnt_prdlst: str | None = None
    use_gcct: str | None = None
    homepage_url: str | None = None
    pblic_toilet_yn: str | None = None
    prkplce_yn: str | None = None
    estbl_year: int | None = None
    phone_number: str | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    raw: Any = field(default_factory=dict)


_CASES = [
    ("standard_special_streets", "run_feature_place_standard_special_streets", _Street(),
     replace(_Street(), stret_nm=" "), "special_street", "standard_special_streets"),
    ("standard_traditional_markets", "run_feature_place_standard_traditional_markets",
     _Market(), replace(_Market(), mrkt_nm=""), "traditional_market",
     "datagokr_traditional_markets"),
]


def _context(resource: str, records: list[Any]) -> Any:
    return cast(Any, SimpleNamespace(
        resources=SimpleNamespace(**{resource: records, "fetched_at": _FETCHED}),
        log=SimpleNamespace(info=lambda *_: None, warning=lambda *_: None),
    ))


@pytest.mark.parametrize(("resource", "run", "good", "blank", "entity", "dataset"), _CASES)
async def test_live_run_retires_absent_rows_from_a_complete_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    resource: str, run: str, good: Any, blank: Any, entity: str, dataset: str,
) -> None:
    del blank
    seen: dict[str, Any] = {}

    async def _fake_load(context: object, **kwargs: Any) -> str:
        seen.update(kwargs)
        return "loaded"

    monkeypatch.setattr(assets, "_load", _fake_load)
    assert await getattr(assets, run)(_context(resource, [good])) == "loaded"
    assert seen["dataset_key"] == dataset
    assert seen["source_entity_type"] == entity
    assert seen["retire_absent_from_snapshot"] is True
    assert seen["authoritative_snapshot_complete"] is True
    assert seen["record_sync_state"] is True
    assert len(seen["bundles"]) == 1


@pytest.mark.parametrize(("resource", "run", "good", "blank", "entity", "dataset"), _CASES)
@pytest.mark.parametrize("which", ["empty", "all_blank"])
async def test_empty_snapshot_or_empty_conversion_never_reaches_the_load(
    monkeypatch: pytest.MonkeyPatch,
    resource: str, run: str, good: Any, blank: Any, entity: str, dataset: str, which: str,
) -> None:
    del good, entity, dataset

    async def _fake_load(context: object, **kwargs: Any) -> str:
        raise AssertionError("은퇴 적재에 닿으면 안 된다")

    monkeypatch.setattr(assets, "_load", _fake_load)
    records = [] if which == "empty" else [blank, blank]
    with pytest.raises(Failure):
        await getattr(assets, run)(_context(resource, records))
