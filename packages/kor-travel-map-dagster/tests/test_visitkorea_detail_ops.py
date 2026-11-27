"""TourAPI 상세 op(소개·이미지·반려동물·무장애) fetcher·asset 경로(ADR-126).

fetcher 테스트는 ``visitkorea`` 모듈 대역을 심는다. 대역 메서드 이름·인자는 실물과 같다
(``visitkorea/client.py``: ``detail_intro(content_id, content_type_id)``,
``detail_images(content_id, *, num_of_rows)``, ``detail_pet_tour(content_id)``;
``visitkorea/hub.py``: ``TourApiHubClient.call(service, operation, params)``).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from kortravelmap.providers.visitkorea_attractions import (
    TOURAPI_DETAIL_RAW_KEY,
    TourApiDetailRequest,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

from kortravelmap.dagster import assets
from kortravelmap.dagster.provider_fetchers import fetch_visitkorea_detail_ops
from kortravelmap.dagster.upstream_requests import counting_upstream_requests

KST = timezone(timedelta(hours=9))
_SETTINGS = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))


class _ProviderError(Exception):
    def __init__(self, failure_kind: str) -> None:
        super().__init__(failure_kind)
        self.failure_kind = failure_kind


def _page(*rows: dict[str, Any]) -> Any:
    return SimpleNamespace(items=tuple(SimpleNamespace(raw=row) for row in rows))


class _FakeClient:
    instances: list[_FakeClient] = []
    errors: dict[tuple[str, str], str] = {}

    def __init__(self, service_key: str | None = None, **_: Any) -> None:
        self.service_key = service_key
        self.closed = False
        self.calls: list[tuple[str, str]] = []
        type(self).instances.append(self)

    def _maybe_fail(self, op: str, content_id: str) -> None:
        self.calls.append((op, content_id))
        kind = type(self).errors.get((op, content_id))
        if kind is not None:
            raise _ProviderError(kind)

    async def detail_intro(self, content_id: str, content_type_id: str) -> Any:
        self._maybe_fail("intro", content_id)
        return _page(
            {
                "contentid": content_id,
                "contenttypeid": content_type_id,
                "usetime": f"상시 {content_id}",
                "restdate": "",
                "unrelated": "x",
            }
        )

    async def detail_images(self, content_id: str, *, num_of_rows: int = 10) -> Any:
        self._maybe_fail("images", content_id)
        assert num_of_rows == 20
        return _page(
            {"originimgurl": "http://tong.visitkorea.or.kr/a.jpg", "cpyrhtDivCd": "Type1"}
        )


    async def aclose(self) -> None:
        self.closed = True


class _FakeHub(_FakeClient):
    instances: list[_FakeClient] = []

    async def call(self, service: str, operation: str, params: dict[str, Any]) -> Any:
        if (service, operation) == ("pet", "detailPetTour2"):
            self._maybe_fail("pet", params["contentId"])
            return SimpleNamespace(items=())  # 원천에 없음
        assert (service, operation) == ("with", "detailWithTour2")
        self._maybe_fail("accessibility", params["contentId"])
        return SimpleNamespace(items=({"wheelchair": "대여 가능", "contentid": "x"},))


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> type[_FakeClient]:
    _FakeClient.instances = []
    _FakeHub.instances = []
    _FakeClient.errors = {}
    module = ModuleType("visitkorea")
    module.__dict__["KrTourApiClient"] = _FakeClient
    module.__dict__["TourApiHubClient"] = _FakeHub
    monkeypatch.setitem(sys.modules, "visitkorea", module)
    return _FakeClient


def _req(*ids: str) -> tuple[TourApiDetailRequest, ...]:
    return tuple(TourApiDetailRequest(content_id=cid, content_type_id="12") for cid in ids)


async def test_each_op_keeps_only_known_fields_and_closes(fake: type[_FakeClient]) -> None:
    with counting_upstream_requests() as counter:
        result = await fetch_visitkorea_detail_ops(
            _SETTINGS,
            {
                "intro": _req("1"),
                "images": _req("1"),
                "pet": _req("1"),
                "accessibility": _req("1"),
            },
        )
    assert result == {
        "intro": {"1": {"usetime": "상시 1"}},
        "images": {
            "1": [{"originimgurl": "http://tong.visitkorea.or.kr/a.jpg", "cpyrhtDivCd": "Type1"}]
        },
        "pet": {"1": {}},
        "accessibility": {"1": {"wheelchair": "대여 가능"}},
    }
    assert counter[0] == 4
    assert all(client.closed for client in [*_FakeClient.instances, *_FakeHub.instances])


async def test_a_quota_stop_on_one_op_does_not_stop_the_others(fake: type[_FakeClient]) -> None:
    fake.errors = {("intro", "2"): "rate_limit", ("images", "2"): "no_data"}
    result = await fetch_visitkorea_detail_ops(
        _SETTINGS, {"intro": _req("1", "2", "3"), "images": _req("1", "2", "3")}
    )
    assert set(result["intro"]) == {"1"}  # 한도 뒤로는 부르지 않는다
    assert result["images"]["2"] == []  # 원천에 없음 = 받은 빈 값
    assert set(result["images"]) == {"1", "2", "3"}
    intro_calls = [c for c in _FakeClient.instances[0].calls if c[0] == "intro"]
    assert intro_calls == [("intro", "1"), ("intro", "2")]


async def test_no_requests_open_no_client(fake: type[_FakeClient]) -> None:
    assert await fetch_visitkorea_detail_ops(_SETTINGS, {"intro": ()}) == {}
    assert fake.instances == []


# -- asset ------------------------------------------------------------------

_T = datetime(2026, 11, 1, 9, 0, tzinfo=KST)


def _tour_item(content_id: str) -> Any:
    visitkorea = pytest.importorskip("visitkorea")
    base: dict[str, Any] = {
        name: None for name in visitkorea.TourItem.model_fields if name != "raw"
    }
    base.update(
        content_id=content_id,
        content_type_id="12",
        title=f"관광지 {content_id}",
        modified_time=_T,
        raw={},
    )
    return visitkorea.TourItem.model_validate(base)


class _Client:
    def __init__(self, stored: list[Any], scores: dict[str, int] | None = None) -> None:
        self.stored = stored
        self.scores = scores
        self.score_reads = 0

    async def read_current_source_records(self, **_: str) -> tuple[list[Any], int]:
        return self.stored, len(self.stored)

    async def read_detail_priority_scores(self, **_: str) -> dict[str, int]:
        self.score_reads += 1
        if self.scores is None:
            raise PermissionError("no grant")
        return self.scores


class _Kv:
    """Dagster ``run_storage``의 ``kvs_get``·``kvs_set`` 대역."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def kvs_get(self, keys: set[str]) -> dict[str, str]:
        return {key: self.values[key] for key in keys if key in self.values}

    def kvs_set(self, pairs: dict[str, str]) -> None:
        self.values.update(pairs)


def _context(
    client: object, *, retry_number: int = 0, kv: _Kv | None = None, ledger: bool = True
) -> Any:
    warnings: list[str] = []
    instance = SimpleNamespace(run_storage=kv or _Kv()) if ledger else None
    return SimpleNamespace(
        resources=SimpleNamespace(kor_travel_map_client=client),
        log=SimpleNamespace(info=lambda *_a, **_k: None, warning=warnings.append),
        retry_number=retry_number,
        warnings=warnings,
        instance=instance,
    )


MEMBERS: dict[str, frozenset[str] | None] = {}


@pytest.fixture
def requested(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    seen: list[Any] = []

    async def _fetch(settings: Any, requests: Any) -> dict[str, dict[str, Any]]:
        del settings
        seen.append({op: [r.content_id for r in reqs] for op, reqs in requests.items()})
        return {
            op: {r.content_id: {"usetime": "새"} for r in reqs} for op, reqs in requests.items()
        }

    async def _members(settings: Any, service: str) -> frozenset[str] | None:
        del settings
        return MEMBERS.get(service)

    monkeypatch.setattr(assets, "fetch_visitkorea_detail_ops", _fetch)
    monkeypatch.setattr(assets, "fetch_visitkorea_service_members", _members)
    MEMBERS.clear()
    MEMBERS.update({"with": frozenset({"a", "b", "c"}), "pet": frozenset({"a", "b", "c"})})
    for name in ("INTRO", "IMAGE", "PET", "ACCESSIBILITY"):
        monkeypatch.setenv(f"KOR_TRAVEL_MAP_VISITKOREA_DETAIL_{name}_DAILY_BUDGET", "1")
    return seen


async def test_asset_prioritises_scored_rows_and_keeps_stored(requested: list[Any]) -> None:
    stored = [
        SimpleNamespace(
            source_entity_id="a",
            raw_data={
                TOURAPI_DETAIL_RAW_KEY: {
                    "intro": {"modified_time": _T.isoformat(), "data": {"usetime": "저장"}}
                }
            },
        )
    ]
    client = _Client(stored, scores={"c": 12})
    records = [_tour_item(cid) for cid in ("a", "b", "c")]

    details = await assets._tourapi_detail_ops(_context(client), records, replay=False)

    assert requested == [
        {"intro": ["c"], "images": ["c"], "pet": ["c"], "accessibility": ["c"]}
    ]
    assert details["a"]["intro"]["data"] == {"usetime": "저장"}
    assert details["c"]["intro"] == {"modified_time": _T.isoformat(), "data": {"usetime": "새"}}
    assert "b" not in details  # 예산 밖


async def test_replay_and_retry_fetch_nothing(requested: list[Any]) -> None:
    client = _Client([], scores={})
    records = [_tour_item("a")]
    assert await assets._tourapi_detail_ops(_context(client), records, replay=True) == {}
    assert await assets._tourapi_detail_ops(
        _context(client, retry_number=1), records, replay=False
    ) == {}
    assert requested == []
    assert client.score_reads == 0


async def test_unreadable_priority_falls_back_without_failing(requested: list[Any]) -> None:
    client = _Client([], scores=None)
    context = _context(client)
    details = await assets._tourapi_detail_ops(context, [_tour_item("a")], replay=False)
    assert set(details) == {"a"}
    assert any("우선순위" in warning for warning in context.warnings)


async def test_daily_ledger_caps_the_second_run_of_the_same_day(requested: list[Any]) -> None:
    kv = _Kv()
    client = _Client([], scores={})
    records = [_tour_item(cid) for cid in ("a", "b")]
    await assets._tourapi_detail_ops(_context(client, kv=kv), records, replay=False)
    # 첫 run이 하루 상한(1)을 다 썼다 — 같은 날 재실행·큐 runner는 아무것도 받지 않는다.
    await assets._tourapi_detail_ops(_context(client, kv=kv), records, replay=False)
    assert requested == [{"intro": ["a"], "images": ["a"], "pet": ["a"], "accessibility": ["a"]}]
    assert sorted(v for v in kv.values.values()) == ["1", "1", "1", "1"]


async def test_member_list_failure_skips_only_that_op(requested: list[Any]) -> None:
    MEMBERS["with"] = None
    MEMBERS["pet"] = frozenset({"b"})
    client = _Client([], scores={})
    context = _context(client)
    await assets._tourapi_detail_ops(context, [_tour_item("a"), _tour_item("b")], replay=False)
    assert requested == [{"intro": ["a"], "images": ["a"], "pet": ["b"], "accessibility": []}]
    assert any("with 목록" in warning for warning in context.warnings)


async def test_missing_stored_reader_fails_closed(requested: list[Any]) -> None:
    from dagster import Failure

    with pytest.raises(Failure, match="current 원본"):
        await assets._tourapi_detail_ops(
            _context(SimpleNamespace()), [_tour_item("a")], replay=False
        )


def test_detail_common_budgets_follow_settings_with_module_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.providers.visitkorea import DATASET_KEY_VISITKOREA_FESTIVALS

    plain = KorTravelMapSettings()
    assert assets._detail_common_run_budget(plain, "visitkorea_tourist_attractions") == 850
    assert assets._detail_common_run_budget(plain, DATASET_KEY_VISITKOREA_FESTIVALS) == 50
    monkeypatch.setenv("KOR_TRAVEL_MAP_VISITKOREA_DETAIL_COMMON_FESTIVAL_BUDGET", "")
    monkeypatch.setenv("KOR_TRAVEL_MAP_VISITKOREA_DETAIL_COMMON_ATTRACTION_BUDGET", "4000")
    env = KorTravelMapSettings()
    assert env.visitkorea_detail_common_festival_budget is None  # 빈 값 = 코드 기본값
    assert assets._detail_common_run_budget(env, "visitkorea_tourist_attractions") == 4000


def test_budgets_come_from_settings() -> None:
    settings = KorTravelMapSettings(
        visitkorea_detail_intro_daily_budget=5000, visitkorea_detail_image_daily_budget=0
    )
    budgets = assets.tourapi_detail_op_budgets(settings)
    assert budgets == {"intro": 5000, "images": 0, "pet": 900, "accessibility": 900}


async def test_context_without_ledger_fetches_nothing(requested: list[Any]) -> None:
    # 큐 runner의 직접 context(instance 없음)는 하루 한도를 지킬 수 없다 — 받지 않는다.
    context = _context(_Client([], scores={}), ledger=False)
    await assets._tourapi_detail_ops(context, [_tour_item("a")], replay=False)
    assert requested == []
    assert any("장부" in warning for warning in context.warnings)
