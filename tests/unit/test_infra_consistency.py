"""``test_consistency`` — ``build_report`` 순수 집계 로직 (DB 무관, ADR-033 Phase 1).

``run_consistency_checks``의 DB 경로는 ``tests/integration/test_consistency_reports.py``
(testcontainers)에서 검증. 본 모듈은 severity_max / summary 집계 규칙만 단위 검증.
"""

from __future__ import annotations

from krtour.map.infra.consistency import (
    CONSISTENCY_CASES,
    CaseResult,
    build_report,
)


def _case(code: str, severity: str, count: int) -> CaseResult:
    return CaseResult(
        code=code,
        severity=severity,
        description=f"{code} desc",
        count=count,
        sample_ids=[f"{code}-{i}" for i in range(min(count, 3))],
    )


def test_phase1_declares_f1_f2_f3_all_error() -> None:
    codes = [c.code for c in CONSISTENCY_CASES]
    assert codes == ["F1", "F2", "F3"]
    assert all(c.severity == "ERROR" for c in CONSISTENCY_CASES)


def test_build_report_all_clean_is_ok() -> None:
    cases = [_case("F1", "ERROR", 0), _case("F2", "ERROR", 0), _case("F3", "ERROR", 0)]
    report = build_report("batch-1", cases)

    assert report.severity_max == "OK"
    assert report.summary["total_violations"] == 0
    assert report.summary["by_severity"] == {"ERROR": 0, "WARN": 0}
    assert report.summary["by_code"] == {"F1": 0, "F2": 0, "F3": 0}
    # effective severity는 위반 0건이면 OK로 표기.
    assert all(c["severity"] == "OK" for c in report.cases_json())


def test_build_report_error_violation_sets_severity_max() -> None:
    cases = [_case("F1", "ERROR", 2), _case("F2", "ERROR", 0), _case("F3", "ERROR", 0)]
    report = build_report("batch-2", cases)

    assert report.severity_max == "ERROR"
    assert report.summary["total_violations"] == 2
    assert report.summary["by_code"]["F1"] == 2
    f1 = next(c for c in report.cases_json() if c["code"] == "F1")
    assert f1["severity"] == "ERROR"
    assert f1["count"] == 2
    assert f1["sample_ids"] == ["F1-0", "F1-1"]


def test_build_report_warn_only_is_warn_not_error() -> None:
    cases = [_case("F1", "ERROR", 0), _case("X", "WARN", 3)]
    report = build_report("batch-3", cases)

    assert report.severity_max == "WARN"
    assert report.summary["by_severity"] == {"ERROR": 0, "WARN": 3}


def test_build_report_error_outranks_warn() -> None:
    cases = [_case("X", "WARN", 5), _case("F1", "ERROR", 1)]
    report = build_report("batch-4", cases)

    assert report.severity_max == "ERROR"
    assert report.summary["total_violations"] == 6
