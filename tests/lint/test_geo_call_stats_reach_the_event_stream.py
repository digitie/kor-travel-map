"""geo 경계 계수가 **Dagster event stream까지 닿는지** 센다.

계측은 기록되는 곳까지 가야 계측이다. 2026-09-19의 증상이 정확히 "3시간 동안
dagster 이벤트 0건"이었고, 그때 컨테이너 stdout에는 무언가 있었을지 몰라도
event stream에는 아무것도 없었다. `docker/dagster.yaml`의 `managed_python_loggers`에
모듈 이름이 없으면 그 모듈의 표준 logging은 stdout에만 남는다.

**이 검사는 문자열 비교가 아니다.** yaml에 적힌 이름으로 logger를 만들고 거기에
핸들러를 붙인 뒤, resource 모듈이 **실제로 쓰는 logger 객체**에 레코드를 흘려
그 핸들러가 받는지를 본다. 그래야 (a) 이름 오타, (b) 로거를 다른 이름으로 바꾼
리팩터링, (c) `propagate = False` 같은 조용한 차단이 전부 잡힌다.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any, Final

import pytest
import yaml

REPO_ROOT: Final = pathlib.Path(__file__).resolve().parents[2]
_DAGSTER_YAML: Final = REPO_ROOT / "docker" / "dagster.yaml"

#: 계수가 WARNING으로 나가는 이유 — yaml의 `python_log_level`이 WARNING이다.
#: INFO로 내리면 event stream에 실리지 않는다.
_REQUIRED_LEVEL: Final = logging.WARNING


def _dagster_yaml() -> dict[str, Any]:
    return yaml.safe_load(_DAGSTER_YAML.read_text(encoding="utf-8"))


def _managed_loggers() -> list[str]:
    logs = _dagster_yaml().get("python_logs") or {}
    return list(logs.get("managed_python_loggers") or [])


def _covers(managed_name: str, record_logger: logging.Logger) -> bool:
    """``managed_name``으로 만든 logger가 ``record_logger``의 레코드를 **받는가**.

    핸들러를 붙여 실제로 흘려 본다 — 이름 접두 비교로 대신하지 않는다.
    그러면 `propagate = False`나 필터를 못 본다.
    """

    target = logging.getLogger(managed_name)
    received: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record)

    handler = _Capture(level=logging.NOTSET)
    previous_level = target.level
    target.addHandler(handler)
    target.setLevel(logging.NOTSET)
    try:
        record_logger.warning("geo 경계 계수 배선 확인용 레코드")
    finally:
        target.removeHandler(handler)
        target.setLevel(previous_level)
    return bool(received)


def _resources_logger() -> logging.Logger:
    from kortravelmap.dagster import resources

    logger = getattr(resources, "_LOGGER", None)
    assert isinstance(logger, logging.Logger), (
        "`kortravelmap.dagster.resources`에 모듈 logger가 없다 — geo 경계 계수를 "
        "내보낼 통로가 사라졌다."
    )
    return logger


def test_the_managed_logger_list_is_not_empty() -> None:
    """항진명제 방지 — 목록이 비면 아래 검사가 아무것도 요구하지 않는다."""

    managed = _managed_loggers()
    assert managed, (
        "`docker/dagster.yaml`의 `managed_python_loggers`가 비었다 — 표준 logging이 "
        "Dagster event stream에 하나도 실리지 않는다."
    )


def test_the_geo_stats_logger_is_actually_captured() -> None:
    """resource가 **실제로 쓰는 logger**의 레코드를 yaml 항목이 받아야 한다."""

    logger = _resources_logger()
    managed = _managed_loggers()
    covering = [name for name in managed if _covers(name, logger)]
    assert covering, (
        f"`{logger.name}`의 레코드를 받는 항목이 `managed_python_loggers`에 없다 "
        f"(현재 목록: {managed}). geo 경계 계수가 컨테이너 stdout에만 남고 Dagster "
        "event stream에는 안 보인다 — 2026-09-19의 증상이 정확히 '이벤트 0건'이었다."
    )


def test_the_configured_level_admits_the_geo_stats_record() -> None:
    """`python_log_level`이 WARNING보다 높으면 계수가 조용히 사라진다."""

    logs = _dagster_yaml().get("python_logs") or {}
    configured = str(logs.get("python_log_level", "WARNING")).upper()
    level = logging.getLevelNamesMapping().get(configured)
    assert level is not None, f"알 수 없는 python_log_level: {configured!r}"
    assert level <= _REQUIRED_LEVEL, (
        f"`python_log_level={configured}`이 WARNING을 걸러낸다 — geo 경계 계수는 "
        "WARNING으로 나간다(그 자리 주석 참조)."
    )


@pytest.mark.parametrize("managed_name", _managed_loggers())
def test_every_managed_logger_name_resolves_to_a_real_module(
    managed_name: str,
) -> None:
    """목록의 이름이 실재하는 모듈이어야 한다 — 오타는 조용한 no-op이다."""

    import importlib.util

    assert importlib.util.find_spec(managed_name) is not None, (
        f"`managed_python_loggers`의 `{managed_name}`이 import 가능한 모듈이 아니다. "
        "Dagster는 이 이름으로 logger를 만들 뿐이므로 오타가 에러 없이 지나간다."
    )
