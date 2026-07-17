"""Dagster 운영 요약 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from kortravelmap.api import dagster_graphql as dagster_mod
from kortravelmap.api import dagster_query_service as dagster_query
from kortravelmap.api import dagster_schedule_service as dagster_schedule
from kortravelmap.api.app import create_app
from kortravelmap.api.dagster_http import schedule_idempotency_http_exception
from kortravelmap.api.dagster_schema import (
    DagsterScheduleCommandData,
    DagsterScheduleCommandResponse,
)
from kortravelmap.api.routers import dagster as dagster_router
from kortravelmap.api.settings import ApiSettings


@pytest.mark.unit
def test_resolved_schedule_idempotency_conflict_is_confirmed() -> None:
    command_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    error = schedule_idempotency_http_exception(
        dagster_schedule.DagsterScheduleIdempotencyConflict(
            "운영자 확인으로 이미 해제됨",
            command_id=command_id,
            resolved=True,
            resolution="confirmed_not_applied",
        )
    )

    assert error.status_code == 409
    assert error.detail["code"] == "DAGSTER_SCHEDULE_CLAIM_RESOLVED"
    assert error.detail["details"] == {
        "command_id": str(command_id),
        "active_command_id": None,
        "active_claim_resolvable_at": None,
        "outcome_certainty": "confirmed",
        "audit_status": "recorded",
        "resolution": "confirmed_not_applied",
    }


@pytest.mark.unit
def test_schedule_url_error_redacts_invalid_configuration_secrets() -> None:
    data = dagster_schedule._schedule_url_error(
        checked_at=datetime(2026, 7, 17, tzinfo=UTC),
        schedule_name="safe_schedule",
        command="run",
        error=dagster_mod.DagsterUrlConfigurationError(
            "dagster_graphql_url must not include userinfo"
        ),
    )

    assert data.dagster_url == ""
    assert data.graphql_url == ""
    assert "secret" not in data.model_dump_json()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    app = create_app(
        ApiSettings(
            dagster_url="http://dagster.example:12302",
            dagster_allowed_hosts=["dagster.example"],
            dagster_request_timeout_seconds=1.0,
        )
    )

    async def _empty_schedule_overrides(_session: object) -> dict[str, str]:
        return {}

    monkeypatch.setattr(
        dagster_schedule,
        "schedule_overrides",
        _empty_schedule_overrides,
    )
    with TestClient(app) as test_client:
        yield test_client


def _malformed_run_detail_payload(case: str) -> dict[str, object]:
    event_connection: object = {
        "cursor": None,
        "hasMore": False,
        "events": [],
    }
    run: dict[str, object] = {
        "__typename": "Run",
        "runId": "run-1",
        "status": "SUCCESS",
        "tags": [],
        "eventConnection": event_connection,
    }
    if case == "missing_run_id":
        run.pop("runId")
    elif case == "empty_run_id":
        run["runId"] = ""
    elif case == "mismatched_run_id":
        run["runId"] = "other-run"
    elif case == "non_object_connection":
        run["eventConnection"] = []
    elif case == "missing_events":
        assert isinstance(event_connection, dict)
        event_connection.pop("events")
    elif case == "non_boolean_has_more":
        assert isinstance(event_connection, dict)
        event_connection["hasMore"] = "false"
    elif case == "non_list_events":
        assert isinstance(event_connection, dict)
        event_connection["events"] = {}
    elif case == "non_string_cursor":
        assert isinstance(event_connection, dict)
        event_connection["cursor"] = 1
    elif case == "missing_next_cursor":
        assert isinstance(event_connection, dict)
        event_connection["hasMore"] = True
    elif case == "empty_next_cursor":
        assert isinstance(event_connection, dict)
        event_connection.update({"cursor": "", "hasMore": True})
    elif case == "oversized_next_cursor":
        assert isinstance(event_connection, dict)
        event_connection.update({"cursor": "c" * 2049, "hasMore": True})
    else:  # pragma: no cover - 테스트 파라미터 오타 방어
        raise AssertionError(f"unknown malformed case: {case}")
    return {"data": {"runOrError": run}}


@pytest.mark.unit
def test_dagster_summary_parses_graphql_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_query._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        assert graphql_url == "http://dagster.example:12302/graphql"
        calls.append({"query": query, "variables": variables})
        assert query == dagster_query._DAGSTER_SUMMARY_QUERY
        assert variables == {"limit": 3}
        return {
            "data": {
                "version": "1.13.7",
                "repositoriesOrError": {
                    "__typename": "RepositoryConnection",
                    "nodes": [
                        {
                            "name": "__repository__",
                            "location": {
                                "name": "kortravelmap.dagster.definitions",
                            },
                            "pipelines": [{"name": "__ASSET_JOB", "isJob": True}],
                            "schedules": [
                                {
                                    "name": "nightly_feature_refresh",
                                    "cronSchedule": "0 2 * * *",
                                    "executionTimezone": "Asia/Seoul",
                                    "scheduleState": {
                                        "status": "RUNNING",
                                        "ticks": [
                                            {
                                                "tickId": "schedule-tick-1",
                                                "status": "SUCCESS",
                                                "timestamp": 1710000000.0,
                                                "endTimestamp": 1710000010.0,
                                                "runIds": ["run-1"],
                                                "runKeys": ["nightly"],
                                                "skipReason": None,
                                                "cursor": "cursor-1",
                                                "error": None,
                                            }
                                        ],
                                    },
                                }
                            ],
                            "sensors": [
                                {
                                    "name": "provider_failure_sensor",
                                    "sensorState": {
                                        "status": "STOPPED",
                                        "ticks": [
                                            {
                                                "tickId": "sensor-tick-1",
                                                "status": "FAILURE",
                                                "timestamp": 1710000200.0,
                                                "endTimestamp": None,
                                                "runIds": [],
                                                "runKeys": [],
                                                "skipReason": None,
                                                "cursor": None,
                                                "error": {
                                                    "message": "sensor failed",
                                                    "stack": ["frame 1"],
                                                    "className": "SensorFailure",
                                                },
                                            }
                                        ],
                                    },
                                }
                            ],
                            "assetNodes": [
                                {
                                    "id": "asset-1",
                                    "groupName": "features_place",
                                    "assetKey": {
                                        "path": ["feature_place_mois_licenses"]
                                    },
                                },
                                {
                                    "id": "asset-2",
                                    "groupName": "features_event",
                                    "assetKey": {
                                        "path": [
                                            "feature_event_datagokr_cultural_festivals"
                                        ]
                                    },
                                },
                            ],
                        }
                    ],
                },
                "runsOrError": {
                    "__typename": "Runs",
                    "results": [
                        {
                            "runId": "run-1",
                            "jobName": "__ASSET_JOB",
                            "status": "SUCCESS",
                            "startTime": 1.0,
                            "endTime": 2.0,
                            "updateTime": 2.0,
                            "tags": [{"key": "dagster/job", "value": "__ASSET_JOB"}],
                        }
                    ],
                },
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/summary?page_size=3")

    assert response.status_code == 200
    body = response.json()
    assert "duration_ms" in body["meta"]
    data = body["data"]
    assert data["status"] == "ok"
    assert data["dagster_url"] == "http://dagster.example:12302"
    assert data["graphql_url"] == "http://dagster.example:12302/graphql"
    assert data["version"] == "1.13.7"
    assert data["repository_count"] == 1
    assert data["job_count"] == 1
    assert data["asset_count"] == 2
    assert data["schedule_count"] == 1
    assert data["sensor_count"] == 1
    assert data["run_counts"] == {"SUCCESS": 1}
    repository = data["repositories"][0]
    assert repository["schedules"][0]["effective_cron_schedule"] == "0 2 * * *"
    assert repository["schedules"][0]["override_saved"] is False
    assert repository["schedules"][0]["override_effective"] is None
    assert repository["schedules"][0]["can_run_now"] is False
    assert repository["schedules"][0]["disabled_reason"] == (
        "schedule job 이름이 없습니다."
    )
    assert repository["schedules"][0]["recent_ticks"] == [
        {
            "tick_id": "schedule-tick-1",
            "status": "SUCCESS",
            "timestamp": 1710000000.0,
            "end_timestamp": 1710000010.0,
            "run_ids": ["run-1"],
            "run_keys": ["nightly"],
            "skip_reason": None,
            "cursor": "cursor-1",
            "error": None,
        }
    ]
    assert repository["sensors"][0]["recent_ticks"][0]["error"] == {
        "message": "sensor failed",
        "stack": ["frame 1"],
        "class_name": "SensorFailure",
    }
    assert data["repositories"][0]["asset_groups"] == [
        {
            "group_name": "features_event",
            "asset_count": 1,
            "assets": ["feature_event_datagokr_cultural_festivals"],
            "asset_items": [
                {
                    "name": "feature_event_datagokr_cultural_festivals",
                    "display_name": "전국 문화축제",
                }
            ],
        },
        {
            "group_name": "features_place",
            "asset_count": 1,
            "assets": ["feature_place_mois_licenses"],
            "asset_items": [
                    {
                        "name": "feature_place_mois_licenses",
                        "display_name": "인허가 장소",
                    }
            ],
        },
    ]
    assert data["recent_runs"][0]["run_id"] == "run-1"
    assert calls == [
        {"query": dagster_query._DAGSTER_SUMMARY_QUERY, "variables": {"limit": 3}},
    ]


@pytest.mark.unit
def test_dagster_schedule_write_contract_has_no_client_actor(
    client: TestClient,
) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert set(schemas["DagsterScheduleOverrideRequest"]["properties"]) == {
        "cron_schedule",
        "reason",
    }
    assert set(schemas["DagsterScheduleCommandRequest"]["properties"]) == {
        "reason"
    }


@pytest.mark.unit
def test_legacy_schedule_command_uses_server_actor_and_idempotency_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_audited_command(
        _session: object,
        **kwargs: object,
    ) -> DagsterScheduleCommandResponse:
        captured.update(kwargs)
        return DagsterScheduleCommandResponse(
            data=DagsterScheduleCommandData(
                status="ok",
                dagster_url="http://dagster.example:12302",
                graphql_url="http://dagster.example:12302/graphql",
                checked_at=datetime.now(UTC),
                schedule_name="weather_daily",
                command="start",
                effective_cron_schedule="0 6 * * *",
                schedule_status="RUNNING",
                save_status="not_applicable",
                reload_status="not_requested",
                effective_status="confirmed",
            ),
            meta={"duration_ms": 0, "request_id": "unit"},
        )

    monkeypatch.setattr(
        dagster_router,
        "_execute_audited_command",
        _fake_audited_command,
    )
    command_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    response = client.post(
        "/v1/ops/dagster/schedules/weather_daily/start",
        headers={"Idempotency-Key": command_id},
        json={"reason": "운영 재개"},
    )

    assert response.status_code == 200
    assert captured["actor"] == "local-dev"
    assert captured["reason"] == "운영 재개"
    assert captured["request_details"] == {"command": "start"}
    assert captured["command_id"] == UUID(command_id)

    spoofed = client.post(
        "/v1/ops/dagster/schedules/weather_daily/start",
        headers={"Idempotency-Key": command_id},
        json={"operator": "spoofed"},
    )
    assert spoofed.status_code == 422


@pytest.mark.unit
def test_dagster_run_detail_parses_graphql_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_query._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        assert graphql_url == "http://dagster.example:12302/graphql"
        calls.append({"query": query, "variables": variables})
        assert query == dagster_query._DAGSTER_RUN_DETAIL_QUERY
        assert variables == {
            "runId": "run-1",
            "eventLimit": 5,
            "afterCursor": None,
        }
        return {
            "data": {
                "runOrError": {
                    "__typename": "Run",
                    "runId": "run-1",
                    "jobName": "__ASSET_JOB",
                    "status": "FAILURE",
                    "startTime": 1710000000.0,
                    "endTime": 1710000030.0,
                    "updateTime": 1710000030.0,
                    "tags": [{"key": "dagster/job", "value": "__ASSET_JOB"}],
                    "eventConnection": {
                        "cursor": "event-cursor-1",
                        "hasMore": True,
                        "events": [
                            {
                                "__typename": "StepStartEvent",
                                "message": "step started",
                                "timestamp": "1710000001.0",
                                "level": "INFO",
                                "stepKey": "load_features",
                                "eventType": "STEP_START",
                            },
                            {
                                "__typename": "RunFailureEvent",
                                "message": "run failed",
                                "timestamp": "1710000030.0",
                                "level": "ERROR",
                                "stepKey": None,
                                "eventType": "RUN_FAILURE",
                                "error": {
                                    "message": "boom",
                                    "stack": ["traceback"],
                                    "className": "RuntimeError",
                                },
                            },
                        ],
                    },
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/runs/run-1?page_size=5")

    assert response.status_code == 200
    body = response.json()
    assert "duration_ms" in body["meta"]
    data = body["data"]
    assert data["status"] == "ok"
    assert data["dagster_url"] == "http://dagster.example:12302"
    assert data["graphql_url"] == "http://dagster.example:12302/graphql"
    assert data["run"]["run_id"] == "run-1"
    assert data["run"]["status"] == "FAILURE"
    assert data["event_cursor"] == "event-cursor-1"
    assert data["event_has_more"] is True
    assert data["events"][0]["dagster_event_type"] == "STEP_START"
    assert data["events"][1]["error"] == {
        "message": "boom",
        "stack": ["traceback"],
        "class_name": "RuntimeError",
    }
    assert data["failure_reason"] == "RuntimeError: boom"
    assert data["failure_events"] == [
        {
            "event_type": "RunFailureEvent",
            "message": "RuntimeError: boom",
            "timestamp": "1710000030.0",
            "level": "ERROR",
            "step_id": None,
            "dagster_event_type": "RUN_FAILURE",
            "error": {
                "message": "boom",
                "stack": ["traceback"],
                "class_name": "RuntimeError",
            },
        }
    ]
    assert calls == [
        {
            "query": dagster_query._DAGSTER_RUN_DETAIL_QUERY,
            "variables": {"runId": "run-1", "eventLimit": 5, "afterCursor": None},
        },
    ]


@pytest.mark.unit
def test_dagster_run_detail_returns_not_found(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_query._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        return {
            "data": {
                "runOrError": {
                    "__typename": "RunNotFoundError",
                    "message": "Run not found",
                    "runId": "missing-run",
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/runs/missing-run")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "not_found"
    assert data["run"] is None
    assert data["events"] == []
    assert data["errors"] == ["Run not found"]


@pytest.mark.unit
def test_dagster_run_detail_passes_after_cursor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``after`` 쿼리파라미터가 GraphQL ``afterCursor`` 변수로 전달돼야 한다(긴 run
    뒤쪽 실패 이벤트로 전진 페이지네이션, #291 리뷰)."""
    seen: list[dict[str, object]] = []

    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_query._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        seen.append(variables)
        return {
            "data": {
                "runOrError": {
                    "__typename": "Run",
                    "runId": "run-1",
                    "status": "FAILURE",
                    "tags": [],
                    "eventConnection": {"cursor": None, "hasMore": False, "events": []},
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/runs/run-1?page_size=5&after=ev-cursor-80")

    assert response.status_code == 200
    assert seen == [{"runId": "run-1", "eventLimit": 5, "afterCursor": "ev-cursor-80"}]


@pytest.mark.unit
def test_dagster_run_detail_graphql_error_extracts_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GraphQL top-level errors는 dict repr이 아니라 message만 노출돼야 한다(#291 리뷰)."""

    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_query._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        return {
            "errors": [
                {
                    "message": "Field 'bogus' doesn't exist",
                    "locations": [{"line": 3, "column": 5}],
                    "path": ["runOrError"],
                }
            ]
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/runs/run-1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "error"
    assert data["errors"] == ["Field 'bogus' doesn't exist"]
    # dict repr(파이썬 표현)이 새지 않아야 한다.
    assert "locations" not in data["errors"][0]


@pytest.mark.unit
@pytest.mark.parametrize(
    "case",
    [
        "missing_run_id",
        "empty_run_id",
        "mismatched_run_id",
        "non_object_connection",
        "missing_events",
        "non_boolean_has_more",
        "non_list_events",
        "non_string_cursor",
        "missing_next_cursor",
        "empty_next_cursor",
        "oversized_next_cursor",
    ],
)
def test_legacy_dagster_run_detail_returns_error_for_malformed_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    async def _fake_post_graphql(**_kwargs: object) -> dict[str, object]:
        return _malformed_run_detail_payload(case)

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/dagster/runs/run-1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "error"
    assert data["run"] is None
    assert data["events"] == []
    assert data["errors"]


@pytest.mark.unit
def test_mark_dagster_nux_seen_posts_mutation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_query._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        assert graphql_url == "http://dagster.example:12302/graphql"
        calls.append({"query": query, "variables": variables})
        assert query == dagster_query._DAGSTER_SET_NUX_SEEN_MUTATION
        assert variables == {}
        return {"data": {"setNuxSeen": True}}

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post("/v1/ops/dagster/nux-seen")

    assert response.status_code == 200
    body = response.json()
    assert "duration_ms" in body["meta"]
    data = body["data"]
    assert data["status"] == "ok"
    assert data["seen"] is True
    assert data["errors"] == []
    assert calls == [
        {"query": dagster_query._DAGSTER_SET_NUX_SEEN_MUTATION, "variables": {}}
    ]


@pytest.mark.unit
def test_dagster_summary_returns_unavailable_when_graphql_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_query._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(dagster_mod, "post_graphql", _raise_post_graphql)

    response = client.get("/v1/ops/dagster/summary")

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["status"] == "unavailable"
    assert data["repository_count"] == 0
    assert data["recent_runs"] == []
    assert data["errors"]


@pytest.mark.unit
def test_dagster_summary_rejects_disallowed_url_before_http_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ApiSettings(
            dagster_url="http://169.254.169.254:12302",
            dagster_allowed_hosts=["127.0.0.1"],
        )
    )

    async def _unexpected_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_query._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        raise AssertionError("disallowed Dagster URL must not be requested")

    async def _unexpected_schedule_overrides(_session: object) -> dict[str, str]:
        raise AssertionError("disallowed Dagster URL must not access schedule storage")

    def _unexpected_http_client(_request: object, _settings: object) -> httpx.AsyncClient:
        raise AssertionError("disallowed Dagster URL must not create an HTTP client")

    monkeypatch.setattr(dagster_mod, "post_graphql", _unexpected_post_graphql)
    monkeypatch.setattr(dagster_schedule, "schedule_overrides", _unexpected_schedule_overrides)
    monkeypatch.setattr(dagster_router, "http_client_from_request", _unexpected_http_client)

    with TestClient(app) as test_client:
        response = test_client.get("/v1/ops/dagster/summary")

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["status"] == "error"
    assert data["dagster_url"] == ""
    assert data["graphql_url"] == ""
    assert data["repository_count"] == 0
    assert data["errors"] == ["dagster_url host is not in dagster_allowed_hosts"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("dagster_url", "dagster_graphql_url", "expected_error"),
    [
        ("http://[::1", "", "dagster_url is not a valid URL"),
        (
            "http://dagster.example:not-a-port",
            "",
            "dagster_url is not a valid URL",
        ),
        ("http://dagster.example:70000", "", "dagster_url is not a valid URL"),
        (
            "http://dagster.example:12302",
            "http://user:super-secret@dagster.example:12302/graphql?token=secret",
            "dagster_graphql_url must not include userinfo",
        ),
    ],
)
def test_dagster_summary_rejects_malformed_url_without_resource_access_or_reflection(
    monkeypatch: pytest.MonkeyPatch,
    dagster_url: str,
    dagster_graphql_url: str,
    expected_error: str,
) -> None:
    app = create_app(
        ApiSettings(
            dagster_url=dagster_url,
            dagster_graphql_url=dagster_graphql_url,
            dagster_allowed_hosts=["dagster.example", "::1"],
        )
    )

    async def _unexpected_schedule_overrides(_session: object) -> dict[str, str]:
        raise AssertionError("invalid Dagster URL must not access schedule storage")

    def _unexpected_http_client(_request: object, _settings: object) -> httpx.AsyncClient:
        raise AssertionError("invalid Dagster URL must not create an HTTP client")

    monkeypatch.setattr(dagster_schedule, "schedule_overrides", _unexpected_schedule_overrides)
    monkeypatch.setattr(dagster_router, "http_client_from_request", _unexpected_http_client)

    with TestClient(app) as test_client:
        response = test_client.get("/v1/ops/dagster/summary")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "error",
        "dagster_url": "",
        "graphql_url": "",
        "version": None,
        "checked_at": response.json()["data"]["checked_at"],
        "repository_count": 0,
        "job_count": 0,
        "asset_count": 0,
        "schedule_count": 0,
        "sensor_count": 0,
        "run_counts": {},
        "repositories": [],
        "recent_runs": [],
        "errors": [expected_error],
    }
    assert "super-secret" not in response.text
    assert "token=secret" not in response.text


@pytest.mark.unit
def test_dagster_nux_seen_rejects_invalid_graphql_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ApiSettings(
            dagster_url="http://127.0.0.1:12302",
            dagster_graphql_url="http://127.0.0.1:12302/query",
            dagster_allowed_hosts=["127.0.0.1"],
        )
    )

    async def _unexpected_post_graphql(
        client: httpx.AsyncClient,
        graphql_url: str,
        variables: dict[str, object],
        query: str = dagster_query._DAGSTER_SUMMARY_QUERY,
    ) -> dict[str, object]:
        raise AssertionError("invalid GraphQL URL must not be requested")

    def _unexpected_http_client(_request: object, _settings: object) -> httpx.AsyncClient:
        raise AssertionError("invalid GraphQL URL must not create an HTTP client")

    monkeypatch.setattr(dagster_mod, "post_graphql", _unexpected_post_graphql)
    monkeypatch.setattr(dagster_router, "http_client_from_request", _unexpected_http_client)

    with TestClient(app) as test_client:
        response = test_client.post("/v1/ops/dagster/nux-seen")

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["status"] == "error"
    assert data["dagster_url"] == ""
    assert data["graphql_url"] == ""
    assert data["seen"] is False
    assert data["errors"] == ["dagster_graphql_url path must end with /graphql"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/ops/dagster/runs/run-secret"),
        ("post", "/v1/ops/dagster/nux-seen"),
    ],
)
def test_dagster_sibling_routes_do_not_reflect_invalid_url_secrets_or_create_client(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    app = create_app(
        ApiSettings(
            dagster_url="http://dagster.example:12302",
            dagster_graphql_url=(
                "http://user:super-secret@dagster.example:12302/graphql?token=secret"
            ),
            dagster_allowed_hosts=["dagster.example"],
        )
    )

    def _unexpected_http_client(_request: object, _settings: object) -> httpx.AsyncClient:
        raise AssertionError("invalid GraphQL URL must not create an HTTP client")

    monkeypatch.setattr(dagster_router, "http_client_from_request", _unexpected_http_client)

    with TestClient(app) as test_client:
        response = test_client.request(method, path)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "error"
    assert data["dagster_url"] == ""
    assert data["graphql_url"] == ""
    assert data["errors"] == ["dagster_graphql_url must not include userinfo"]
    assert "super-secret" not in response.text
    assert "token=secret" not in response.text


@pytest.mark.unit
def test_dagster_summary_openapi_path_is_mounted(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/ops/dagster/runs/{run_id}" in spec["paths"]
    assert "/v1/ops/dagster/summary" in spec["paths"]
    assert "/v1/ops/dagster/nux-seen" in spec["paths"]
    assert "DagsterRunDetailResponse" in spec["components"]["schemas"]
    assert "DagsterSummaryResponse" in spec["components"]["schemas"]
    assert "DagsterNuxSeenResponse" in spec["components"]["schemas"]
