"""``test_consistency`` — ``build_report`` 순수 집계 로직 (DB 무관, ADR-033).

``run_consistency_checks``의 DB 경로는 ``tests/integration/test_consistency_reports.py``
(testcontainers)에서 검증. 본 모듈은 severity_max / summary 집계 규칙만 단위 검증.
"""

from __future__ import annotations

from typing import Any

import pytest

from krtour.map.infra.consistency import (
    CONSISTENCY_CASES,
    CaseResult,
    FileObjectRef,
    _build_f7_dedup_score_result,
    _build_f8_file_object_orphan_result,
    _check_f4_dedup_backlog,
    _check_f5_provider_last_success_sla,
    _check_f7_dedup_score_regression,
    _check_f8_file_object_orphans,
    build_report,
    run_consistency_checks,
)


def _case(code: str, severity: str, count: int) -> CaseResult:
    return CaseResult(
        code=code,
        severity=severity,
        description=f"{code} desc",
        count=count,
        sample_ids=[f"{code}-{i}" for i in range(min(count, 3))],
    )


class _FakeResult:
    def __init__(self, *, scalar: int | None = None, rows: list[Any] | None = None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one(self) -> int:
        assert self._scalar is not None
        return self._scalar

    def scalars(self) -> _FakeResult:
        return self

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results
        self.calls: list[tuple[Any, Any]] = []

    async def execute(self, statement: Any, params: Any = None) -> _FakeResult:
        self.calls.append((statement, params))
        return self._results.pop(0)


def test_static_cases_declares_f1_f2_f3_f6_all_error() -> None:
    codes = [c.code for c in CONSISTENCY_CASES]
    assert codes == ["F1", "F2", "F3", "F6"]
    assert all(c.severity == "ERROR" for c in CONSISTENCY_CASES)


def test_f3_postgis_functions_are_schema_qualified() -> None:
    f3 = next(case for case in CONSISTENCY_CASES if case.code == "F3")

    assert "x_extension.ST_SRID" in f3.sql
    assert "x_extension.ST_DWithin" in f3.sql
    assert "x_extension.ST_Transform" in f3.sql


def test_f6_scans_feature_table_once_before_lateral_period_expansion() -> None:
    f6 = next(case for case in CONSISTENCY_CASES if case.code == "F6")

    assert f6.sql.count("FROM feature.features f") == 1
    assert "WITH candidate_features AS" in f6.sql
    assert "FROM candidate_features f" in f6.sql
    assert "CROSS JOIN LATERAL (" in f6.sql
    assert f6.sql.count("jsonb_path_query(") == 4


def test_build_report_all_clean_is_ok() -> None:
    cases = [_case("F1", "ERROR", 0), _case("F2", "ERROR", 0), _case("F3", "ERROR", 0)]
    report = build_report("batch-1", cases)

    assert report.severity_max == "OK"
    assert cases[0].ok
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


@pytest.mark.asyncio
async def test_check_f4_dedup_backlog_warns_over_threshold() -> None:
    session = _FakeSession([_FakeResult(scalar=3), _FakeResult(rows=["rk-high", "rk-low"])])

    result = await _check_f4_dedup_backlog(session, threshold=2, sample_limit=2)  # type: ignore[arg-type]

    assert result.code == "F4"
    assert result.severity == "WARN"
    assert result.count == 1
    assert result.metadata == {
        "pending_count": 3,
        "threshold": 2,
        "over_threshold": True,
    }
    assert result.sample_ids == ["rk-high", "rk-low"]
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_check_f4_dedup_backlog_ok_below_threshold_skips_sample_query() -> None:
    session = _FakeSession([_FakeResult(scalar=1)])

    result = await _check_f4_dedup_backlog(session, threshold=2, sample_limit=2)  # type: ignore[arg-type]

    assert result.code == "F4"
    assert result.count == 0
    assert result.metadata == {
        "pending_count": 1,
        "threshold": 2,
        "over_threshold": False,
    }
    assert result.sample_ids == []
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_check_f5_provider_last_success_sla_warns_with_samples() -> None:
    session = _FakeSession(
        [_FakeResult(scalar=2), _FakeResult(rows=["provider:a:system", "provider:b:system"])]
    )

    result = await _check_f5_provider_last_success_sla(
        session,
        sla_seconds=86400,
        sample_limit=2,  # type: ignore[arg-type]
    )

    assert result.code == "F5"
    assert result.severity == "WARN"
    assert result.count == 2
    assert result.sample_ids == ["provider:a:system", "provider:b:system"]
    assert "86400" in result.description


@pytest.mark.asyncio
async def test_check_f5_provider_last_success_sla_ok_skips_sample_query() -> None:
    session = _FakeSession([_FakeResult(scalar=0)])

    result = await _check_f5_provider_last_success_sla(
        session,
        sla_seconds=86400,
        sample_limit=2,  # type: ignore[arg-type]
    )

    assert result.code == "F5"
    assert result.count == 0
    assert result.sample_ids == []
    assert len(session.calls) == 1


def test_build_f7_dedup_score_result_counts_regressions_and_limits_samples() -> None:
    rows = [
        {
            "review_key": "rk-regressed",
            "feature_id_a": "f7-a",
            "feature_id_b": "f7-b",
            "baseline_score": 95.0,
            "name_a": "가나다",
            "name_b": "XYZ",
            "category_a": "CAT.A",
            "category_b": "CAT.B",
            "lon_a": 126.9784,
            "lat_a": 37.5665,
            "lon_b": 126.9784,
            "lat_b": 37.5665,
        },
        {
            "review_key": "rk-stable",
            "feature_id_a": "f7-c",
            "feature_id_b": "f7-d",
            "baseline_score": 95.0,
            "name_a": "경복궁",
            "name_b": "경복궁",
            "category_a": "HERITAGE.PALACE",
            "category_b": "HERITAGE.PALACE",
            "lon_a": 126.9769,
            "lat_a": 37.5796,
            "lon_b": 126.9769,
            "lat_b": 37.5796,
        },
        {
            "review_key": "rk-no-coord",
            "feature_id_a": "f7-e",
            "feature_id_b": "f7-f",
            "baseline_score": 95.0,
            "name_a": "남산타워",
            "name_b": "남산타워",
            "category_a": "VIEW.TOWER",
            "category_b": "VIEW.TOWER",
            "lon_a": None,
            "lat_a": None,
            "lon_b": None,
            "lat_b": None,
        },
    ]

    result = _build_f7_dedup_score_result(rows, regression_points=10.0, sample_limit=1)

    assert result.code == "F7"
    assert result.severity == "WARN"
    assert result.count == 2
    assert len(result.sample_ids) == 1
    assert result.sample_ids[0].startswith("rk-regressed:f7-a:f7-b:95.00->")


@pytest.mark.asyncio
async def test_check_f7_dedup_score_regression_delegates_sql_rows() -> None:
    session = _FakeSession(
        [
            _FakeResult(
                rows=[
                    {
                        "review_key": "rk-regressed",
                        "feature_id_a": "f7-a",
                        "feature_id_b": "f7-b",
                        "baseline_score": 95.0,
                        "name_a": "가나다",
                        "name_b": "XYZ",
                        "category_a": "CAT.A",
                        "category_b": "CAT.B",
                        "lon_a": 126.9784,
                        "lat_a": 37.5665,
                        "lon_b": 126.9784,
                        "lat_b": 37.5665,
                    }
                ]
            )
        ]
    )

    result = await _check_f7_dedup_score_regression(
        session,
        regression_points=10.0,
        sample_limit=5,  # type: ignore[arg-type]
    )

    assert result.code == "F7"
    assert result.count == 1
    assert result.sample_ids[0].startswith("rk-regressed:f7-a:f7-b:95.00->")
    assert len(session.calls) == 1


def test_build_f8_file_object_orphan_result_compares_metadata_and_objects() -> None:
    rows = [
        {
            "file_id": "file-missing-object",
            "feature_id": "feature-active",
            "storage_backend": "s3",
            "bucket": "krtour-map",
            "object_key": "missing-object.jpg",
            "feature_missing": False,
        },
        {
            "file_id": "file-missing-feature",
            "feature_id": "feature-deleted",
            "storage_backend": "s3",
            "bucket": "krtour-map",
            "object_key": "deleted-feature.jpg",
            "feature_missing": True,
        },
    ]
    known_objects = [
        FileObjectRef(
            storage_backend="s3",
            bucket="krtour-map",
            object_key="deleted-feature.jpg",
        ),
        FileObjectRef(
            storage_backend="s3",
            bucket="krtour-map",
            object_key="object-without-metadata.jpg",
        ),
    ]

    result = _build_f8_file_object_orphan_result(
        rows,
        known_file_objects=known_objects,
        sample_limit=2,
    )

    assert result.code == "F8"
    assert result.severity == "WARN"
    assert result.count == 3
    assert result.metadata == {
        "metadata_file_issue_count": 2,
        "object_missing_metadata_count": 1,
    }
    assert result.sample_ids == [
        "metadata_missing_object:s3:krtour-map:missing-object.jpg:"
        "file-missing-object:feature-active",
        "metadata_without_active_feature:s3:krtour-map:deleted-feature.jpg:"
        "file-missing-feature:feature-deleted",
    ]


def test_build_f8_file_object_orphan_result_counts_same_file_once_for_multiple_issues() -> None:
    rows = [
        {
            "file_id": "file-double-issue",
            "feature_id": "feature-deleted",
            "storage_backend": "s3",
            "bucket": "krtour-map",
            "object_key": "missing-and-deleted.jpg",
            "feature_missing": True,
        }
    ]

    result = _build_f8_file_object_orphan_result(
        rows,
        known_file_objects=[],
        sample_limit=5,
    )

    assert result.code == "F8"
    assert result.count == 1
    assert result.metadata == {
        "metadata_file_issue_count": 1,
        "object_missing_metadata_count": 0,
    }
    assert result.sample_ids == [
        "metadata_without_active_feature:s3:krtour-map:missing-and-deleted.jpg:"
        "file-double-issue:feature-deleted",
        "metadata_missing_object:s3:krtour-map:missing-and-deleted.jpg:"
        "file-double-issue:feature-deleted",
    ]


@pytest.mark.asyncio
async def test_check_f8_file_object_orphans_missing_table_still_flags_known_objects() -> None:
    session = _FakeSession([_FakeResult(scalar=0)])

    result = await _check_f8_file_object_orphans(
        session,
        known_file_objects=[
            FileObjectRef(storage_backend="s3", bucket="krtour-map", object_key="orphan.jpg")
        ],
        sample_limit=5,  # type: ignore[arg-type]
    )

    assert result.code == "F8"
    assert result.count == 1
    assert result.sample_ids == ["object_missing_metadata:s3:krtour-map:orphan.jpg"]
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_run_consistency_checks_evaluates_dynamic_cases_and_persists() -> None:
    session: Any = _FakeSession(
        [
            _FakeResult(scalar=0),  # F1 count
            _FakeResult(scalar=1),  # F2 count
            _FakeResult(rows=["feature-missing-detail"]),  # F2 samples
            _FakeResult(scalar=0),  # F3 count
            _FakeResult(scalar=0),  # F6 count
            _FakeResult(scalar=2),  # F4 pending count
            _FakeResult(rows=["rk-pending-1", "rk-pending-2"]),  # F4 samples
            _FakeResult(scalar=1),  # F5 stale count
            _FakeResult(rows=["provider:dataset:scope"]),  # F5 samples
            _FakeResult(
                rows=[
                    {
                        "review_key": "rk-regressed",
                        "feature_id_a": "f7-a",
                        "feature_id_b": "f7-b",
                        "baseline_score": 95.0,
                        "name_a": "가나다",
                        "name_b": "XYZ",
                        "category_a": "CAT.A",
                        "category_b": "CAT.B",
                        "lon_a": 126.9784,
                        "lat_a": 37.5665,
                        "lon_b": 126.9784,
                        "lat_b": 37.5665,
                    }
                ]
            ),
            _FakeResult(scalar=0),  # F8 feature_files table exists
            _FakeResult(),  # persist insert
        ]
    )

    report = await run_consistency_checks(
        session,
        batch_id="batch-unit",
        persist=True,
        sample_limit=2,
        dedup_pending_threshold=1,
        provider_last_success_sla_seconds=3600,
        dedup_score_regression_warn_points=10.0,
    )

    assert report.batch_id == "batch-unit"
    assert report.severity_max == "ERROR"
    assert report.summary["total_violations"] == 4
    assert report.summary["cases_evaluated"] == 8
    assert report.summary["by_code"] == {
        "F1": 0,
        "F2": 1,
        "F3": 0,
        "F6": 0,
        "F4": 1,
        "F5": 1,
        "F7": 1,
        "F8": 0,
    }
    assert report.summary["case_metadata"]["F4"] == {
        "pending_count": 2,
        "threshold": 1,
        "over_threshold": True,
    }
    assert report.cases_json()[1]["sample_ids"] == ["feature-missing-detail"]
    by_code = {case["code"]: case for case in report.cases_json()}
    assert by_code["F4"]["metadata"]["pending_count"] == 2
    assert by_code["F7"]["sample_ids"][0].startswith("rk-regressed:f7-a:f7-b:95.00->")
    assert len(session.calls) == 12
    assert session.calls[-1][1]["batch_id"] == "batch-unit"
    assert session.calls[-1][1]["severity_max"] == "ERROR"
