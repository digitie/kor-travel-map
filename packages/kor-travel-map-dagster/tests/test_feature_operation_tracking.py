"""Dagster execution guard의 canonical operation membership 회귀."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from kortravelmap.core.feature_operation import (
    ProviderDatasetOperationMembership,
    TriggerKind,
)

from kortravelmap.dagster.feature_operation_tracking import (
    EXECUTION_SCOPES_TAG,
    DeclaredExecutionScope,
    FeatureOperationExecutionGuard,
    FeatureOperationGuardUnavailable,
    _guard_from_context_async,
    declared_execution_scopes,
    encode_execution_scopes,
    feature_operation_guard_resource,
    finish_tracked_feature_membership,
    resolve_run_execution_manifest,
    run_tracked_feature_asset,
)


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.memberships = (
            ProviderDatasetOperationMembership(
                provider_dataset_id=41,
                sync_scope="dataset_wide",
                operation_key="feature_place_mcst_culture_job",
            ),
        )

    async def ensure_dagster_feature_operation(self, **kwargs: Any) -> Any:
        self.calls.append(("ensure", kwargs))
        return SimpleNamespace(outcome="applied", block_reason=None)

    async def finish_dagster_feature_membership(self, **kwargs: Any) -> Any:
        self.calls.append(("finish", kwargs))
        return SimpleNamespace(outcome="applied", block_reason=None)

    async def append_dagster_feature_attempt_event(self, **kwargs: Any) -> None:
        self.calls.append(("attempt", kwargs))

    async def resolve_feature_operation_memberships(self, **kwargs: Any) -> Any:
        self.calls.append(("memberships", kwargs))
        return self.memberships


class _Instance:
    def __init__(self, run: Any) -> None:
        self.run = run

    def get_run_record_by_id(self, run_id: str) -> Any:
        assert run_id == self.run.run_id
        return SimpleNamespace(
            dagster_run=self.run,
            create_timestamp=datetime(2026, 8, 1, tzinfo=UTC),
            start_time=datetime(2026, 8, 1, 1, tzinfo=UTC).timestamp(),
        )


def _run(*, tagged: bool = True) -> Any:
    tags = (
        {
            "kor_travel_map.operation_key": "feature_place_mcst_culture_job",
            "kor_travel_map.trigger_kind": "schedule",
        }
        if tagged
        else {}
    )
    return SimpleNamespace(
        run_id="run-41",
        job_name="feature_place_mcst_culture_job",
        tags=tags,
        status=SimpleNamespace(value="STARTED"),
    )


def _guard(client: _Client) -> FeatureOperationExecutionGuard:
    run = _run()
    return FeatureOperationExecutionGuard(
        client=client,  # type: ignore[arg-type]
        instance=_Instance(run),
        operation_key="feature_place_mcst_culture_job",
        memberships=client.memberships,
        dagster_run_id=run.run_id,
        trigger_kind="schedule",
    )


def test_guard_ensures_frozen_memberships_with_operation_key() -> None:
    client = _Client()
    guard = _guard(client)

    asyncio.run(guard.ensure())

    name, call = client.calls[0]
    assert name == "ensure"
    assert call["operation_key"] == "feature_place_mcst_culture_job"
    assert call["selected_memberships"] == client.memberships


def test_single_member_wrapper_finishes_canonical_membership() -> None:
    client = _Client()
    guard = _guard(client)
    context = SimpleNamespace(
        resources=SimpleNamespace(feature_operation_guard=guard, kor_travel_map_client=client),
        instance=guard.instance,
        run=guard.instance.run,
        retry_number=0,
    )

    result = asyncio.run(run_tracked_feature_asset(context, lambda _context: _result()))

    assert result == "loaded"
    assert client.calls[-1] == (
        "finish",
        {
            "dagster_run_id": "run-41",
            "membership": client.memberships[0],
            "authoritative_snapshot_complete": False,
        },
    )


async def _result() -> str:
    return "loaded"


def _tracking_context(
    guard: FeatureOperationExecutionGuard,
    client: _Client,
) -> Any:
    return SimpleNamespace(
        resources=SimpleNamespace(feature_operation_guard=guard, kor_travel_map_client=client),
        instance=guard.instance,
        run=guard.instance.run,
        retry_number=0,
    )


def _member_pair() -> tuple[ProviderDatasetOperationMembership, ...]:
    """같은 operation에 결박된 member 2건(스키마가 허용하는 multi-member manifest)."""
    return (
        ProviderDatasetOperationMembership(
            provider_dataset_id=41,
            sync_scope="dataset_wide",
            operation_key="feature_place_mcst_culture_job",
        ),
        ProviderDatasetOperationMembership(
            provider_dataset_id=42,
            sync_scope="dataset_wide",
            operation_key="feature_place_mcst_culture_job",
        ),
    )


def test_operation_without_enabled_memberships_is_rejected_not_run_empty() -> None:
    """실행 가능 member가 0건이면 **빈 manifest로 진행하지 않고** 죽는다.

    operation이 disable되거나 dataset이 ``is_active=false``로 내려가면 canonical
    resolver가 0건을 돌려준다. 그때 그대로 진행하면 guard도 reconcile sensor도
    (둘 다 이 함수를 쓴다) member 없는 selection을 DB에 밀어 넣어, run이 아무것도
    추적하지 않은 채 성공으로 닫힌다.
    """
    client = _ManifestClient(executable=(), resolved={})

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        asyncio.run(
            resolve_run_execution_manifest(
                client,  # type: ignore[arg-type]
                operation_key="feature_place_knps_points_job",
                declared=None,
                boundary="unit",
            )
        )

    assert excinfo.value.reason == "operation_has_no_enabled_memberships"


def test_single_member_wrapper_refuses_a_manifest_that_is_not_exactly_one() -> None:
    """manifest가 1건이 아니면 single-member wrapper는 **아무것도 실행하지 않는다**.

    이 게이트가 사라지면 manifest 0건에서 ``guard.memberships[0]``이 ``IndexError``,
    2건 이상에서는 첫 member만 완료되고 나머지가 running으로 남아 terminal
    reconcile이 operation을 ``tracking_invariant``로 떨어뜨린다.
    """
    client = _Client()
    guard = _guard(client)
    two_member_guard = FeatureOperationExecutionGuard(
        client=client,  # type: ignore[arg-type]
        instance=guard.instance,
        operation_key=guard.operation_key,
        memberships=_member_pair(),
        dagster_run_id=guard.dagster_run_id,
        trigger_kind=guard.trigger_kind,
    )
    body_calls: list[object] = []

    async def _body(context: object) -> str:
        body_calls.append(context)
        return "loaded"

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        asyncio.run(
            run_tracked_feature_asset(_tracking_context(two_member_guard, client), _body)
        )

    assert excinfo.value.reason == "operation_requires_exactly_one_membership"
    assert body_calls == [], "거부해야 할 run이 asset 본문을 실행했다"
    assert "finish" not in [name for name, _call in client.calls]


def test_multi_member_callback_cannot_finish_a_member_outside_the_manifest() -> None:
    """frozen manifest 밖 member는 완료 처리되지 않는다.

    multi-member callback(MCST)이 자기가 적재한 것으로 믿는 member를 그대로 넘기는
    자리다. 여기서 걸러 내지 않으면 이 run이 실행하지도 않은 형제 member가 ``done``이
    되어, 그 member를 실제로 실행할 run과 완료 기록이 어긋난다.
    """
    client = _Client()
    guard = _guard(client)
    outsider = ProviderDatasetOperationMembership(
        provider_dataset_id=guard.memberships[0].provider_dataset_id + 1,
        sync_scope="dataset_wide",
        operation_key="feature_place_mcst_culture_job",
    )
    assert outsider not in guard.memberships

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        asyncio.run(finish_tracked_feature_membership(guard, outsider))

    assert excinfo.value.reason == "membership_not_in_frozen_selection"
    assert client.calls == [], "거부해야 할 완료가 DB 경계까지 갔다"
    # 대조: manifest 안의 member는 같은 함수로 통과한다 — 거부 사유가 "manifest 밖"임을
    # 못 박는다(전부 거부하는 것으로 미끄러져도 앞 단언만으로는 안 잡힌다).
    asyncio.run(finish_tracked_feature_membership(guard, guard.memberships[0]))
    assert [name for name, _call in client.calls] == ["finish"]


@pytest.mark.parametrize(
    ("tag_overrides", "guard_trigger_kind", "expected_reason"),
    [
        (
            {"kor_travel_map.operation_key": "feature_place_knps_points_job"},
            "schedule",
            "operation_key_mismatch",
        ),
        ({"kor_travel_map.trigger_kind": "manual"}, "schedule", "trigger_mismatch"),
    ],
)
def test_io_boundary_recheck_rejects_a_run_whose_tags_moved(
    tag_overrides: dict[str, str],
    guard_trigger_kind: str,
    expected_reason: str,
) -> None:
    """I/O 직전 재검증은 operation_key/trigger_kind 축도 대조한다.

    guard는 resource init 시점 tag로 frozen되고, 실행 직전에 살아 있는 run tag를 다시
    읽는다. 세 축(operation_key / trigger_kind / 실행 manifest 선언) 중 어느 하나라도
    빠지면 그 축이 바뀐 run이 frozen selection 그대로 진행해 DB member와 실제 실행
    대상이 갈린다. manifest 축은 통합 회귀가 잡으므로 여기서는 나머지 두 축을 건다.
    """
    client = _Client()
    guard = _guard(client)
    moved_guard = FeatureOperationExecutionGuard(
        client=client,  # type: ignore[arg-type]
        instance=guard.instance,
        operation_key=guard.operation_key,
        memberships=guard.memberships,
        dagster_run_id=guard.dagster_run_id,
        trigger_kind=cast(TriggerKind, guard_trigger_kind),
    )
    moved_guard.instance.run.tags.update(tag_overrides)
    body_calls: list[object] = []

    async def _body(context: object) -> str:
        body_calls.append(context)
        return "loaded"

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        asyncio.run(run_tracked_feature_asset(_tracking_context(moved_guard, client), _body))

    assert excinfo.value.reason == expected_reason
    assert body_calls == [], "거부해야 할 run이 asset 본문을 실행했다"
    assert client.calls == [], "거부해야 할 run이 operation을 전진시켰다"


def test_resource_init_opens_the_lifecycle_before_handing_out_the_guard() -> None:
    """resource wrapper는 guard를 만들고 **그 자리에서** lifecycle을 연다.

    통합 회귀는 ``_guard_from_context_async`` + 손으로 부른 ``guard.ensure()``만
    태우므로 이 wrapper의 ensure 결선은 그쪽에서 검증되지 않는다. 여기서 ensure가
    빠지면 run root/member 행이 provider I/O 전에 만들어지지 않아, run이 중간에
    죽었을 때 추적 레코드가 통째로 없다.
    """
    client = _Client()
    run = _run()
    loop = asyncio.new_event_loop()
    context = SimpleNamespace(
        run=run,
        instance=_Instance(run),
        resources=SimpleNamespace(kor_travel_map_client=client),
        event_loop=loop,
    )

    try:
        resource_fn = cast(Any, feature_operation_guard_resource.resource_fn)
        guard = resource_fn(context)
    finally:
        loop.close()

    assert guard.operation_key == "feature_place_mcst_culture_job"
    assert [name for name, _call in client.calls] == ["memberships", "ensure"]
    assert client.calls[-1][1]["selected_memberships"] == client.memberships


def test_resource_guard_loads_enabled_memberships_from_database() -> None:
    client = _Client()
    run = _run()
    context = SimpleNamespace(
        run=run,
        instance=_Instance(run),
        resources=SimpleNamespace(kor_travel_map_client=client),
    )

    guard = asyncio.run(_guard_from_context_async(context))

    assert guard.operation_key == "feature_place_mcst_culture_job"
    assert guard.memberships == client.memberships
    assert client.calls == [("memberships", {"operation_key": "feature_place_mcst_culture_job"})]


_MALFORMED_TAG_VALUES: tuple[str, ...] = (
    "",
    "   ",
    "not json",
    "{}",
    "[]",
    '["knps_trails"]',
    '[{"provider": "python-knps-api", "dataset_key": "knps_trails"}]',
    '[{"provider": "python-knps-api", "dataset_key": "knps_trails", "sync_scope": ""}]',
    '[{"provider": " python-knps-api", "dataset_key": "knps_trails",'
    ' "sync_scope": "dataset_wide"}]',
    '[{"provider": "python-knps-api", "dataset_key": "knps_trails", "sync_scope": 7}]',
)


@pytest.mark.parametrize("raw", _MALFORMED_TAG_VALUES)
def test_malformed_manifest_tag_is_rejected_instead_of_widening(raw: str) -> None:
    """선언 tag가 깨지면 조용히 "operation 전체"로 넓어지지 않고 죽는다.

    넓히는 쪽으로 fallback하면 guard가 실행하지도 않을 member까지 running으로 만들고,
    run이 끝난 뒤 terminal reconcile이 그 미완료 member 때문에 operation을
    ``tracking_invariant``로 떨어뜨린다. 그래서 "tag 없음"(=전체)과 "tag 깨짐"(=거부)은
    반드시 다른 결과여야 한다 — 아래 두 단언이 그 둘을 갈라 놓는다.
    """
    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        declared_execution_scopes({EXECUTION_SCOPES_TAG: raw}, boundary="unit")

    assert excinfo.value.reason == "execution_scopes_tag_malformed"
    assert excinfo.value.boundary == "unit"
    # tag가 아예 없을 때만 "operation 전체가 manifest"다.
    assert declared_execution_scopes({}, boundary="unit") is None


def test_duplicated_manifest_declaration_is_rejected() -> None:
    """같은 scope를 두 번 선언한 tag는 거부된다.

    중복을 그대로 통과시키면 manifest 길이가 실제 실행 대상 수와 달라져,
    ``_single_membership_for_asset``의 "manifest 1건" 판정이 뒤집힌다.
    """
    scope = DeclaredExecutionScope(
        provider="python-knps-api",
        dataset_key="knps_trails",
        sync_scope="dataset_wide",
    )
    raw = encode_execution_scopes((scope, scope))

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        declared_execution_scopes({EXECUTION_SCOPES_TAG: raw}, boundary="unit")

    assert excinfo.value.reason == "execution_scopes_tag_duplicated"
    # 한 번만 선언하면 통과한다 — 거부 사유가 중복 그 자체임을 못 박는다.
    assert declared_execution_scopes(
        {EXECUTION_SCOPES_TAG: encode_execution_scopes((scope,))}, boundary="unit"
    ) == (scope,)


def test_encoded_manifest_round_trips_through_the_parser() -> None:
    """``encode_execution_scopes``가 쓴 값을 ``declared_execution_scopes``가 그대로 읽는다.

    schedule/job 정의는 encode 쪽을, guard와 reconcile sensor는 parse 쪽을 쓴다.
    두 함수가 갈라지면 선언이 tag를 타고 실행 경계까지 가지 못한다.
    """
    scopes = (
        DeclaredExecutionScope(
            provider="python-kma-api",
            dataset_key="kma_short_forecast",
            sync_scope="target_grids",
        ),
        DeclaredExecutionScope(
            provider="python-knps-api",
            dataset_key="knps_park_boundaries",
            sync_scope="dataset_wide",
        ),
    )

    raw = encode_execution_scopes(scopes)

    assert declared_execution_scopes({EXECUTION_SCOPES_TAG: raw}, boundary="unit") == scopes


class _ManifestClient:
    """선언 해석에 필요한 두 resolver만 갖는 stub."""

    def __init__(
        self,
        *,
        executable: tuple[ProviderDatasetOperationMembership, ...],
        resolved: dict[tuple[str, str, str], ProviderDatasetOperationMembership],
    ) -> None:
        self._executable = executable
        self._resolved = resolved

    async def resolve_feature_operation_memberships(
        self, *, operation_key: str
    ) -> tuple[ProviderDatasetOperationMembership, ...]:
        return self._executable

    async def resolve_feature_operation_dataset_membership(
        self,
        *,
        operation_key: str,
        provider: str,
        dataset_key: str,
        sync_scope: str | None = None,
    ) -> ProviderDatasetOperationMembership:
        key = (provider, dataset_key, str(sync_scope))
        if key not in self._resolved:
            raise LookupError(key)
        return self._resolved[key]


def _member(provider_dataset_id: int) -> ProviderDatasetOperationMembership:
    return ProviderDatasetOperationMembership(
        provider_dataset_id=provider_dataset_id,
        sync_scope="dataset_wide",
        operation_key="feature_place_knps_points_job",
    )


def _scope(dataset_key: str) -> DeclaredExecutionScope:
    return DeclaredExecutionScope(
        provider="python-knps-api",
        dataset_key=dataset_key,
        sync_scope="dataset_wide",
    )


def test_manifest_is_sorted_and_deduplicated() -> None:
    """해석된 manifest는 정렬·중복제거된 canonical 형태로 나온다.

    DB 경계가 selection을 같은 형태로 정규화해 저장한다 —
    ``feature_operation_repo._memberships``가 ``tuple(sorted(set(values)))``다.
    guard가 다른 형태를 들면 guard가 들고 있는 순서와 저장된 member 순서가 갈리고,
    그 둘을 원소 단위로 나란히 놓는 통합 회귀(member 행을
    ``ORDER BY provider_dataset_id, sync_scope, operation_key``로 읽어
    ``guard.memberships``와 비교한다)가 형태 차이만으로 흔들린다.
    """
    client = _ManifestClient(
        executable=(_member(70), _member(71), _member(72)),
        resolved={
            ("python-knps-api", "knps_shelters", "dataset_wide"): _member(72),
            ("python-knps-api", "knps_restrooms", "dataset_wide"): _member(70),
        },
    )

    manifest = asyncio.run(
        resolve_run_execution_manifest(
            client,  # type: ignore[arg-type]
            operation_key="feature_place_knps_points_job",
            declared=(
                _scope("knps_shelters"),
                _scope("knps_restrooms"),
                _scope("knps_shelters"),
            ),
            boundary="unit",
        )
    )

    assert manifest == (_member(70), _member(72))


def test_declaration_absent_from_the_catalog_is_rejected() -> None:
    """카탈로그가 해석하지 못하는 선언은 거부된다 — 선언이 member를 만들어낼 수 없다."""
    client = _ManifestClient(executable=(_member(70),), resolved={})

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        asyncio.run(
            resolve_run_execution_manifest(
                client,  # type: ignore[arg-type]
                operation_key="feature_place_knps_points_job",
                declared=(_scope("knps_restrooms"),),
                boundary="unit",
            )
        )

    assert excinfo.value.reason == "execution_scope_not_in_catalog"


def test_declaration_outside_the_executable_set_is_rejected() -> None:
    """해석은 됐지만 실행 가능 집합 밖인 선언은 거부된다.

    지금 프로덕션 DB에서는 두 resolver의 SQL 술어가 같아
    (``operation.is_enabled`` + ``dataset.is_active``, ``feature_operation_repo``의
    ``_OPERATION_MEMBERSHIPS_SQL`` / ``_OPERATION_DATASET_MEMBERSHIP_SQL``) 이 분기가
    실제로 밟히지 않는다. 그래서 stub으로 두 술어가 갈라진 상태를 만들어 **그때
    manifest에 끼워 넣지 않고 거부한다**는 것을 고정한다 — 통과시키면 guard가
    실행 불가능한 member를 running으로 만든다.
    """
    client = _ManifestClient(
        executable=(_member(70),),
        resolved={("python-knps-api", "knps_shelters", "dataset_wide"): _member(72)},
    )

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        asyncio.run(
            resolve_run_execution_manifest(
                client,  # type: ignore[arg-type]
                operation_key="feature_place_knps_points_job",
                declared=(_scope("knps_shelters"),),
                boundary="unit",
            )
        )

    assert excinfo.value.reason == "execution_scope_not_executable"


def test_untagged_run_remains_panel_only_without_database_lookup() -> None:
    client = _Client()
    run = _run(tagged=False)
    context = SimpleNamespace(
        run=run,
        instance=_Instance(run),
        resources=SimpleNamespace(kor_travel_map_client=client),
    )

    guard = asyncio.run(_guard_from_context_async(context))

    assert guard.operation_key is None
    assert guard.memberships == ()
    assert client.calls == []
