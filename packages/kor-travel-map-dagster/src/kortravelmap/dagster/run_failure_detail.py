"""Dagster run 실패 이벤트에서 **비밀 없는** 실패 원인을 꺼낸다 (감사 2026-11-23 §1.2·§4 #15).

Map DB에 남는 run 실패 기록은 종전에
``{"kind":"dagster_run_terminal","status":"FAILURE"}``(operation
root)와 ``"Dagster feature update worker failed: run_id=…"``(큐 request)뿐이었다. 원인은 Dagster
event
log에만 있었고, 그것은 n150에서 1.98 GB로 자라 사후 판독이 어렵다.

``RUN_FAILURE`` 이벤트의 ``JobFailureData``는 ``first_step_failure_event``를 들고 온다 — **추가
storage
읽기 없이** 실패한 step과 그 오류를 알 수 있다. launch 실패처럼 step이 없으면 ``error``(또는 이벤트
메시지)를 쓴다. 메시지는 :func:`~kortravelmap.infra.failure_summary.redact_failure_text`로 비밀값과
SQL
본문을 걷는다.

이 함수들은 실패 경로에서만 돈다 — 무엇을 받든 예외를 던지지 않는다(원인 기록이 원인을 덮지 않게).
"""

from __future__ import annotations

from typing import Any, Final

from kortravelmap.infra.failure_summary import redact_failure_text

__all__ = ["describe_run_failure", "failure_detail_text", "run_failure_detail"]

_MAX_CAUSE_DEPTH: Final[int] = 6


def _first_line(text: object) -> str:
    raw = str(text or "").strip()
    return raw.splitlines()[0] if raw else ""


def _strip_qualified_prefix(message: str, cls_name: object) -> str:
    """Dagster가 메시지 앞에 붙이는 ``모듈.클래스: `` 접두를 뗀다 — 타입은 따로 싣는다."""

    if not isinstance(cls_name, str) or not cls_name:
        return message
    head, separator, rest = message.partition(": ")
    if separator and (head == cls_name or head.endswith("." + cls_name)):
        return rest
    return message


def _error_parts(error: Any) -> dict[str, str]:
    """``SerializableErrorInfo``에서 타입·메시지·가장 안쪽 원인을 꺼낸다."""

    parts: dict[str, str] = {}
    cls_name = getattr(error, "cls_name", None)
    if isinstance(cls_name, str) and cls_name:
        parts["error_type"] = cls_name
    message = redact_failure_text(
        _strip_qualified_prefix(_first_line(getattr(error, "message", "")), cls_name)
    )
    if message:
        parts["error"] = message
    cause = getattr(error, "cause", None)
    innermost: Any = None
    depth = 0
    while cause is not None and depth < _MAX_CAUSE_DEPTH:
        innermost = cause
        cause = getattr(cause, "cause", None)
        depth += 1
    if innermost is not None:
        cause_type = getattr(innermost, "cls_name", None) or "Exception"
        cause_message = redact_failure_text(
            _strip_qualified_prefix(_first_line(getattr(innermost, "message", "")), cause_type)
        )
        parts["cause"] = f"{cause_type}: {cause_message}" if cause_message else str(cause_type)
    return parts


def run_failure_detail(failure_event: Any) -> dict[str, str]:
    """``RUN_FAILURE`` :class:`dagster.DagsterEvent`에서 실패 원인 요약을 만든다. 없으면 빈 dict."""

    detail: dict[str, str] = {}
    try:
        data = getattr(failure_event, "event_specific_data", None)
        reason = getattr(data, "failure_reason", None)
        if reason is not None:
            detail["failure_reason"] = str(getattr(reason, "value", reason))
        step_event = getattr(data, "first_step_failure_event", None)
        error: Any = None
        if step_event is not None:
            step_key = getattr(step_event, "step_key", None)
            if isinstance(step_key, str) and step_key:
                detail["failed_step"] = step_key
            error = getattr(getattr(step_event, "event_specific_data", None), "error", None)
        if error is None:
            error = getattr(data, "error", None)
        if error is not None:
            detail.update(_error_parts(error))
        elif "error" not in detail:
            message = redact_failure_text(_first_line(getattr(failure_event, "message", "")))
            if message:
                detail["error"] = message
    except Exception:  # noqa: BLE001 — 원인 기록이 실패 처리 자체를 깨면 안 된다
        return detail
    return detail


def failure_detail_text(detail: dict[str, str]) -> str:
    """``step x: Type: msg ← 원인 Type: msg`` — 비어 있으면 빈 문자열."""

    body: list[str] = []
    if "failed_step" in detail:
        body.append(f"step {detail['failed_step']}")
    error = detail.get("error")
    error_type = detail.get("error_type")
    if error_type and error:
        body.append(f"{error_type}: {error}")
    elif error:
        body.append(error)
    elif error_type:
        body.append(error_type)
    text = ": ".join(body)
    if "cause" in detail:
        text = f"{text} ← 원인 {detail['cause']}" if text else f"원인 {detail['cause']}"
    return redact_failure_text(text, limit=600)


def describe_run_failure(run_id: str, detail: dict[str, str]) -> str:
    """운영자가 읽을 한 줄 — ``Dagster run <id> 실패 — step x: Type: msg ← 원인 Type: msg``."""

    body = failure_detail_text(detail)
    head = f"Dagster run {run_id} 실패"
    return f"{head} — {body}" if body else head
