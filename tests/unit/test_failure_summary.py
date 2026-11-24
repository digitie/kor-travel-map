"""실패 요약·일시 DB 실패 분류·비밀값 제거 (감사 2026-11-23 §1.3 P1·§4 #15)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from kortravelmap.infra.failure_summary import (
    MAX_FAILURE_MESSAGE_CHARS,
    redact_failure_text,
    summarize_failure,
    transient_db_failure_kind,
)

pytestmark = pytest.mark.unit


class _PgError(Exception):
    """asyncpg 예외 모양 — ``sqlstate`` 속성만 본다."""

    def __init__(self, message: str, sqlstate: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def _driver_error(module: str, name: str) -> Exception:
    return type(name, (Exception,), {"__module__": module})("connection was closed")


@pytest.mark.parametrize(
    ("sqlstate", "kind"),
    [
        ("55P03", "lock_timeout"),
        ("40001", "serialization"),
        ("40P01", "deadlock"),
        ("08006", "connection"),
        ("57P01", "connection"),
        ("53300", "connection"),
        ("23505", None),
        ("42P01", None),
        ("57014", None),  # statement timeout은 결정적으로 본다(느린 질의는 다시 돌려도 느리다)
    ],
)
def test_sqlstate_classification(sqlstate: str, kind: str | None) -> None:
    assert transient_db_failure_kind(_PgError("x", sqlstate)) == kind


def test_sqlalchemy_error_is_classified_through_orig() -> None:
    orig = _PgError("canceling statement due to lock timeout", "55P03")
    wrapped = OperationalError("INSERT INTO ops.import_job_events ...", {"job_id": "x"}, orig)
    assert transient_db_failure_kind(wrapped) == "lock_timeout"


def test_connection_invalidated_and_driver_connection_errors() -> None:
    invalidated = OperationalError("SELECT 1", {}, Exception("gone"))
    invalidated.connection_invalidated = True
    assert transient_db_failure_kind(invalidated) == "connection"
    assert (
        transient_db_failure_kind(
            _driver_error("asyncpg.exceptions", "ConnectionDoesNotExistError")
        )
        == "connection"
    )
    assert transient_db_failure_kind(_driver_error("elsewhere", "InterfaceError")) is None
    # 기반 InterfaceError(하위에 client 쪽 DataError 등)는 연결 끊김이 아니다.
    assert transient_db_failure_kind(_driver_error("asyncpg.exceptions", "InterfaceError")) is None
    assert transient_db_failure_kind(_driver_error("asyncpg.exceptions", "DataError")) is None


def test_explicit_cause_is_followed_but_implicit_context_is_not() -> None:
    wrapped = RuntimeError("provider refresh asset execution failed")
    wrapped.__cause__ = _PgError("lock timeout", "55P03")
    assert transient_db_failure_kind(wrapped) == "lock_timeout"

    deterministic = ValueError("bad scope")
    deterministic.__context__ = _PgError("lock timeout during cleanup", "55P03")
    assert transient_db_failure_kind(deterministic) is None


def test_first_sqlstate_in_the_chain_decides() -> None:
    """바깥에 결정적 SQLSTATE가 있으면 안쪽의 일시 오류로 덮지 않는다."""

    outer = _PgError("duplicate key", "23505")
    outer.__cause__ = _PgError("lock timeout", "55P03")
    assert transient_db_failure_kind(outer) is None


def test_redaction_removes_secrets_and_sql_body() -> None:
    text = (
        "(sqlalchemy.dialects.postgresql.asyncpg.Error) <class 'LockNotAvailableError'>: "
        "canceling statement due to lock timeout\n"
        "[SQL: INSERT INTO ops.import_job_events (job_id) VALUES ($1)]\n"
        "[parameters: ('secret-row',)]\n"
        "(Background on this error at: https://sqlalche.me/e/20/dbapi)"
    )
    cleaned = redact_failure_text(text)
    assert cleaned == (
        "(sqlalchemy.dialects.postgresql.asyncpg.Error) <class 'LockNotAvailableError'>: "
        "canceling statement due to lock timeout"
    )

    secrets = (
        "GET https://apis.data.go.kr/x?serviceKey=ABC123&pageNo=1 "
        "postgresql+asyncpg://ktm:hunter2@db:5432/map token=tok-1 "
        "Authorization: Bearer eyJhbGciOi.x.y password='p w'"
    )
    cleaned = redact_failure_text(secrets)
    for leaked in ("ABC123", "hunter2", "tok-1", "eyJhbGciOi", "p w"):
        assert leaked not in cleaned
    # URL query string은 통째로 걷는다 — provider마다 키 이름이 다르다.
    assert "https://apis.data.go.kr/x?…" in cleaned
    assert "postgresql+asyncpg://***@db:5432/map" in cleaned


@pytest.mark.parametrize(
    "text",
    [
        "GET http://x/y?key=SECRET1&a=1 failed",  # krex·VWorld
        "certkey=SECRET1 rejected",  # OpiNet
        "authKey: SECRET1",  # KMA
        "crtfc_key=SECRET1",  # 공공데이터 계열
        "HTTP 503 for url 'https://host/p/SECRETPATH?serviceKey=SECRET1'",
    ],
)
def test_provider_key_parameters_never_survive(text: str) -> None:
    assert "SECRET1" not in redact_failure_text(text)


def test_redaction_truncates_long_messages() -> None:
    cleaned = redact_failure_text("x" * 1000)
    assert len(cleaned) == MAX_FAILURE_MESSAGE_CHARS
    assert cleaned.endswith("…")


def test_summary_keeps_the_legacy_head_and_appends_the_innermost_cause() -> None:
    plain = summarize_failure(RuntimeError("simulated provider checkpoint failure"))
    assert plain.describe() == "RuntimeError: simulated provider checkpoint failure"
    assert plain.failure_class == "execution"
    assert plain.causes == ()

    class _QuotaError(Exception):
        failure_kind = "quota"

    outer = RuntimeError("provider refresh asset execution failed")
    outer.__cause__ = _QuotaError("LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR")
    summary = summarize_failure(outer)
    assert summary.describe() == (
        "RuntimeError: provider refresh asset execution failed ← 원인 "
        "_QuotaError: LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"
    )
    assert summary.failure_kind == "quota"
    payload = summary.payload()
    assert payload["failure_class"] == "execution"
    assert payload["error_type"] == "RuntimeError"
    assert payload["causes"] == [
        "_QuotaError: LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"
    ]


def test_summary_of_a_lock_timeout_is_transient_and_has_no_sql() -> None:
    orig = _PgError("canceling statement due to lock timeout", "55P03")
    wrapped = OperationalError("INSERT INTO ops.import_job_events VALUES (1)", {}, orig)
    summary = summarize_failure(wrapped)
    assert summary.failure_class == "transient_db"
    assert summary.db_failure == "lock_timeout"
    assert "INSERT INTO" not in summary.describe()
    assert summary.payload()["db_failure"] == "lock_timeout"


def test_a_failure_raised_while_handling_another_keeps_the_masked_cause() -> None:
    """실패를 기록하다 lock timeout이 나면 분류는 바깥(일시)이지만 진짜 원인을 잃지 않는다."""

    original = RuntimeError("provider exploded")
    while_saving = _PgError("canceling statement due to lock timeout", "55P03")
    while_saving.__context__ = original
    summary = summarize_failure(while_saving)
    assert summary.failure_class == "transient_db"
    assert summary.payload()["masked_failure"] == "RuntimeError: provider exploded"
