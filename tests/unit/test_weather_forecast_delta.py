"""ADR-122 — weather 예보 증분(``since``) 병합이 전량 적재와 **같은 값**을 만든다(Valkey·HTTP 없이).

weather W3 ``since`` 계약(weather main ``3bcda7e``의 ``export_forecasts._page_items``·
``export_mid_reader``)을 작은 모형(:func:`_export`)으로 흉내 낸다:

- 승인 scope 하나는 ``(provider, published_at, 위치별 point)``이다. ``published_at``은 weather
  publication clock(단조)이다.
- ``since``가 있으면 ``published_at <= since``인 scope를 통째로 건너뛴다. 남은 scope는 그 위치들의
  묶음을 **전부** 다시 낸다(묶음 전체 교체 — scalar patch가 아니다).
- 응답 시각 ``now`` 이후 ``target_at``만 낸다. metric은 미래 point가 있을 때만 나온다. 미래 point가
  없는 위치는 뺀다. ``known_at``은 지난 point까지 포함한 최댓값이다.

이 모형 위에서 "직전 전량 + 증분 병합"이 "지금 전량"과 바이트까지 같은지 본다. weather가
**알리지 않는** 제거(위치가 scope에서 빠짐·승인 만료·provider 퇴역)는 증분으로 볼 수 없다 —
:func:`test_removal_is_invisible_to_a_delta_and_only_a_full_resync_heals_it`가 그 한계를 고정한다.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

import pytest

from kortravelmap.dto.weather_state import WeatherForecastGroupState, WeatherForecastState
from kortravelmap.infra.valkey_state import StateItem
from kortravelmap.providers.kor_travel_weather import (
    WeatherExportForecastGroup,
    WeatherExportForecastMember,
)
from kortravelmap.providers.kor_travel_weather_state import (
    ForecastDeltaRefused,
    ForecastGrouper,
    forecast_membership_digest,
    merge_forecast_delta,
    trim_forecast_group,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Point:
    location_id: str
    metric: str
    target: datetime
    value: float | str
    known: datetime


@dataclass
class _Scope:
    provider: str
    published_at: datetime
    points: list[_Point] = field(default_factory=list)

    @property
    def locations(self) -> set[str]:
        return {p.location_id for p in self.points}


def _export(
    scopes: list[_Scope], now: datetime, since: datetime | None = None, *, style: str = "short"
) -> list[WeatherExportForecastGroup]:
    """weather W3 응답 항목(페이지를 이어 붙인 것)."""
    out: list[WeatherExportForecastGroup] = []
    for scope in scopes:
        if since is not None and scope.published_at <= since:
            continue
        by_location: dict[str, list[_Point]] = defaultdict(list)
        for point in scope.points:
            by_location[point.location_id].append(point)
        for location_id in sorted(by_location):
            points = by_location[location_id]
            future = [p for p in points if p.target > now]
            if not future:
                continue
            targets = sorted({p.target for p in future})
            metrics: dict[str, dict[datetime, float | str]] = defaultdict(dict)
            for point in future:
                metrics[point.metric][point.target] = point.value
            out.append(
                WeatherExportForecastGroup(
                    location_id=location_id,
                    provider=scope.provider,
                    forecast_style=style,  # type: ignore[arg-type]
                    known_at=max(p.known for p in points),
                    published_at=scope.published_at,
                    target_at=targets,
                    metrics={
                        name: [values.get(t) for t in targets]
                        for name, values in sorted(metrics.items())
                    },
                )
            )
    return out


def _omitted(
    scopes: list[_Scope], now: datetime, since: datetime | None = None
) -> list[WeatherExportForecastMember]:
    """weather ``meta.omitted_expired`` — 걸은 scope에서 미래 point가 없어 뺀 (위치, provider)."""
    return [
        WeatherExportForecastMember(
            location_id=location_id, provider=scope.provider, published_at=scope.published_at
        )
        for scope in scopes
        if since is None or scope.published_at > since
        for location_id in sorted(scope.locations)
        if not any(p.target > now for p in scope.points if p.location_id == location_id)
    ]


def _full(scopes: list[_Scope], now: datetime) -> list[StateItem]:
    grouper = ForecastGrouper(style="short")
    for group in _export(scopes, now):
        grouper.add(group)
    return grouper.items()


Members = dict[tuple[str, str], datetime]


def _manifest_digest(scopes: list[_Scope]) -> str:
    """weather ``meta.membership_digest`` — 얼린 manifest 전체(시간 필터 전, since 무관)."""
    return forecast_membership_digest(
        {(loc, s.provider): s.published_at for s in scopes for loc in s.locations}
    )


def _full_ledger(scopes: list[_Scope], now: datetime) -> tuple[list[StateItem], Members]:
    grouper = ForecastGrouper(style="short")
    for group in _export(scopes, now):
        grouper.add(group)
    members = grouper.members()
    for member in _omitted(scopes, now):  # 값 없는 멤버(Dagster 수집기와 같은 규칙)
        members[(member.location_id, member.provider)] = member.published_at
    return grouper.items(), members


def _merge_ledger(
    base: list[StateItem], ledger: Members, scopes: list[_Scope], since: datetime, now: datetime
) -> tuple[list[StateItem], Members]:
    merge = merge_forecast_delta(
        _states(base), _export(scopes, now, since), style="short", since=since, now=now,
        base_members=ledger, omitted=_omitted(scopes, now, since),
    )
    return merge.items, merge.members


def _states(items: list[StateItem]) -> list[WeatherForecastState]:
    return [WeatherForecastState.model_validate_json(item.value) for item in items]


def _canonical(items: list[StateItem]) -> dict[str, str]:
    """id → 저장 값 JSON. 저장되는 바이트 그대로 비교한다."""
    values = {item.id: item.value for item in items}
    assert len(values) == len(items)
    return values


def _merge(
    base: list[StateItem], scopes: list[_Scope], since: datetime, now: datetime
) -> list[StateItem]:
    return merge_forecast_delta(
        _states(base), _export(scopes, now, since), style="short", since=since, now=now,
        omitted=_omitted(scopes, now, since),
    ).items


def _points(
    location_id: str,
    hours: range,
    *,
    at: datetime,
    known: datetime,
    metrics: dict[str, float | str] | None = None,
) -> list[_Point]:
    metrics = metrics or {"TMP": 10.0, "SKY": "맑음"}
    return [
        _Point(location_id, name, at + timedelta(hours=h), value, known)
        for h in hours
        for name, value in metrics.items()
    ]


# -- 정해진 시나리오 ------------------------------------------------------------------------


def test_delta_merge_equals_a_full_pull_through_republish_expiry_and_new_scopes() -> None:
    w0 = T0
    a = _Scope("python-kma-api", w0, _points("L1", range(6), at=T0, known=T0))
    a.points += _points("L2", range(6), at=T0, known=T0)
    b = _Scope("open_meteo", w0 - timedelta(minutes=1), _points("L1", range(6), at=T0, known=T0))
    c = _Scope("python-kma-api", w0, _points("L3", range(1, 2), at=T0, known=T0))
    now0 = T0 + timedelta(minutes=30)
    base = _full([a, b, c], now0)
    assert {s.location_id for s in _states(base)} == {"L1", "L2", "L3"}

    # weather 쪽 변화(모두 since 이후 공개):
    w1 = w0 + timedelta(hours=3)
    # ① a 재공개 — L1은 metric 하나(SKY)가 사라지고 시각이 바뀌고, L4가 같은 scope에 더해진다.
    a2 = _Scope(
        "python-kma-api",
        w1,
        _points("L1", range(3, 9), at=T0, known=w1, metrics={"TMP": 7.5})
        + _points("L2", range(3, 9), at=T0, known=w1)
        + _points("L4", range(3, 5), at=T0, known=w1),
    )
    # ② 새 provider scope가 L2에 생긴다.
    d = _Scope("met_norway", w1, _points("L2", range(2, 4), at=T0, known=w1))
    # b(open_meteo)는 그대로 — 시각만 지나 앞쪽이 잘린다. c(L3)는 모든 시각이 지나 빠진다.
    now1 = T0 + timedelta(hours=2, minutes=30)
    scopes1 = [a2, b, c, d]

    merged = _merge(base, scopes1, since=w0, now=now1)
    assert _canonical(merged) == _canonical(_full(scopes1, now1))
    by_location = {s.location_id: s for s in _states(merged)}
    assert set(by_location) == {"L1", "L2", "L4"}  # L3는 모든 시각이 지나 빠졌다
    assert [g.provider for g in by_location["L2"].groups] == ["met_norway", "python-kma-api"]
    l1 = {g.provider: g for g in by_location["L1"].groups}
    assert set(l1["python-kma-api"].metrics) == {"TMP"}  # 사라진 metric이 남지 않는다
    assert l1["open_meteo"].target_at == [T0 + timedelta(hours=h) for h in (3, 4, 5)]


def test_a_metric_whose_future_points_all_passed_disappears_like_in_a_full_pull() -> None:
    # TMP는 0~5시, POP는 0시에만 있다. 1시 반이 되면 POP는 미래 point가 없어 weather가 내지 않는다.
    scope = _Scope(
        "python-kma-api",
        T0,
        _points("L1", range(6), at=T0, known=T0, metrics={"TMP": 1.0})
        + _points("L1", range(1), at=T0, known=T0, metrics={"POP": 30.0}),
    )
    base = _full([scope], T0 - timedelta(minutes=1))
    assert set(_states(base)[0].groups[0].metrics) == {"TMP", "POP"}
    now = T0 + timedelta(hours=1, minutes=30)
    merged = _merge(base, [scope], since=T0, now=now)  # 빈 증분
    assert _canonical(merged) == _canonical(_full([scope], now))
    assert set(_states(merged)[0].groups[0].metrics) == {"TMP"}


def test_target_exactly_at_now_is_dropped_like_weather() -> None:
    scope = _Scope("p", T0, _points("L1", range(3), at=T0, known=T0))
    base = _full([scope], T0 - timedelta(minutes=1))
    now = T0 + timedelta(hours=1)  # weather는 target_at > now만 낸다
    merged = _merge(base, [scope], since=T0, now=now)
    assert _canonical(merged) == _canonical(_full([scope], now))
    assert _states(merged)[0].groups[0].target_at == [T0 + timedelta(hours=2)]


def test_a_chain_of_deltas_equals_a_full_pull() -> None:
    scopes = [
        _Scope("p", T0, _points("L1", range(48), at=T0, known=T0)),
        _Scope("q", T0, _points("L2", range(48), at=T0, known=T0)),
    ]
    now = T0 + timedelta(minutes=10)
    state, ledger = _full_ledger(scopes, now)
    since = T0
    for step in range(1, 6):
        clock = T0 + timedelta(hours=3 * step)
        scopes[step % 2] = _Scope(
            scopes[step % 2].provider,
            clock,
            _points(f"L{step % 2 + 1}", range(3 * step, 3 * step + 40), at=T0, known=clock,
                    metrics={"TMP": float(step)}),
        )
        now = clock + timedelta(minutes=20)
        state, ledger = _merge_ledger(state, ledger, scopes, since=since, now=now)
        since = clock
        assert _canonical(state) == _canonical(_full(scopes, now))
        # 시각이 지나 값에서 빠진 묶음도 멤버십에는 남는다 — weather digest(시간 필터 전)와 같다.
        assert forecast_membership_digest(ledger) == _manifest_digest(scopes), step


# -- 무작위 시나리오(계약이 표현하는 변화만) ---------------------------------------------


_PROVIDERS = ("python-kma-api", "open_meteo", "met_norway")
_LOCATIONS = tuple(f"L{i:02d}" for i in range(12))
_METRICS = ("TMP", "POP", "SKY", "REH")


def _random_points(
    rng: random.Random, locations: set[str], clock: datetime, now: datetime
) -> list[_Point]:
    points: list[_Point] = []
    start = now - timedelta(hours=2)
    for location_id in sorted(locations):
        metrics = rng.sample(_METRICS, rng.randint(1, len(_METRICS)))
        for half_hours in sorted(rng.sample(range(120), rng.randint(1, 12))):
            target = start + timedelta(minutes=30 * half_hours)
            for metric in metrics:
                if rng.random() < 0.8:
                    value: float | str = (
                        "맑음" if metric == "SKY" else round(rng.uniform(-10, 40), 1)
                    )
                    points.append(_Point(location_id, metric, target, value, clock))
        # 위치마다 point가 하나는 있다(scope에서 빠지는 제거는 계약 밖 시험이 따로 본다). 그 시각이
        # 지났으면 weather가 omitted_expired로 알린다(재공개됐지만 미래 시각 없음 — 계약 5(e)).
        at = now + timedelta(minutes=30 * rng.randint(-6, 8))
        points.append(_Point(location_id, "TMP", at, round(rng.uniform(-10, 40), 1), clock))
    return points


@pytest.mark.parametrize("seed", range(40))
def test_random_republish_growth_and_time_keep_delta_equal_to_full(seed: int) -> None:
    rng = random.Random(seed)
    clock = T0
    now = T0
    # provider마다 위치는 scope 하나에만 속한다(weather inventory 규약 —
    # 같은 위치·provider 중복 없음).
    scopes: list[_Scope] = []
    owned: dict[str, set[str]] = {p: set() for p in _PROVIDERS}
    for provider in _PROVIDERS:
        for _ in range(rng.randint(1, 3)):
            free = sorted(set(_LOCATIONS) - owned[provider])
            if not free:
                break
            locations = set(rng.sample(free, rng.randint(1, min(4, len(free)))))
            owned[provider] |= locations
            scopes.append(_Scope(provider, clock, _random_points(rng, locations, clock, now)))
    state, ledger = _full_ledger(scopes, now)
    assert forecast_membership_digest(ledger) == _manifest_digest(scopes)
    since = clock
    for _ in range(8):
        clock += timedelta(minutes=rng.randint(1, 240))
        # 시계는 거꾸로 가지 않는다(앞 step의 now가 이번 clock보다 늦을 수 있다).
        now = max(now, clock + timedelta(minutes=rng.choice((0, 30, 60, 90))))
        for index, scope in enumerate(scopes):
            if rng.random() < 0.35:
                grow = set()
                free = sorted(set(_LOCATIONS) - owned[scope.provider])
                if free and rng.random() < 0.3:
                    grow = {rng.choice(free)}
                    owned[scope.provider] |= grow
                scopes[index] = _Scope(
                    scope.provider,
                    clock,
                    _random_points(rng, scope.locations | grow, clock, now),
                )
        provider = rng.choice(_PROVIDERS)
        free = sorted(set(_LOCATIONS) - owned[provider])
        if free and rng.random() < 0.3:
            locations = {rng.choice(free)}
            owned[provider] |= locations
            scopes.append(_Scope(provider, clock, _random_points(rng, locations, clock, now)))
        state, ledger = _merge_ledger(state, ledger, scopes, since=since, now=now)
        since = clock
        assert _canonical(state) == _canonical(_full(scopes, now))
        assert forecast_membership_digest(ledger) == _manifest_digest(scopes)


# -- 계약 밖: 알리지 않는 제거 ---------------------------------------------------------


def test_removal_is_invisible_to_a_delta_and_only_a_full_resync_heals_it() -> None:
    """weather는 since 응답에 tombstone을 싣지 않는다(W-MAP-08 미구현). 위치가 scope에서 빠지거나
    승인이 만료돼 전량에서 사라져도 증분에는 아무 흔적이 없다 — 주기 전량 재동기화가 고친다."""
    keep = _Scope("p", T0, _points("L1", range(24), at=T0, known=T0))
    gone = _Scope("q", T0, _points("L2", range(24), at=T0, known=T0))
    base = _full([keep, gone], T0)
    now = T0 + timedelta(hours=1)
    merged = _merge(base, [keep], since=T0, now=now)  # q가 만료·퇴역으로 전량에서 빠졌다
    full = _full([keep], now)
    assert _canonical(merged) != _canonical(full)
    assert {s.location_id for s in _states(merged)} == {"L1", "L2"}
    assert {s.location_id for s in _states(full)} == {"L1"}
    # weather membership digest가 그 제거를 드러낸다(ADR-122 — membership_mismatch → 전량).
    _, ledger = _merge_ledger(*_full_ledger([keep, gone], T0), [keep], since=T0, now=now)
    assert forecast_membership_digest(ledger) != _manifest_digest([keep])


def test_republish_without_future_points_is_reported_as_omitted_expired() -> None:
    """재공개된 scope에서 미래 시각이 하나도 없는 위치는 항목에서 빠지고 ``omitted_expired``로 온다.
    병합은 지금 세대의 옛 묶음을 빼고 장부에 새 ``published_at``을 남긴다 — 전량과 같다
    (계약 5(e))."""
    old = _Scope("p", T0, _points("L1", range(1, 24), at=T0, known=T0))
    base, ledger = _full_ledger([old], T0)
    now = T0 + timedelta(minutes=30)
    republished = _Scope(
        "p", T0 + timedelta(minutes=10), _points("L1", range(-3, 0), at=T0, known=now)
    )
    assert _export([republished], now, since=T0) == []
    items, merged = _merge_ledger(base, ledger, [republished], since=T0, now=now)
    assert _canonical(items) == _canonical(_full([republished], now)) == {}
    assert merged == {("L1", "p"): T0 + timedelta(minutes=10)}
    assert forecast_membership_digest(merged) == _manifest_digest([republished])


def test_full_pull_counts_omitted_rows_as_value_less_members() -> None:
    live = _Scope("p", T0, _points("L1", range(1, 24), at=T0, known=T0))
    stale = _Scope("q", T0, _points("L2", range(-5, -1), at=T0, known=T0))
    items, ledger = _full_ledger([live, stale], T0)
    assert {s.location_id for s in _states(items)} == {"L1"}
    assert ledger == {("L1", "p"): T0, ("L2", "q"): T0}
    assert forecast_membership_digest(ledger) == _manifest_digest([live, stale])


def test_omitted_member_overlapping_an_item_is_refused() -> None:
    later = T0 + timedelta(hours=1)
    member = WeatherExportForecastMember(location_id="L1", provider="p", published_at=later)
    with pytest.raises(ForecastDeltaRefused) as excinfo:
        merge_forecast_delta(
            [], [_group("L1", "p", later)], style="short", since=T0, now=T0, omitted=[member]
        )
    assert excinfo.value.reason == "delta_duplicates"


def test_expired_carried_group_stays_in_the_membership() -> None:
    scope = _Scope("p", T0, _points("L1", range(1, 3), at=T0, known=T0))
    base, ledger = _full_ledger([scope], T0)
    now = T0 + timedelta(hours=5)
    items, merged = _merge_ledger(base, ledger, [scope], since=T0, now=now)
    assert items == []
    assert merged == {("L1", "p"): T0}


def test_membership_digest_follows_the_weather_definition() -> None:
    import hashlib
    import json

    kst = timezone(timedelta(hours=9))
    members = {
        ("서울-1", "python-kma-api"): datetime(2026, 11, 11, 1, 2, 3, 45, tzinfo=UTC),
        ("A", "open_meteo"): datetime(2026, 11, 11, 19, 0, tzinfo=kst),  # UTC로 바꿔 적는다
    }
    body = json.dumps(
        [
            ["A", "open_meteo", "2026-11-11T10:00:00.000000Z"],
            ["서울-1", "python-kma-api", "2026-11-11T01:02:03.000045Z"],
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    expected = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert forecast_membership_digest(members) == expected


# -- 거부(증분을 버리고 전량으로) -----------------------------------------------------------


def _group(location_id: str, provider: str, published_at: datetime) -> WeatherExportForecastGroup:
    return WeatherExportForecastGroup(
        location_id=location_id,
        provider=provider,
        forecast_style="short",
        known_at=published_at,
        published_at=published_at,
        target_at=[T0 + timedelta(days=1)],
        metrics={"TMP": [1.0]},
    )


def test_duplicate_location_provider_in_a_delta_is_refused() -> None:
    since = T0
    later = T0 + timedelta(hours=1)
    with pytest.raises(ForecastDeltaRefused) as excinfo:
        merge_forecast_delta(
            [], [_group("L1", "p", later), _group("L1", "p", later)],
            style="short", since=since, now=later,
        )
    assert excinfo.value.reason == "delta_duplicates"


def test_delta_row_published_at_or_before_since_is_refused() -> None:
    with pytest.raises(ForecastDeltaRefused) as excinfo:
        merge_forecast_delta(
            [], [_group("L1", "p", T0)], style="short", since=T0, now=T0
        )
    assert excinfo.value.reason == "delta_not_after_since"


def test_delta_older_than_the_stored_group_is_refused() -> None:
    newer = T0 + timedelta(hours=2)
    base = _full([_Scope("p", newer, _points("L1", range(30, 40), at=T0, known=newer))], T0)
    with pytest.raises(ForecastDeltaRefused) as excinfo:
        merge_forecast_delta(
            _states(base),
            [_group("L1", "p", T0 + timedelta(hours=1))],
            style="short",
            since=T0,
            now=T0,
        )
    assert excinfo.value.reason == "published_at_regressed"


def test_base_of_another_style_is_refused() -> None:
    base = _states(_full([_Scope("p", T0, _points("L1", range(30, 40), at=T0, known=T0))], T0))
    with pytest.raises(ForecastDeltaRefused) as excinfo:
        merge_forecast_delta(base, [], style="mid", since=T0, now=T0)
    assert excinfo.value.reason == "base_mismatch"


def test_trim_keeps_an_untrimmed_group_as_is() -> None:
    group = WeatherForecastGroupState(
        provider="p",
        known_at=T0,
        published_at=T0,
        target_at=[T0 + timedelta(hours=1)],
        metrics={"TMP": [None]},
    )
    # 잘린 시각이 없으면 null만 남은 metric도 그대로다(weather가 그 null point를 냈다).
    assert trim_forecast_group(group, T0) is group
    assert trim_forecast_group(group, T0 + timedelta(hours=1)) is None
