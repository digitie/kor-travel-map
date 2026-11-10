"""TourAPI 축제 asset — 유일한 축제 원천(2026-11-10)의 상세 예산·은퇴 가드·적재 배선.

축제와 관광지는 같은 ``detailCommon2`` 오퍼레이션을 쓰고 data.go.kr 한도는 **오퍼레이션마다**
걸린다(일일 1,000). 두 dataset의 run 예산은 그 한도를 나눠 쓴다. fetcher 쪽 완전성 가드는
``test_provider_fetchers.py``가, 변환기는 ``tests/unit/test_providers_visitkorea.py``가 본다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from dagster import Failure

from kortravelmap.dagster import assets

KST = timezone(timedelta(hours=9))
_T = datetime(2026, 11, 10, 4, 35, tzinfo=KST)


def _tour_item(content_id: str, **fields: Any) -> Any:
    visitkorea = pytest.importorskip("visitkorea")
    base: dict[str, Any] = {
        name: None for name in visitkorea.TourItem.model_fields if name != "raw"
    }
    base.update(
        content_id=content_id,
        content_type_id="15",
        title=f"축제 {content_id}",
        addr1="경상북도 포항시 북구 두호동 685-1",
        map_x=129.3655,
        map_y=36.0567,
        lcls_systm1="EV",
        lcls_systm2="EV01",
        lcls_systm3="EV010200",
        event_start_date="20261119",
        event_end_date="20261121",
        modified_time=_T,
        raw={"contentid": content_id},
    )
    base.update(fields)
    return visitkorea.TourItem.model_validate(base)


class _StoredClient:
    def __init__(self, stored: list[Any]) -> None:
        self.stored = stored
        self.reads: list[dict[str, str]] = []

    async def read_current_source_records(self, **kwargs: str) -> tuple[list[Any], int]:
        self.reads.append(kwargs)
        return self.stored, len(self.stored)


def _context(client: object, *, retry_number: int = 0) -> Any:
    return SimpleNamespace(
        resources=SimpleNamespace(kor_travel_map_client=client),
        log=SimpleNamespace(info=lambda *_a, **_k: None),
        retry_number=retry_number,
    )


@pytest.fixture
def requested(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def _details(settings: Any, content_ids: Any) -> dict[str, tuple[str, str]]:
        del settings
        seen.extend(content_ids)
        return {cid: (f"새 설명 {cid}", "") for cid in content_ids}

    monkeypatch.setattr(assets, "fetch_visitkorea_attraction_details", _details)
    return seen


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """asset 본문 밖(자원·geo·적재)을 대역으로 바꾸고 무엇이 불렸는지 모은다."""
    seen: dict[str, Any] = {"records": [], "load": None, "geo_guard": None}

    async def _resource_value(context: Any, name: str, *, default: object = None) -> object:
        del context, default
        return _T if name == "fetched_at" else object()

    async def _prefetch(source: object) -> None:
        del source

    async def _record_list(context: Any, resource_key: str) -> list[Any]:
        del context
        seen["resource_key"] = resource_key
        return list(seen["records"])

    async def _transform(
        context: Any, transform: Any, records: Any, /, **kwargs: Any
    ) -> list[Any]:
        del context
        seen["transform"] = transform
        seen["transformed"] = list(records)
        return await transform(records, **kwargs)

    def _geo_guard(bundles: Any, *, label: str = "") -> None:
        seen["geo_guard"] = (len(bundles), label)

    async def _load(context: Any, **kwargs: Any) -> str:
        del context
        seen["load"] = kwargs
        return "loaded"

    monkeypatch.setattr(assets, "_resource_value", _resource_value)
    monkeypatch.setattr(assets, "prefetch_replay", _prefetch)
    monkeypatch.setattr(assets, "is_replay", lambda source: False)
    monkeypatch.setattr(assets, "_record_list", _record_list)
    monkeypatch.setattr(assets, "_transform_reusing_geo", _transform)
    monkeypatch.setattr(assets, "_reverse_geocoder", lambda context: None)
    monkeypatch.setattr(assets, "_ensure_geo_resolved_enough", _geo_guard)
    monkeypatch.setattr(assets, "_load", _load)
    return seen


def test_the_two_detail_budgets_fit_the_shared_daily_quota() -> None:
    # 관광지·축제 모두 매일 돈다. 둘이 같은 detailCommon2 일일 한도(1,000)를 쓰므로 합이 한도
    # 아래여야 한다 — 하나만 올리면 다른 쪽 run이 한도에 막혀 상세 없이 끝난다.
    total = assets.VISITKOREA_ATTRACTION_DETAIL_BUDGET + assets.VISITKOREA_FESTIVAL_DETAIL_BUDGET
    assert total <= assets.VISITKOREA_DETAIL_DAILY_BUDGET < 1000
    assert assets.VISITKOREA_FESTIVAL_DETAIL_BUDGET > 0


async def test_an_empty_festival_list_fails_before_retiring_every_festival(
    wired: dict[str, Any],
) -> None:
    wired["records"] = []

    with pytest.raises(Failure, match="0행"):
        await assets.run_feature_event_visitkorea_festivals(_context(_StoredClient([])))
    assert wired["load"] is None


async def test_festival_details_come_from_the_festival_dataset_within_its_budget(
    monkeypatch: pytest.MonkeyPatch, requested: list[str], wired: dict[str, Any]
) -> None:
    monkeypatch.setattr(assets, "VISITKOREA_FESTIVAL_DETAIL_BUDGET", 2)
    stored = [
        SimpleNamespace(
            source_entity_id="a",
            raw_data={"modified_time": _T.isoformat(), "overview": "저장 설명", "homepage": ""},
        )
    ]
    client = _StoredClient(stored)
    wired["records"] = [_tour_item(cid) for cid in ("a", "b", "c", "d")]

    result = await assets.run_feature_event_visitkorea_festivals(_context(client))

    assert result == "loaded"
    assert wired["resource_key"] == "visitkorea_festivals"
    # 저장 상세는 축제 dataset에서 읽는다(관광지 dataset이 아니다).
    assert client.reads == [
        {"provider": "python-visitkorea-api", "dataset_key": "visitkorea_festivals"}
    ]
    # 예산(2) 안에서 새 항목만 받는다 — 저장 상세가 있는 a는 다시 받지 않는다.
    assert requested == ["b", "c"]
    assert [(r.content_id, r.overview) for r in wired["transformed"]] == [
        ("a", "저장 설명"),
        ("b", "새 설명 b"),
        ("c", "새 설명 c"),
        ("d", None),
    ]
    assert wired["geo_guard"] == (4, "TourAPI 축제")
    load = wired["load"]
    assert load["provider"] == "python-visitkorea-api"
    assert load["dataset_key"] == "visitkorea_festivals"
    assert load["source_entity_type"] == "festival"
    # 수집 창 전체가 한 snapshot이다 — 창에서 밀려난 축제는 은퇴한다.
    assert load["retire_absent_from_snapshot"] is True
    assert load["authoritative_snapshot_complete"] is True
    assert {bundle.feature.kind.value for bundle in load["bundles"]} == {"event"}


async def test_the_festival_run_never_asks_for_more_than_its_share(
    requested: list[str], wired: dict[str, Any]
) -> None:
    wired["records"] = [
        _tour_item(str(n)) for n in range(assets.VISITKOREA_FESTIVAL_DETAIL_BUDGET + 50)
    ]

    await assets.run_feature_event_visitkorea_festivals(_context(_StoredClient([])))

    assert len(requested) == assets.VISITKOREA_FESTIVAL_DETAIL_BUDGET


async def test_a_retried_festival_step_does_not_spend_the_budget_again(
    requested: list[str], wired: dict[str, Any]
) -> None:
    wired["records"] = [_tour_item("a"), _tour_item("b")]

    await assets.run_feature_event_visitkorea_festivals(
        _context(_StoredClient([]), retry_number=1)
    )

    assert requested == []
