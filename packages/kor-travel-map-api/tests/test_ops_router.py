"""``/v1/ops/*`` 라우터 단위 테스트."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient
from kortravelmap.infra.ops_repo import (
    OpsConsistencyReport,
    OpsConsistencyReportPage,
    OpsIntegrityIssue,
    OpsIntegrityIssueCounts,
    OpsIntegrityIssuePage,
)
from kortravelmap.infra.status_repo import StatusCounts
from starlette.websockets import WebSocket, WebSocketDisconnect

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings

_LIVE_SECRET = "ops-live-test-secret-at-least-32-bytes"


def _live_subprotocol(
    *,
    now: datetime | None = None,
    expires_in_seconds: int = 60,
    payload_overrides: dict[str, Any] | None = None,
    secret: str = _LIVE_SECRET,
) -> str:
    issued_at = int((now or datetime.now(tz=UTC)).timestamp())
    payload = {
        "aud": "kor-travel-map-admin-ops-live",
        "exp": issued_at + expires_in_seconds,
        "iat": issued_at,
        "nonce": "dGVzdC1vcHMtbGl2ZS1ub25jZQ",
        "sub": "live-test-admin",
        "v": 1,
    }
    payload.update(payload_overrides or {})
    payload_part = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(
        hmac.new(
            secret.encode(),
            payload_part.encode(),
            hashlib.sha256,
        ).digest()
    ).decode().rstrip("=")
    return f"ktm.ops-live.v1.{payload_part}.{signature}"


class _FakeBegin:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.rollback_calls = 0

    def begin(self) -> _FakeBegin:
        return _FakeBegin()

    async def rollback(self) -> None:
        self.rollback_calls += 1


class _RawWebSocketClient(asyncio.Protocol):
    def __init__(self, request: bytes) -> None:
        self._request = request
        self.chunks: list[bytes] = []
        self.closed = asyncio.get_running_loop().create_future()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.Transport)
        transport.write(self._request)

    def data_received(self, data: bytes) -> None:
        self.chunks.append(bytes(data))

    def connection_lost(self, exc: Exception | None) -> None:
        if not self.closed.done():
            self.closed.set_result(exc)


async def _capture_raw_ops_live_response(app: Any) -> list[bytes]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    host, port = listener.getsockname()
    request = (
        "GET /v1/ops/live HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ).encode("ascii")
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            access_log=False,
            lifespan="off",
            log_config=None,
            ws="websockets-sansio",
        )
    )
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    transport: asyncio.Transport | None = None
    try:
        for _ in range(1_000):
            if server.started:
                break
            if server_task.done():
                await server_task
                raise AssertionError("Uvicorn exited before startup")
            await asyncio.sleep(0.001)
        else:
            raise AssertionError("Uvicorn startup timeout")

        protocol = _RawWebSocketClient(request)
        created_transport, _ = await asyncio.get_running_loop().create_connection(
            lambda: protocol,
            host,
            port,
        )
        assert isinstance(created_transport, asyncio.Transport)
        transport = created_transport
        await asyncio.wait_for(protocol.closed, timeout=2)
        return protocol.chunks
    finally:
        if transport is not None:
            transport.close()
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=2)
        listener.close()


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(session: _FakeSession) -> TestClient:
    app = create_app(ApiSettings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


@pytest.fixture
def live_client(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    from kortravelmap.api.routers import ops_live as live_mod

    app = create_app(ApiSettings(admin_proxy_secret=_LIVE_SECRET))

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    async def _claim(_session: Any, _context: Any) -> bool:
        return True

    monkeypatch.setattr(live_mod, "claim_ops_live_ticket", _claim)
    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _report() -> OpsConsistencyReport:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return OpsConsistencyReport(
        report_id="22222222-2222-2222-2222-222222222222",
        batch_id="33333333-3333-3333-3333-333333333333",
        started_at=now,
        finished_at=now,
        severity_max="WARN",
        cases=[],
        summary={"total_violations": 3, "by_code": {"F4": 3}},
    )


def _issue() -> OpsIntegrityIssue:
    return OpsIntegrityIssue(
        issue_id="44444444-4444-4444-4444-444444444444",
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_record_key="src-1",
        feature_id="feature-1",
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
        payload={"source": "unit"},
        status="open",
        detected_at=datetime(2026, 6, 3, tzinfo=UTC),
        last_seen_at=datetime(2026, 6, 4, tzinfo=UTC),
        resolved_at=None,
    )


@pytest.mark.unit
def test_remaining_ops_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert {
        "/v1/ops/metrics",
        "/v1/ops/health-deep",
        "/v1/ops/consistency/reports",
        "/v1/ops/consistency/issues",
    } <= set(spec["paths"])
    assert "OpsMetricsResponse" in spec["components"]["schemas"]

@pytest.mark.unit
def test_ops_live_websocket_rejects_logged_out_connection(
    live_client: TestClient,
    session: _FakeSession,
) -> None:
    with live_client.websocket_connect("/v1/ops/live") as websocket:
        assert websocket.accepted_subprotocol is None
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()

    assert exc_info.value.code == 4401
    assert session.rollback_calls == 1


@pytest.mark.unit
def test_ops_live_websocket_rejects_tampered_ticket(
    live_client: TestClient,
    session: _FakeSession,
) -> None:
    protocol = _live_subprotocol()
    tampered = f"{protocol[:-1]}{'A' if protocol[-1] != 'A' else 'B'}"

    with live_client.websocket_connect(
        "/v1/ops/live",
        subprotocols=[tampered],
    ) as websocket:
        assert websocket.accepted_subprotocol == tampered
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()

    assert exc_info.value.code == 4401
    assert session.rollback_calls == 1


@pytest.mark.unit
def test_ops_live_websocket_rejects_expired_ticket(
    live_client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    async def _claim_must_not_run(_session: Any, _context: Any) -> bool:
        raise AssertionError("expired ticket must close before claim")

    monkeypatch.setattr(live_mod, "claim_ops_live_ticket", _claim_must_not_run)
    protocol = _live_subprotocol(
        now=datetime(2026, 1, 1, tzinfo=UTC),
        expires_in_seconds=60,
    )

    with live_client.websocket_connect(
        "/v1/ops/live",
        subprotocols=[protocol],
    ) as websocket, pytest.raises(WebSocketDisconnect) as exc_info:
        websocket.receive_json()

    assert exc_info.value.code == 4408
    assert session.rollback_calls == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("protocol", "now"),
    [
        ("ktm.ops-live.v1.not-a-ticket", datetime(2026, 7, 17, tzinfo=UTC)),
        (
            _live_subprotocol(
                now=datetime(2026, 7, 17, tzinfo=UTC),
                payload_overrides={"iat": 1_784_240_500, "exp": 1_784_240_560},
            ),
            datetime.fromtimestamp(1_784_240_000, tz=UTC),
        ),
        (
            _live_subprotocol(
                now=datetime(2026, 7, 17, tzinfo=UTC),
                payload_overrides={"aud": "another-service"},
            ),
            datetime(2026, 7, 17, tzinfo=UTC),
        ),
        (
            _live_subprotocol(
                now=datetime(2026, 7, 17, tzinfo=UTC),
                expires_in_seconds=61,
            ),
            datetime(2026, 7, 17, tzinfo=UTC),
        ),
    ],
    ids=["malformed", "future-iat", "wrong-audience", "wrong-ttl"],
)
def test_ops_live_ticket_verifier_rejects_invalid_contract(
    protocol: str,
    now: datetime,
) -> None:
    from kortravelmap.api.ops_live_auth import verify_ops_live_subprotocol

    assert verify_ops_live_subprotocol(protocol, secret=_LIVE_SECRET, now=now) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("requested_protocols", "expected"),
    [
        (None, None),
        ("", None),
        ("chat", None),
        ("chat, ktm.ops-live.v1.YQ.YQ", "ktm.ops-live.v1.YQ.YQ"),
        (
            "ktm.ops-live.v1.YQ.YQ, ktm.ops-live.v1.Yg.Yg",
            None,
        ),
        (f"ktm.ops-live.v1.{'A' * 2_048}.A", None),
        ("ktm.ops-live.v1.not-a-ticket", None),
    ],
    ids=[
        "none",
        "empty",
        "unrelated",
        "single",
        "multiple",
        "too-long",
        "malformed",
    ],
)
def test_select_ops_live_subprotocol_requires_one_bounded_formatted_candidate(
    requested_protocols: str | None,
    expected: str | None,
) -> None:
    from kortravelmap.api.ops_live_auth import select_ops_live_subprotocol

    assert select_ops_live_subprotocol(requested_protocols) == expected


@pytest.mark.unit
def test_ops_live_websocket_rejects_replayed_ticket(
    live_client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    async def _already_claimed(_session: Any, _context: Any) -> bool:
        return False

    monkeypatch.setattr(live_mod, "claim_ops_live_ticket", _already_claimed)
    with live_client.websocket_connect(
        "/v1/ops/live",
        subprotocols=[_live_subprotocol()],
    ) as websocket, pytest.raises(WebSocketDisconnect) as exc_info:
        websocket.receive_json()

    assert exc_info.value.code == 4401
    assert session.rollback_calls == 1


@pytest.mark.unit
def test_ops_live_websocket_snapshot_database_failure_retries_later(
    live_client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    async def _collect(
        _session: Any,
        topics: set[str],
    ) -> dict[str, live_mod.LiveTopicSnapshot]:
        if not topics:
            return {}
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(live_mod, "collect_live_topic_snapshots", _collect)

    with live_client.websocket_connect(
        "/v1/ops/live",
        subprotocols=[_live_subprotocol()],
    ) as websocket:
        assert websocket.receive_json()["type"] == "hello"
        websocket.send_json({"type": "subscribe", "topics": ["import_jobs"]})
        assert websocket.receive_json()["type"] == "subscribed"
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()

    assert exc_info.value.code == 1013
    assert session.rollback_calls == 1


@pytest.mark.unit
def test_ops_live_ticket_claim_timeout_rolls_back_and_closes_expired(
    live_client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    async def _wait_for_pool(_session: Any, _context: Any) -> bool:
        await asyncio.sleep(60)
        return True

    monkeypatch.setattr(live_mod, "claim_ops_live_ticket", _wait_for_pool)
    monkeypatch.setattr(live_mod, "_remaining_lease_seconds", lambda _expires: 0.001)

    with live_client.websocket_connect(
        "/v1/ops/live",
        subprotocols=[_live_subprotocol()],
    ) as websocket, pytest.raises(WebSocketDisconnect) as exc_info:
        websocket.receive_json()

    assert exc_info.value.code == 4408
    assert session.rollback_calls == 1


@pytest.mark.unit
def test_ops_live_ticket_claim_timeout_bounds_rollback_before_expired_close(
    live_client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    async def _wait_for_pool(_session: Any, _context: Any) -> bool:
        await asyncio.sleep(60)
        return True

    async def _rollback_never_finishes() -> None:
        session.rollback_calls += 1
        await asyncio.sleep(60)

    monkeypatch.setattr(live_mod, "claim_ops_live_ticket", _wait_for_pool)
    monkeypatch.setattr(live_mod, "_remaining_lease_seconds", lambda _expires: 0.001)
    monkeypatch.setattr(live_mod, "_ROLLBACK_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(session, "rollback", _rollback_never_finishes)

    with live_client.websocket_connect(
        "/v1/ops/live",
        subprotocols=[_live_subprotocol()],
    ) as websocket, pytest.raises(WebSocketDisconnect) as exc_info:
        websocket.receive_json()

    assert exc_info.value.code == 4408
    assert session.rollback_calls == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "claim_error",
    [TimeoutError("database statement timeout"), RuntimeError("database unavailable")],
    ids=["internal-timeout", "database-error"],
)
def test_ops_live_ticket_claim_failure_rolls_back_and_retries_later(
    live_client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
    claim_error: Exception,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    async def _fail_claim(_session: Any, _context: Any) -> bool:
        raise claim_error

    monkeypatch.setattr(live_mod, "claim_ops_live_ticket", _fail_claim)

    with live_client.websocket_connect(
        "/v1/ops/live",
        subprotocols=[_live_subprotocol()],
    ) as websocket, pytest.raises(WebSocketDisconnect) as exc_info:
        websocket.receive_json()

    assert exc_info.value.code == 1013
    assert session.rollback_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_accept_yields_before_auth_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    events: list[str] = []

    async def _accept(
        _websocket: Any,
        *,
        subprotocol: str | None,
    ) -> bool:
        assert subprotocol == "ktm.ops-live.v1.YQ.YQ"
        events.append("accept")
        asyncio.get_running_loop().call_soon(events.append, "event-loop-yield")
        return True

    async def _close(
        _websocket: Any,
        *,
        code: int,
        reason: str,
    ) -> None:
        assert code == 4401
        assert reason == "authentication required"
        events.append("close")

    monkeypatch.setattr(live_mod, "_accept_best_effort", _accept)
    monkeypatch.setattr(live_mod, "_close_best_effort", _close)

    await live_mod._accept_and_close_best_effort(
        object(),
        code=4401,
        reason="authentication required",
        subprotocol="ktm.ops-live.v1.YQ.YQ",
    )

    assert events == ["accept", "event-loop-yield", "close"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_accept_failure_does_not_send_auth_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    async def _accept(
        _websocket: Any,
        *,
        subprotocol: str | None,
    ) -> bool:
        assert subprotocol is None
        return False

    async def _close_must_not_run(
        _websocket: Any,
        *,
        code: int,
        reason: str,
    ) -> None:
        raise AssertionError(f"close must not run after failed accept: {code=} {reason=}")

    monkeypatch.setattr(live_mod, "_accept_best_effort", _accept)
    monkeypatch.setattr(live_mod, "_close_best_effort", _close_must_not_run)

    await live_mod._accept_and_close_best_effort(
        object(),
        code=4401,
        reason="authentication required",
        subprotocol=None,
    )


@pytest.mark.unit
def test_ops_live_accept_close_settle_setting_default_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 기본값 0.25s — #810 후속: 10ms는 엣지 경유 브라우저 close-code delivery에 부족.
    assert ApiSettings().ops_live_accept_close_settle_seconds == pytest.approx(0.25)
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_API_OPS_LIVE_ACCEPT_CLOSE_SETTLE_SECONDS", "0.4"
    )
    assert ApiSettings().ops_live_accept_close_settle_seconds == pytest.approx(0.4)


@pytest.mark.unit
def test_resolve_accept_close_settle_reads_settings_and_falls_back() -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    # settings가 없는 bare object → 모듈 기본값 fallback.
    assert live_mod._resolve_accept_close_settle_seconds(
        object()  # type: ignore[arg-type]
    ) == pytest.approx(live_mod._DEFAULT_ACCEPT_CLOSE_SETTLE_SECONDS)

    class _Settings:
        ops_live_accept_close_settle_seconds = 0.4

    class _State:
        settings = _Settings()

    class _App:
        state = _State()

    class _WebSocket:
        app = _App()

    assert live_mod._resolve_accept_close_settle_seconds(
        _WebSocket()  # type: ignore[arg-type]
    ) == pytest.approx(0.4)

    class _NegSettings:
        ops_live_accept_close_settle_seconds = -1.0

    class _NegState:
        settings = _NegSettings()

    class _NegApp:
        state = _NegState()

    class _NegWebSocket:
        app = _NegApp()

    # 음수는 0으로 clamp.
    assert (
        live_mod._resolve_accept_close_settle_seconds(
            _NegWebSocket()  # type: ignore[arg-type]
        )
        == 0.0
    )

    class _NoneSettings:
        ops_live_accept_close_settle_seconds = None

    class _NoneState:
        settings = _NoneSettings()

    class _NoneApp:
        state = _NoneState()

    class _NoneWebSocket:
        app = _NoneApp()

    # 비정상 값(None) → 모듈 기본값 fallback.
    assert live_mod._resolve_accept_close_settle_seconds(
        _NoneWebSocket()  # type: ignore[arg-type]
    ) == pytest.approx(live_mod._DEFAULT_ACCEPT_CLOSE_SETTLE_SECONDS)

    class _HugeSettings:
        ops_live_accept_close_settle_seconds = 100.0

    class _HugeState:
        settings = _HugeSettings()

    class _HugeApp:
        state = _HugeState()

    class _HugeWebSocket:
        app = _HugeApp()

    # 상한 초과는 _MAX로 clamp.
    assert live_mod._resolve_accept_close_settle_seconds(
        _HugeWebSocket()  # type: ignore[arg-type]
    ) == pytest.approx(live_mod._MAX_ACCEPT_CLOSE_SETTLE_SECONDS)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_reject_close_sleeps_for_configured_settle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    async def _accept(_websocket: Any, *, subprotocol: str | None) -> bool:
        del subprotocol
        return True

    async def _close(_websocket: Any, *, code: int, reason: str) -> None:
        del code, reason

    monkeypatch.setattr(live_mod.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(live_mod, "_accept_best_effort", _accept)
    monkeypatch.setattr(live_mod, "_close_best_effort", _close)

    class _Settings:
        ops_live_accept_close_settle_seconds = 0.5

    class _State:
        settings = _Settings()

    class _App:
        state = _State()

    class _WebSocket:
        app = _App()

    await live_mod._accept_and_close_best_effort(
        _WebSocket(),  # type: ignore[arg-type]
        code=4408,
        reason="ops live ticket expired",
        subprotocol="ktm.ops-live.v1.YQ.YQ",
    )

    # reject-close는 settings에서 읽은 settle만큼 정확히 대기한다.
    assert slept == [pytest.approx(0.5)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_cancellation_during_accept_handoff_closes_once() -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    close_codes: list[int] = []
    operation: asyncio.Task[None]

    class _AcceptThenCancelWebSocket:
        async def accept(
            self,
            *,
            subprotocol: str | None,
        ) -> None:
            assert subprotocol is None
            asyncio.get_running_loop().call_soon(operation.cancel)

        async def close(self, *, code: int, reason: str) -> None:
            assert reason == "authentication required"
            close_codes.append(code)

    operation = asyncio.create_task(
        live_mod._accept_and_close_best_effort(
            _AcceptThenCancelWebSocket(),  # type: ignore[arg-type]
            code=4401,
            reason="authentication required",
            subprotocol=None,
        )
    )

    with pytest.raises(asyncio.CancelledError):
        await operation

    assert close_codes == [4401]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_repeated_cancellation_during_close_closes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    close_started = asyncio.Event()
    close_release = asyncio.Event()
    close_codes: list[int] = []

    async def _accept(
        _websocket: Any,
        *,
        subprotocol: str | None,
    ) -> bool:
        assert subprotocol is None
        return True

    async def _close(
        _websocket: Any,
        *,
        code: int,
        reason: str,
    ) -> None:
        assert reason == "authentication required"
        close_codes.append(code)
        close_started.set()
        await close_release.wait()

    monkeypatch.setattr(live_mod, "_accept_best_effort", _accept)
    monkeypatch.setattr(live_mod, "_close_best_effort", _close)

    operation = asyncio.create_task(
        live_mod._accept_and_close_best_effort(
            object(),
            code=4401,
            reason="authentication required",
            subprotocol=None,
        )
    )
    await close_started.wait()
    operation.cancel()
    await asyncio.sleep(0)
    operation.cancel()
    await asyncio.sleep(0)
    close_release.set()

    with pytest.raises(asyncio.CancelledError):
        await operation

    assert close_codes == [4401]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_real_uvicorn_separates_handshake_and_auth_close() -> None:
    app = create_app(ApiSettings(admin_proxy_secret=_LIVE_SECRET))
    session = _FakeSession()

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    for attempt in range(5):
        chunks = await _capture_raw_ops_live_response(app)
        response = b"".join(chunks)
        header_end = response.index(b"\r\n\r\n") + 4

        offset = 0
        for chunk in chunks:
            offset += len(chunk)
            if header_end <= offset:
                assert header_end == offset, (
                    f"coalesced response on attempt {attempt + 1}"
                )
                break
        else:  # pragma: no cover - response.index가 먼저 실패한다.
            raise AssertionError("WebSocket handshake header boundary is missing")

        assert response.startswith(b"HTTP/1.1 101 Switching Protocols\r\n")
        frame = response[header_end:]
        assert frame[0] & 0x0F == 0x08
        assert frame[1] & 0x80 == 0
        payload_length = frame[1] & 0x7F
        assert payload_length < 126
        assert len(frame) == payload_length + 2
        assert int.from_bytes(frame[2:4], "big") == 4401
    assert session.rollback_calls == 5


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["timeout", "exception"])
async def test_ops_live_real_uvicorn_owns_failed_accept_fallback(
    failure_mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    app = create_app(ApiSettings(admin_proxy_secret=_LIVE_SECRET))
    session = _FakeSession()

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    async def _fail_accept(
        _websocket: WebSocket,
        subprotocol: str | None = None,
        headers: Any = None,
    ) -> None:
        del subprotocol, headers
        if failure_mode == "timeout":
            await asyncio.sleep(60)
        raise RuntimeError("injected accept failure")

    app.dependency_overrides[get_session] = _fake_session
    monkeypatch.setattr(WebSocket, "accept", _fail_accept)
    monkeypatch.setattr(live_mod, "_CLOSE_TIMEOUT_SECONDS", 0.001)

    response = b"".join(await _capture_raw_ops_live_response(app))

    assert response.startswith(b"HTTP/1.1 500 Internal Server Error\r\n")
    assert b"101 Switching Protocols" not in response
    assert session.rollback_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_send_closes_at_ticket_lease_before_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    expires_at = datetime(2026, 7, 17, tzinfo=UTC)

    class _WebSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, Any]] = []
            self.closed: list[int] = []

        async def send_json(self, payload: dict[str, Any]) -> None:
            self.sent.append(payload)

        async def close(self, *, code: int, reason: str) -> None:
            del reason
            self.closed.append(code)

    websocket = _WebSocket()
    session = _FakeSession()
    monkeypatch.setattr(live_mod, "_utcnow", lambda: expires_at)

    sent = await live_mod._send_json_before_expiry(
        websocket,
        session,
        {"type": "snapshot"},
        expires_at=expires_at,
    )

    assert sent is False
    assert websocket.sent == []
    assert websocket.closed == [4408]
    assert session.rollback_calls == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_send_internal_timeout_retries_later() -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    class _WebSocket:
        def __init__(self) -> None:
            self.closed: list[int] = []

        async def send_json(self, _payload: dict[str, Any]) -> None:
            raise TimeoutError("transport timeout")

        async def close(self, *, code: int, reason: str) -> None:
            del reason
            self.closed.append(code)

    websocket = _WebSocket()
    session = _FakeSession()

    sent = await live_mod._send_json_before_expiry(
        websocket,
        session,
        {"type": "snapshot"},
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=60),
    )

    assert sent is False
    assert websocket.closed == [1013]
    assert session.rollback_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_send_transport_error_rolls_back_before_retry_close() -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    events: list[str] = []

    class _Session(_FakeSession):
        async def rollback(self) -> None:
            await super().rollback()
            events.append("rollback")

    class _WebSocket:
        async def send_json(self, _payload: dict[str, Any]) -> None:
            raise OSError("connection reset")

        async def close(self, *, code: int, reason: str) -> None:
            del reason
            events.append(f"close:{code}")

    session = _Session()
    sent = await live_mod._send_json_before_expiry(
        _WebSocket(),
        session,
        {"type": "snapshot"},
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=60),
    )

    assert sent is False
    assert session.rollback_calls == 1
    assert events == ["rollback", "close:1013"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_receive_poll_timeout_is_not_internal_timeout() -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    class _PollingWebSocket:
        async def receive_json(self) -> object:
            await asyncio.sleep(60)
            return {}

    assert await live_mod._receive_command(_PollingWebSocket(), 0.001) is None

    class _InternalTimeoutWebSocket:
        async def receive_json(self) -> object:
            raise TimeoutError("transport timeout")

    with pytest.raises(TimeoutError, match="transport timeout"):
        await live_mod._receive_command(_InternalTimeoutWebSocket(), 60)


@pytest.mark.unit
def test_ops_live_receive_transport_error_rolls_back_and_retries_later(
    live_client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    async def _receive_fails(_websocket: Any, _timeout_seconds: float) -> object:
        raise RuntimeError("receive transport failed")

    monkeypatch.setattr(live_mod, "_receive_command", _receive_fails)

    with live_client.websocket_connect(
        "/v1/ops/live",
        subprotocols=[_live_subprotocol()],
    ) as websocket:
        assert websocket.receive_json()["type"] == "hello"
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()

    assert exc_info.value.code == 1013
    # 최초 empty snapshot transaction 정리 + receive 오류 bounded rollback.
    assert session.rollback_calls == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_snapshot_exception_rolls_back_before_retry_later_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    events: list[str] = []

    class _Session:
        def __init__(self) -> None:
            self.rollback_calls = 0

        async def rollback(self) -> None:
            self.rollback_calls += 1
            events.append("rollback")

    class _WebSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, Any]] = []
            self.closed: list[int] = []

        async def send_json(self, payload: dict[str, Any]) -> None:
            self.sent.append(payload)

        async def close(self, *, code: int, reason: str) -> None:
            del reason
            self.closed.append(code)
            events.append("close")

    async def _raise(_session: Any, _topics: set[str]) -> Any:
        raise RuntimeError("snapshot failed")

    session = _Session()
    websocket = _WebSocket()
    monkeypatch.setattr(live_mod, "collect_live_topic_snapshots", _raise)

    sequence = await live_mod._send_snapshots(
        websocket,
        session,
        {"import_jobs"},
        {},
        sequence=1,
        force=True,
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=60),
    )

    assert sequence is None
    assert session.rollback_calls == 1
    assert websocket.sent == []
    assert websocket.closed == [1013]
    assert events == ["rollback", "close"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_snapshot_internal_timeout_retries_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    class _Session:
        def __init__(self) -> None:
            self.rollback_calls = 0

        async def rollback(self) -> None:
            self.rollback_calls += 1

    class _WebSocket:
        def __init__(self) -> None:
            self.closed: list[int] = []

        async def close(self, *, code: int, reason: str) -> None:
            del reason
            self.closed.append(code)

    async def _database_statement_timeout(
        _session: Any,
        _topics: set[str],
    ) -> Any:
        raise TimeoutError("database statement timeout")

    session = _Session()
    websocket = _WebSocket()
    monkeypatch.setattr(
        live_mod,
        "collect_live_topic_snapshots",
        _database_statement_timeout,
    )

    sequence = await live_mod._send_snapshots(
        websocket,
        session,
        {"import_jobs"},
        {},
        sequence=1,
        force=True,
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=60),
    )

    assert sequence is None
    assert session.rollback_calls == 1
    assert websocket.closed == [1013]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_snapshot_timeout_rolls_back_and_closes_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    events: list[str] = []

    class _Session:
        def __init__(self) -> None:
            self.rollback_calls = 0

        async def rollback(self) -> None:
            self.rollback_calls += 1
            events.append("rollback")

    class _WebSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, Any]] = []
            self.closed: list[int] = []

        async def send_json(self, payload: dict[str, Any]) -> None:
            self.sent.append(payload)

        async def close(self, *, code: int, reason: str) -> None:
            del reason
            self.closed.append(code)
            events.append("close")

    async def _wait_for_database(_session: Any, _topics: set[str]) -> Any:
        await asyncio.sleep(60)

    session = _Session()
    websocket = _WebSocket()
    monkeypatch.setattr(live_mod, "collect_live_topic_snapshots", _wait_for_database)
    monkeypatch.setattr(live_mod, "_remaining_lease_seconds", lambda _expires: 0.001)

    sequence = await live_mod._send_snapshots(
        websocket,
        session,
        {"import_jobs"},
        {},
        sequence=1,
        force=True,
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=60),
    )

    assert sequence is None
    assert session.rollback_calls == 1
    assert websocket.sent == []
    assert websocket.closed == [4408]
    assert events == ["close", "rollback"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_collect_internal_rollback_hang_cannot_outlive_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    class _Session:
        def __init__(self) -> None:
            self.rollback_calls = 0

        async def rollback(self) -> None:
            self.rollback_calls += 1
            await asyncio.sleep(60)

    class _WebSocket:
        def __init__(self) -> None:
            self.closed: list[int] = []

        async def close(self, *, code: int, reason: str) -> None:
            del reason
            self.closed.append(code)

    async def _collect_with_internal_rollback(
        session: Any,
        _topics: set[str],
    ) -> dict[str, Any]:
        await live_mod._rollback_safe(session)
        return {}

    session = _Session()
    websocket = _WebSocket()
    monkeypatch.setattr(
        live_mod,
        "collect_live_topic_snapshots",
        _collect_with_internal_rollback,
    )
    monkeypatch.setattr(live_mod, "_remaining_lease_seconds", lambda _expires: 0.001)
    monkeypatch.setattr(live_mod, "_ROLLBACK_TIMEOUT_SECONDS", 0.001)

    sequence = await live_mod._send_snapshots(
        websocket,
        session,
        {"import_jobs"},
        {},
        sequence=1,
        force=True,
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=60),
    )

    assert sequence is None
    assert session.rollback_calls == 2
    assert websocket.closed == [4408]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_snapshot_close_hang_still_reaches_bounded_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    class _Session:
        def __init__(self) -> None:
            self.rollback_calls = 0

        async def rollback(self) -> None:
            self.rollback_calls += 1

    class _WebSocket:
        def __init__(self) -> None:
            self.close_calls = 0

        async def close(self, *, code: int, reason: str) -> None:
            del code, reason
            self.close_calls += 1
            await asyncio.sleep(60)

    async def _collect_never_finishes(_session: Any, _topics: set[str]) -> Any:
        await asyncio.sleep(60)

    session = _Session()
    websocket = _WebSocket()
    monkeypatch.setattr(
        live_mod,
        "collect_live_topic_snapshots",
        _collect_never_finishes,
    )
    monkeypatch.setattr(live_mod, "_remaining_lease_seconds", lambda _expires: 0.001)
    monkeypatch.setattr(live_mod, "_CLOSE_TIMEOUT_SECONDS", 0.001)

    sequence = await live_mod._send_snapshots(
        websocket,
        session,
        {"import_jobs"},
        {},
        sequence=1,
        force=True,
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=60),
    )

    assert sequence is None
    assert websocket.close_calls == 1
    assert session.rollback_calls == 1


@pytest.mark.unit
def test_ops_live_websocket_authenticated_hello_snapshot_update(
    live_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    collect_count = 0

    async def _collect(
        _session: Any,
        topics: set[str],
    ) -> dict[str, live_mod.LiveTopicSnapshot]:
        nonlocal collect_count
        collect_count += 1
        return {
            topic: live_mod.LiveTopicSnapshot(
                topic=topic,
                revision=f"{topic}:{collect_count}",
                data={"topic": topic, "ok": True},
            )
            for topic in topics
        }

    monkeypatch.setattr(live_mod, "collect_live_topic_snapshots", _collect)

    protocol = _live_subprotocol()
    with live_client.websocket_connect(
        "/v1/ops/live?poll_interval_ms=1000",
        subprotocols=[protocol],
    ) as websocket:
        hello = websocket.receive_json()
        websocket.send_json({"type": "replace", "topics": ["import_jobs"]})
        subscribed = websocket.receive_json()
        snapshot = websocket.receive_json()
        update = websocket.receive_json()

    assert hello["type"] == "hello"
    assert hello["actor"] == "live-test-admin"
    assert hello["topics"] == []
    assert subscribed["type"] == "subscribed"
    assert subscribed["topics"] == ["import_jobs"]
    assert snapshot["type"] == "snapshot"
    assert snapshot["topic"] == "import_jobs"
    assert snapshot["data"] == {"topic": "import_jobs", "ok": True}
    assert update["type"] == "update"
    assert update["topic"] == "import_jobs"


@pytest.mark.unit
def test_ops_live_sql_excludes_quarantined_import_jobs() -> None:
    from kortravelmap.api import ops_live_auth
    from kortravelmap.api.routers import ops_live as live_mod

    assert live_mod._IMPORT_JOBS_LIVE_SQL.count("quarantined_at IS NULL") >= 4
    assert live_mod._IMPORT_JOB_EVENTS_LIVE_SQL.count("quarantined_at IS NULL") >= 1
    assert "event.quarantined_at IS NULL" in live_mod._IMPORT_JOBS_LIVE_SQL
    assert "event.quarantined_at IS NULL" in live_mod._IMPORT_JOB_EVENTS_LIVE_SQL
    assert "ops.import_job_event_clock" in live_mod._IMPORT_JOBS_LIVE_SQL
    assert "ops.import_job_event_clock" in live_mod._IMPORT_JOB_EVENTS_LIVE_SQL
    assert "ops.import_jobs" not in live_mod._IMPORT_JOB_EVENTS_LIVE_SQL
    assert "COUNT(" not in live_mod._IMPORT_JOB_EVENTS_LIVE_SQL
    assert "WHERE quarantined_at IS NULL" in live_mod._DAGSTER_RUNS_LIVE_SQL
    assert "WHERE quarantined_at IS NULL" in live_mod._DAGSTER_RUN_LIVE_SQL
    assert "provider_sync.provider_sync_state" in live_mod._PROVIDER_SYNC_LIVE_SQL
    assert "ops.provider_refresh_policies" in live_mod._PROVIDER_SYNC_LIVE_SQL
    assert "dataset_projection" in live_mod._DATASET_PROJECTION_LIVE_SQL
    assert "ops.dagster_schedule_overrides" in live_mod._DAGSTER_SCHEDULES_LIVE_SQL
    assert (
        "ops.dagster_schedule_audit_events" in live_mod._DAGSTER_SCHEDULES_LIVE_SQL
    )
    assert (
        "ops.dagster_schedule_claim_resolutions"
        in live_mod._DAGSTER_SCHEDULES_LIVE_SQL
    )
    assert "to_regclass" not in live_mod._DAGSTER_SCHEDULES_LIVE_SQL
    assert ops_live_auth._CLAIM_RETENTION_GRACE_SECONDS >= 60
    assert "retention_grace_seconds" in ops_live_auth._CLAIM_SQL


@pytest.mark.unit
def test_ops_live_snapshot_sql_uses_total_ordering() -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    def normalized(sql: str) -> str:
        return " ".join(sql.split())

    import_jobs_sql = normalized(live_mod._IMPORT_JOBS_LIVE_SQL)
    requests_sql = normalized(live_mod._FEATURE_UPDATE_REQUESTS_LIVE_SQL)
    uploads_sql = normalized(live_mod._OFFLINE_UPLOADS_LIVE_SQL)
    dagster_runs_sql = normalized(live_mod._DAGSTER_RUNS_LIVE_SQL)
    dagster_run_sql = normalized(live_mod._DAGSTER_RUN_LIVE_SQL)
    request_sql = normalized(live_mod._FEATURE_UPDATE_REQUEST_LIVE_SQL)

    assert (
        "jsonb_agg(to_jsonb(j) ORDER BY j.created_at DESC, j.job_id DESC)"
        in import_jobs_sql
    )
    assert "ORDER BY created_at DESC, job_id DESC LIMIT 20" in import_jobs_sql
    assert (
        "ORDER BY r.priority DESC, r.created_at ASC, r.request_id ASC"
        in requests_sql
    )
    assert (
        "ORDER BY request.priority DESC, request.created_at ASC, "
        "request.request_id ASC LIMIT 20"
        in requests_sql
    )
    assert (
        "jsonb_agg(to_jsonb(u) ORDER BY u.updated_at DESC, u.upload_id DESC)"
        in uploads_sql
    )
    assert "ORDER BY updated_at DESC, upload_id DESC LIMIT 20" in uploads_sql
    assert (
        "jsonb_agg(DISTINCT j.run_id ORDER BY j.run_id) "
        "FILTER (WHERE j.run_id IS NOT NULL)"
        in dagster_runs_sql
    )
    assert (
        "jsonb_agg(to_jsonb(j) ORDER BY j.created_at DESC, j.job_id DESC)"
        in dagster_run_sql
    )
    assert "ORDER BY created_at DESC, job_id DESC LIMIT 20" in dagster_run_sql
    assert "request.generation" in request_sql
    assert "request.matched_scope" in request_sql
    assert "job.dispatch_requested_at" in request_sql


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_feature_update_request_revision_tracks_all_mutable_rest_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    request_id = "22222222-2222-2222-2222-222222222222"
    base = {
        "request_id": request_id,
        "status": "queued",
        "scope_type": "provider_dataset",
        "priority": 50,
        "job_id": "11111111-1111-1111-1111-111111111111",
        "dagster_run_id": None,
        "error_message": None,
        "created_at": datetime(2026, 7, 17, 0, 0, tzinfo=UTC),
        "started_at": None,
        "finished_at": None,
        "generation": 1,
        "matched_scope": {},
        "dispatch_requested_at": None,
        "updated_at": datetime(2026, 7, 17, 0, 0, tzinfo=UTC),
    }
    rows = iter(
        [
            base,
            {**base, "generation": 2},
            {
                **base,
                "generation": 2,
                "matched_scope": {"feature_count": 3},
            },
            {
                **base,
                "generation": 2,
                "matched_scope": {"feature_count": 3},
                "dispatch_requested_at": datetime(
                    2026,
                    7,
                    17,
                    0,
                    1,
                    tzinfo=UTC,
                ),
            },
        ]
    )

    async def _row_mapping(
        _session: Any,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert sql == live_mod._FEATURE_UPDATE_REQUEST_LIVE_SQL
        assert params == {"request_id": request_id}
        return next(rows)

    monkeypatch.setattr(live_mod, "_row_mapping", _row_mapping)

    snapshots = [
        (
            await live_mod.collect_live_topic_snapshots(
                object(),
                {f"feature_update_request:{request_id}"},
            )
        )[f"feature_update_request:{request_id}"]
        for _ in range(4)
    ]

    assert snapshots[0].data["generation"] == 1
    assert snapshots[0].data["matched_scope"] == {}
    assert snapshots[0].data["dispatch_requested_at"] is None
    assert snapshots[3].data["dispatch_requested_at"] == "2026-07-17T00:01:00+00:00"
    assert len({snapshot.revision for snapshot in snapshots}) == 4


@pytest.mark.unit
def test_ops_live_ping_command_is_unsupported() -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    topics = {"import_jobs"}
    with pytest.raises(ValueError, match="unsupported live command type"):
        live_mod._apply_command(topics, {"type": "ping"})

    assert topics == {"import_jobs"}


@pytest.mark.unit
def test_ops_live_accepts_consolidated_page_topics() -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    assert live_mod._topics_from_value(
        ["provider_sync", "dataset_projection", "dagster_schedules"]
    ) == {
        "provider_sync",
        "dataset_projection",
        "dagster_schedules",
    }


@pytest.mark.unit
def test_ops_live_rejects_non_uuid_resource_topic() -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    with pytest.raises(ValueError, match="must be a UUID"):
        live_mod._topics_from_value(["import_job:not-a-uuid"])

    with pytest.raises(ValueError, match="canonical UUID"):
        live_mod._topics_from_value(
            ["import_job:11111111111111111111111111111111"]
        )


@pytest.mark.unit
def test_ops_live_accepts_canonical_opaque_dagster_run_topic() -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    assert live_mod._topics_from_value(
        ["dagster_run:  실행:지역/2026 run  "]
    ) == {
        "dagster_run:실행:지역/2026 run"
    }

    assert live_mod._topics_from_value(["dagster_run:run,with,comma"]) == {
        "dagster_run:run,with,comma"
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "run_id",
    ["", "   ", "contains\x00control", "x" * 256],
)
def test_ops_live_rejects_invalid_opaque_dagster_run_topic(run_id: str) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    with pytest.raises(ValueError, match="invalid Dagster run id"):
        live_mod._topics_from_value([f"dagster_run:{run_id}"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_live_schedule_revision_reads_c5_audit_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    queries: list[str] = []

    async def _row_mapping(
        _session: Any,
        sql: str,
        _params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        queries.append(sql)
        return {
            "audit_revision": 17,
            "claim_resolution_revision": 23,
            "live_revision": 31,
            "override_count": 2,
            "override_updated_at": None,
        }

    monkeypatch.setattr(live_mod, "_row_mapping", _row_mapping)

    snapshot = await live_mod._dagster_schedules_snapshot(object())

    assert snapshot == {
        "audit_revision": 17,
        "claim_resolution_revision": 23,
        "live_revision": 31,
        "override_count": 2,
        "override_updated_at": None,
    }
    assert len(queries) == 1
    assert "to_regclass" not in queries[0]
    assert "ops.dagster_schedule_audit_events" in queries[0]
    assert "ops.dagster_schedule_claim_resolutions" in queries[0]
    assert "ops.ops_live_topic_revisions" in queries[0]


@pytest.mark.unit
def test_ops_live_websocket_subscribe_command(
    live_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_live as live_mod

    async def _collect(
        _session: Any,
        topics: set[str],
    ) -> dict[str, live_mod.LiveTopicSnapshot]:
        return {
            topic: live_mod.LiveTopicSnapshot(
                topic=topic,
                revision=f"{topic}:1",
                data={"topic": topic},
            )
            for topic in topics
        }

    monkeypatch.setattr(live_mod, "collect_live_topic_snapshots", _collect)

    with live_client.websocket_connect(
        "/v1/ops/live?poll_interval_ms=1000",
        subprotocols=[_live_subprotocol()],
    ) as websocket:
        assert websocket.receive_json()["type"] == "hello"

        websocket.send_json(
            {
                "type": "subscribe",
                "topics": [
                    "import_jobs",
                    "import_job:11111111-1111-1111-1111-111111111111",
                ],
            }
        )
        ack = websocket.receive_json()
        snapshots = [websocket.receive_json(), websocket.receive_json()]

    assert ack["type"] == "subscribed"
    assert ack["topics"] == [
        "import_job:11111111-1111-1111-1111-111111111111",
        "import_jobs",
    ]
    assert {message["topic"] for message in snapshots} == {
        "import_job:11111111-1111-1111-1111-111111111111",
        "import_jobs",
    }


@pytest.mark.unit
@pytest.mark.unit
def test_ops_metrics_maps_counts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops as module

    async def _counts(_session: Any) -> StatusCounts:
        return StatusCounts(
            features_total=10,
            features_active=9,
            features_inactive=1,
            features_by_kind={"place": 8, "event": 2},
            source_records_by_provider={"python-mois-api": 10},
            import_jobs_by_status={"running": 1},
            dedup_queue_by_status={"merged": 1, "rejected": 1, "pending": 2},
        )

    async def _issue_counts(_session: Any) -> OpsIntegrityIssueCounts:
        return OpsIntegrityIssueCounts(
            open_total=3,
            by_status={"open": 3},
            by_severity={"error": 2, "warning": 1},
            by_type={"missing_coordinate": 2, "missing_address": 1},
        )

    async def _latest(_session: Any) -> OpsConsistencyReport:
        return _report()

    monkeypatch.setattr(module, "gather_status_counts", _counts)
    monkeypatch.setattr(module, "get_ops_integrity_issue_counts", _issue_counts)
    monkeypatch.setattr(module, "get_latest_consistency_report", _latest)
    response = client.get("/v1/ops/metrics")

    assert response.status_code == 200
    body = response.json()
    assert "duration_ms" in body["meta"]
    data = body["data"]
    assert data["features_total"] == 10
    assert data["import_jobs_by_status"] == {"running": 1}
    assert data["dedup_fp_stats"]["confirmed"] == 1
    assert data["dedup_fp_stats"]["rejected"] == 1
    assert data["data_integrity_issues"]["open_total"] == 3
    assert data["latest_consistency_report"]["severity_max"] == "WARN"


@pytest.mark.unit
def test_consistency_and_issue_lists_pass_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops as module

    async def _reports(_session: Any, **kwargs: Any) -> OpsConsistencyReportPage:
        assert kwargs == {"severity_max": "WARN", "limit": 5, "cursor": None}
        return OpsConsistencyReportPage(items=(_report(),), next_cursor=None)

    async def _issues(_session: Any, **kwargs: Any) -> OpsIntegrityIssuePage:
        assert kwargs == {
            "status": "open",
            "severity": "error",
            "violation_type": "missing_coordinate",
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
            "feature_id": "feature-1",
            "limit": 5,
            "cursor": None,
        }
        return OpsIntegrityIssuePage(items=(_issue(),), next_cursor=None)

    monkeypatch.setattr(module, "list_ops_consistency_reports", _reports)
    monkeypatch.setattr(module, "list_ops_integrity_issues", _issues)
    reports = client.get("/v1/ops/consistency/reports?severity_max=WARN&page_size=5")
    issues = client.get(
        "/v1/ops/consistency/issues?status=open&severity=error&"
        "violation_type=missing_coordinate&provider=python-mois-api&"
        "dataset_key=mois_license_features_bulk&feature_id=feature-1&page_size=5"
    )

    assert reports.status_code == 200
    assert reports.json()["data"]["items"][0]["summary"]["by_code"] == {"F4": 3}
    assert reports.json()["meta"]["page"]["page_size"] == 5
    assert issues.status_code == 200
    assert issues.json()["data"]["items"][0]["issue_id"] == _issue().issue_id
    assert issues.json()["data"]["items"][0]["message"] == "좌표 없음"
    assert issues.json()["meta"]["page"]["page_size"] == 5


@pytest.mark.unit
def test_health_deep_ok(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops as module
    from kortravelmap.api.routers.ops import OpsHealthCheck

    async def _database(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="database", status="ok")

    async def _postgis(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="postgis", status="ok", detail="3.5")

    async def _prewarm(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(
            component="prewarm",
            status="ok",
            detail="extension=present, autoprewarm=off",
        )

    monkeypatch.setattr(module, "_check_database", _database)
    monkeypatch.setattr(module, "_check_postgis", _postgis)
    monkeypatch.setattr(module, "_check_prewarm", _prewarm)
    response = client.get("/v1/ops/health-deep")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert body["data"]["status"] == "ok"
    assert {check["component"]: check["status"] for check in body["data"]["checks"]} == {
        "database": "ok",
        "postgis": "ok",
        "prewarm": "ok",
    }
    assert "duration_ms" in body["meta"]


@pytest.mark.unit
def test_health_deep_status_follows_required_checks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops as module
    from kortravelmap.api.routers.ops import OpsHealthCheck

    async def _database(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="database", status="error", detail="down")

    async def _postgis(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="postgis", status="ok", detail="3.5")

    async def _prewarm(_session: Any) -> OpsHealthCheck:
        return OpsHealthCheck(component="prewarm", status="ok")

    monkeypatch.setattr(module, "_check_database", _database)
    monkeypatch.setattr(module, "_check_postgis", _postgis)
    monkeypatch.setattr(module, "_check_prewarm", _prewarm)
    response = client.get("/v1/ops/health-deep")

    assert response.status_code == 503
    assert response.json()["data"]["status"] == "degraded"
