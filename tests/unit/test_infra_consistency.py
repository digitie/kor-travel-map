"""``test_consistency`` — ``build_report`` 순수 집계 로직 (DB 무관, ADR-033).

``run_consistency_checks``의 DB 경로는 ``tests/integration/test_consistency_reports.py``
(testcontainers)에서 검증. 본 모듈은 severity_max / summary 집계 규칙만 단위 검증.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.infra.backup import BackupArtifact
from kortravelmap.infra.consistency import (
    BACKUP_LAST_SUCCESS_WARN_SECONDS,
    CONSISTENCY_CASES,
    CaseResult,
    FileObjectRef,
    _build_f7_dedup_score_result,
    _build_f8_file_object_orphan_result,
    _check_f4_dedup_backlog,
    _check_f5_provider_last_success_sla,
    _check_f7_dedup_score_regression,
    _check_f8_file_object_orphans,
    _check_f9_backup_staleness,
    _is_successful_backup_artifact,
    build_report,
    run_consistency_checks,
)
from kortravelmap.settings import (
    BACKUP_LAST_SUCCESS_WARN_HOURS_DEFAULT,
    KorTravelMapSettings,
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


def test_static_cases_declares_f1_f2_f2g_f3_f6_all_error() -> None:
    """정적 케이스 목록과 순서를 못 박는다.

    ADR-099 2단계가 `F2G`를 더했다 — geometry가 subtype 행 바깥으로 나가면서
    "geometry 없는 route"를 즉시 거절하던 `geom NOT NULL`이 COMMIT 시점 DEFERRABLE
    FK로 바뀌었고, 복구·복제 세션이 그 창을 지날 수 있기 때문이다(F2와 같은 성격의
    보상 관측). 순서는 아래 `run_consistency_checks` 대역이 결과를 **순서대로**
    돌려주므로 계약이다.
    """

    codes = [c.code for c in CONSISTENCY_CASES]
    assert codes == ["F1", "F2", "F2G", "F3", "F6"]
    assert all(c.severity == "ERROR" for c in CONSISTENCY_CASES)


def test_f3_postgis_functions_are_schema_qualified() -> None:
    f3 = next(case for case in CONSISTENCY_CASES if case.code == "F3")

    assert "x_extension.ST_SRID" in f3.sql
    assert "x_extension.ST_DWithin" in f3.sql
    assert "x_extension.ST_Transform" in f3.sql


def test_f5_uses_canonical_dataset_identity_for_state_and_policy() -> None:
    from kortravelmap.infra import consistency

    count_sql = consistency._F5_PROVIDER_LAST_SUCCESS_COUNT_SQL
    sample_sql = consistency._F5_PROVIDER_LAST_SUCCESS_SAMPLE_SQL

    for sql in (count_sql, sample_sql):
        assert "s.provider_dataset_id" in sql
        assert "p.provider_dataset_id = s.provider_dataset_id" in sql
        assert "p.provider = s.provider" not in sql
        assert "p.dataset_key = s.dataset_key" not in sql
    assert "JOIN provider_sync.provider_datasets dataset" in sample_sql
    # sample id는 ``pk_provider_sync_state``와 같은 triple이라야 한다 — pair로 합성하면
    # operation만 다른 두 stale 상태가 같은 id로 중복 표시된다.
    assert "s.provider_dataset_id::text || ':' || s.sync_scope " in sample_sql
    assert "|| ':' || s.operation_key AS id" in sample_sql
    assert "ORDER BY provider_dataset_id, sync_scope, operation_key" in sample_sql


def test_f6_narrows_candidates_by_subtype_columns_before_lateral_expansion() -> None:
    """T-VN-35(ADR-086) — opening_hours 보유 kind는 place/event 둘뿐이고, 그
    값은 subtype 컬럼이 정본이다. 후보를 subtype에서 좁혀야
    ``idx_feature_places_opening_hours`` partial index가 구동된다(core detail
    표현식 인덱스의 대체). core ``features``는 lifecycle 확인용으로만 조인한다.
    """
    f6 = next(case for case in CONSISTENCY_CASES if case.code == "F6")

    assert "WITH candidate_features AS" in f6.sql
    assert "FROM feature.feature_places p " in f6.sql
    assert "FROM feature.feature_events e " in f6.sql
    assert "p.business_hours IS NOT NULL" in f6.sql
    assert "e.opening_hours IS NOT NULL" in f6.sql
    # core detail 문자열 탐침은 되돌아오면 안 된다(컬럼 자체가 없다).
    assert "f.detail" not in f6.sql
    assert "FROM candidate_features c" in f6.sql
    assert "CROSS JOIN LATERAL (" in f6.sql
    assert f6.sql.count("jsonb_path_query(") == 4


def test_f2_detects_missing_subtype_rows_not_empty_detail() -> None:
    """F2의 판정 축 교정 — 조립 뷰는 subtype이 없어도 비어있지 않은 detail을
    내므로 ``detail = '{}'`` 술어는 영영 0건이다. 정확한 축은 subtype 결측이다.
    """
    f2 = next(case for case in CONSISTENCY_CASES if case.code == "F2")

    assert "feature.feature_places" in f2.sql
    assert "feature.feature_areas" in f2.sql
    assert "s.feature_id IS NULL" in f2.sql
    assert "detail" not in f2.sql


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
    session = _FakeSession([_FakeResult(scalar=2), _FakeResult(rows=["41:system", "42:system"])])

    result = await _check_f5_provider_last_success_sla(
        session,
        sla_seconds=86400,
        sample_limit=2,  # type: ignore[arg-type]
    )

    assert result.code == "F5"
    assert result.severity == "WARN"
    assert result.count == 2
    assert result.sample_ids == ["41:system", "42:system"]
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
            "review_id": "rk-regressed",
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
            "review_id": "rk-stable",
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
            "review_id": "rk-no-coord",
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
                        "review_id": "rk-regressed",
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
            "bucket": "kor-travel-map",
            "object_key": "missing-object.jpg",
            "feature_missing": False,
        },
        {
            "file_id": "file-missing-feature",
            "feature_id": "feature-deleted",
            "storage_backend": "s3",
            "bucket": "kor-travel-map",
            "object_key": "deleted-feature.jpg",
            "feature_missing": True,
        },
    ]
    known_objects = [
        FileObjectRef(
            storage_backend="s3",
            bucket="kor-travel-map",
            object_key="deleted-feature.jpg",
        ),
        FileObjectRef(
            storage_backend="s3",
            bucket="kor-travel-map",
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
        "metadata_missing_object:s3:kor-travel-map:missing-object.jpg:"
        "file-missing-object:feature-active",
        "metadata_without_active_feature:s3:kor-travel-map:deleted-feature.jpg:"
        "file-missing-feature:feature-deleted",
    ]


def test_build_f8_file_object_orphan_result_counts_same_file_once_for_multiple_issues() -> None:
    rows = [
        {
            "file_id": "file-double-issue",
            "feature_id": "feature-deleted",
            "storage_backend": "s3",
            "bucket": "kor-travel-map",
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
        "metadata_without_active_feature:s3:kor-travel-map:missing-and-deleted.jpg:"
        "file-double-issue:feature-deleted",
        "metadata_missing_object:s3:kor-travel-map:missing-and-deleted.jpg:"
        "file-double-issue:feature-deleted",
    ]


@pytest.mark.asyncio
async def test_check_f8_file_object_orphans_missing_table_still_flags_known_objects() -> None:
    session = _FakeSession([_FakeResult(scalar=0)])

    result = await _check_f8_file_object_orphans(
        session,
        known_file_objects=[
            FileObjectRef(storage_backend="s3", bucket="kor-travel-map", object_key="orphan.jpg")
        ],
        sample_limit=5,  # type: ignore[arg-type]
    )

    assert result.code == "F8"
    assert result.count == 1
    assert result.sample_ids == ["object_missing_metadata:s3:kor-travel-map:orphan.jpg"]
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_run_consistency_checks_evaluates_dynamic_cases_and_persists() -> None:
    session: Any = _FakeSession(
        [
            _FakeResult(scalar=0),  # F1 count
            _FakeResult(scalar=1),  # F2 count
            _FakeResult(rows=["feature-missing-detail"]),  # F2 samples
            _FakeResult(scalar=0),  # F2G count (route geometry 행 결측)
            _FakeResult(scalar=0),  # F3 count
            _FakeResult(scalar=0),  # F6 count
            _FakeResult(scalar=2),  # F4 pending count
            _FakeResult(rows=["rk-pending-1", "rk-pending-2"]),  # F4 samples
            _FakeResult(scalar=1),  # F5 stale count
            _FakeResult(rows=["provider:dataset:scope"]),  # F5 samples
            _FakeResult(
                rows=[
                    {
                        "review_id": "rk-regressed",
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
    # ADR-099 2단계가 F2G를 더해 정적 케이스가 넷에서 다섯이 됐다.
    assert report.summary["cases_evaluated"] == 10
    assert report.summary["by_code"] == {
        "F1": 0,
        "F2": 1,
        "F2G": 0,
        "F3": 0,
        "F6": 0,
        "F4": 1,
        "F5": 1,
        "F7": 1,
        "F8": 0,
        # backup_root 미제공 → F9는 아무것도 재지 않았다. session을 쓰지 않으므로
        # 아래 ``session.calls`` 수는 F9 추가로 달라지지 않는다.
        "F9": 0,
    }
    assert report.summary["case_metadata"]["F9"] == {
        "observed": False,
        "reason": "backup_root_not_provided",
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


# ── F9 backup staleness (T-VN-H49-BACKUP-STALENESS) ────────────────────────
#
# 아래 테스트가 재현하는 것은 2026-09-16에 실제로 일어난 상태다: geo 예약 백업이
# 2026-09-11 12:30Z부터 425회 연속 실패했고 마지막 성공은 09-10 12:00Z였으며, 그동안
# retention GC만 정상 동작해 09-07 artifact를 TTL로 지웠다. 5일간 아무 경보도 없었다.
_SLA_48H = BACKUP_LAST_SUCCESS_WARN_SECONDS


def _write_backup_artifact(
    root: Path,
    backup_id: str,
    *,
    created_at: datetime | None,
    manifest: str = "ok",
    with_checksums: bool = True,
) -> Path:
    """실제 ``scripts/docker-backup.sh``가 남기는 모양으로 artifact 디렉터리를 쓴다.

    ``list_backup_artifacts``의 진짜 파서를 통과시키기 위해서다 — ``BackupArtifact``를
    손으로 만들어 넣으면 manifest/checksum 판독이 테스트에서 빠지고, 그 판독이 바로
    "반쯤 쓰인 artifact를 성공으로 세지 않는다"의 전부다.
    """
    path = root / backup_id
    (path / "meta").mkdir(parents=True)
    if manifest == "invalid":
        (path / "meta" / "manifest.json").write_text("{not json", encoding="utf-8")
    elif manifest == "ok":
        payload: dict[str, Any] = {
            "schema_version": 1,
            "backup_id": backup_id,
            "mode": "docker-compose-cold-backup",
        }
        if created_at is not None:
            payload["created_at_utc"] = created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        (path / "meta" / "manifest.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    if with_checksums:
        # 실제 스크립트는 이 파일을 **마지막에** 쓴다. 그래서 이 파일의 유무가 곧
        # "완결됐는가"다.
        (path / "meta" / "SHA256SUMS").write_text(
            "0" * 64 + "  meta/manifest.json\n", encoding="utf-8"
        )
    return path


def _incident_root(tmp_path: Path) -> Path:
    """09-08·09-09·09-10 세 건이 남아 있는 사고 당시 디렉터리."""
    root = tmp_path / "backups"
    root.mkdir()
    for day in (8, 9, 10):
        _write_backup_artifact(
            root,
            f"kor_travel_geo_backup_202609{day:02d}",
            created_at=datetime(2026, 9, day, 12, 0, tzinfo=UTC),
        )
    return root


def test_f9_incident_three_artifacts_with_five_day_old_newest_warns(tmp_path: Path) -> None:
    root = _incident_root(tmp_path)

    result = _check_f9_backup_staleness(
        root,
        sla_seconds=_SLA_48H,
        sample_limit=5,
        now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )

    assert result.code == "F9"
    assert result.severity == "WARN"
    assert result.count == 1
    assert result.to_dict()["severity"] == "WARN"
    assert result.metadata["stale"] is True
    assert result.metadata["newest_success_backup_id"] == "kor_travel_geo_backup_20260910"
    assert result.metadata["newest_success_age_seconds"] == 5 * 86400
    assert result.sample_ids == [
        "stale_newest_success:kor_travel_geo_backup_20260910:2026-09-10T12:00:00+00:00"
    ]
    # 보유 쪽은 **멀쩡하다.** 개수를 판정에 넣는 검사였다면 여기서 "3건, 정상"이라고
    # 답했을 것이다 — 그것이 이 사고가 5일간 조용했던 이유다.
    assert result.metadata["artifact_count"] == 3
    assert result.metadata["success_count"] == 3
    assert result.metadata["incomplete_count"] == 0
    assert result.metadata["held_set_span_seconds"] == 2 * 86400


def test_f9_fresh_backup_is_ok(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    root.mkdir()
    for day in (13, 14, 15):
        _write_backup_artifact(
            root,
            f"backup-202609{day:02d}",
            created_at=datetime(2026, 9, day, 12, 0, tzinfo=UTC),
        )

    result = _check_f9_backup_staleness(
        root,
        sla_seconds=_SLA_48H,
        sample_limit=5,
        now=datetime(2026, 9, 15, 18, 0, tzinfo=UTC),
    )

    assert result.count == 0
    assert result.to_dict()["severity"] == "OK"
    assert result.metadata["stale"] is False
    assert result.metadata["newest_success_age_seconds"] == 6 * 3600
    assert result.sample_ids == []


def test_f9_empty_backup_root_warns_instead_of_silently_passing(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    root.mkdir()

    result = _check_f9_backup_staleness(
        root, sla_seconds=_SLA_48H, sample_limit=5, now=datetime(2026, 9, 15, tzinfo=UTC)
    )

    assert result.count == 1
    assert result.metadata["artifact_count"] == 0
    assert result.metadata["newest_success_at_utc"] is None
    assert result.metadata["newest_success_age_seconds"] is None
    assert result.metadata["held_set_span_seconds"] is None
    assert result.sample_ids == [f"no_successful_backup_artifact:{root}"]


def test_f9_missing_backup_root_directory_warns(tmp_path: Path) -> None:
    # 루트 경로가 **설정됐는데 없는** 것은 "안 봤다"가 아니라 "성공이 하나도 없다"다.
    missing = tmp_path / "gone"
    result = _check_f9_backup_staleness(
        missing,
        sla_seconds=_SLA_48H,
        sample_limit=5,
        now=datetime(2026, 9, 15, tzinfo=UTC),
    )

    assert result.count == 1
    assert result.metadata["observed"] is True
    assert result.metadata["artifact_count"] == 0
    # 판정은 위와 같되 **이유는 구분된다.**
    assert result.metadata["root_missing"] is True
    assert result.sample_ids == [f"backup_root_missing:{missing}"]


def test_f9_missing_root_and_empty_root_are_the_same_verdict_but_different_reasons(
    tmp_path: Path,
) -> None:
    """같은 "성공 0건"인데 조치가 다른 둘을 리포트에서 갈라 읽을 수 있어야 한다.

    없는 루트는 경로·볼륨 설정 문제이고, 빈 루트는 백업 자체가 안 돈 것이다. 종전에는
    둘 다 `no_successful_backup_artifact:<root>` 하나로 나와서 리포트만 보고는 어느
    쪽을 고쳐야 하는지 알 수 없었다 — Map prod가 지금 정확히 그 상태다(api·dagster
    어느 컨테이너에도 `backup_root`가 마운트돼 있지 않다, 2026-09-16 실측).

    **판정을 바꾸는 검사가 아니다.** 둘 다 여전히 WARN이고 count 1이다. 바뀌는 것은
    "왜"뿐이고, 그 "왜"가 없으면 고칠 수 없다.
    """
    missing = tmp_path / "gone"
    empty = tmp_path / "empty"
    empty.mkdir()
    at = datetime(2026, 9, 15, tzinfo=UTC)

    missing_result = _check_f9_backup_staleness(
        missing, sla_seconds=_SLA_48H, sample_limit=5, now=at
    )
    empty_result = _check_f9_backup_staleness(
        empty, sla_seconds=_SLA_48H, sample_limit=5, now=at
    )

    # 판정은 같다 — 이것이 바뀌면 경보 하나를 잃은 것이다.
    assert missing_result.severity == empty_result.severity == "WARN"
    assert missing_result.count == empty_result.count == 1
    assert missing_result.metadata["stale"] is True
    assert empty_result.metadata["stale"] is True

    # 이유는 다르다 — 이것이 같아지면 고칠 자리를 잃은 것이다.
    assert missing_result.metadata["root_missing"] is True
    assert empty_result.metadata["root_missing"] is False
    assert missing_result.sample_ids != empty_result.sample_ids
    assert missing_result.sample_ids == [f"backup_root_missing:{missing}"]
    assert empty_result.sample_ids == [f"no_successful_backup_artifact:{empty}"]


def test_f9_in_flight_artifact_without_checksums_is_not_a_success(tmp_path: Path) -> None:
    root = _incident_root(tmp_path)
    # manifest까지만 쓰이고 SHA256SUMS를 아직 못 쓴 상태 — 사고 당시 23분간 존재했던
    # geo의 ``.part``와 같은 단계다. manifest만 보는 판정은 이것을 "방금 성공"으로
    # 읽고 OK를 낸다.
    _write_backup_artifact(
        root,
        "kor_travel_geo_backup_inflight",
        created_at=datetime(2026, 9, 15, 11, 40, tzinfo=UTC),
        with_checksums=False,
    )

    result = _check_f9_backup_staleness(
        root,
        sla_seconds=_SLA_48H,
        sample_limit=5,
        now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )

    assert result.count == 1
    assert result.metadata["artifact_count"] == 4
    assert result.metadata["success_count"] == 3
    assert result.metadata["incomplete_count"] == 1
    assert result.metadata["newest_success_backup_id"] == "kor_travel_geo_backup_20260910"
    assert result.metadata["newest_success_age_seconds"] == 5 * 86400


def test_f9_unreadable_or_undated_artifacts_are_not_successes(tmp_path: Path) -> None:
    root = _incident_root(tmp_path)
    # 셋 다 사고 이후에 만들어졌지만 "언제 찍혔는지"를 세울 수 없다.
    _write_backup_artifact(root, "manifest-missing", created_at=None, manifest="missing")
    _write_backup_artifact(root, "manifest-invalid", created_at=None, manifest="invalid")
    _write_backup_artifact(root, "manifest-undated", created_at=None, manifest="ok")

    result = _check_f9_backup_staleness(
        root,
        sla_seconds=_SLA_48H,
        sample_limit=5,
        now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )

    assert result.count == 1
    assert result.metadata["artifact_count"] == 6
    assert result.metadata["success_count"] == 3
    assert result.metadata["incomplete_count"] == 3
    assert result.metadata["newest_success_backup_id"] == "kor_travel_geo_backup_20260910"


@pytest.mark.parametrize(
    ("age", "expected_count"),
    [
        (timedelta(seconds=_SLA_48H), 0),
        (timedelta(seconds=_SLA_48H + 1), 1),
    ],
)
def test_f9_sla_boundary_is_strictly_greater_than(
    tmp_path: Path, age: timedelta, expected_count: int
) -> None:
    root = tmp_path / "backups"
    root.mkdir()
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    _write_backup_artifact(root, "backup-edge", created_at=now - age)

    result = _check_f9_backup_staleness(
        root, sla_seconds=_SLA_48H, sample_limit=5, now=now
    )

    assert result.count == expected_count


def test_f9_unset_backup_root_is_recorded_as_unobserved() -> None:
    result = _check_f9_backup_staleness(None, sla_seconds=_SLA_48H, sample_limit=5)

    assert result.count == 0
    # count 0이지만 "정상"이 아니다 — 안 봤다는 사실이 리포트에 남아야, 나중에 누가
    # "F9가 0이었으니 백업은 괜찮았다"고 읽는 것을 막는다.
    assert result.metadata == {"observed": False, "reason": "backup_root_not_provided"}
    assert "미관측" in result.description


def test_f9_sample_limit_zero_still_counts_the_violation(tmp_path: Path) -> None:
    root = _incident_root(tmp_path)

    result = _check_f9_backup_staleness(
        root,
        sla_seconds=_SLA_48H,
        sample_limit=0,
        now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )

    assert result.count == 1
    assert result.sample_ids == []


def test_f9_violation_is_warn_and_does_not_block_the_batch_gate(tmp_path: Path) -> None:
    root = _incident_root(tmp_path)
    stale = _check_f9_backup_staleness(
        root,
        sla_seconds=_SLA_48H,
        sample_limit=5,
        now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )

    report = build_report("batch-f9", [_case("F1", "ERROR", 0), stale])

    # ``infra.batch_dag``는 severity_max=ERROR일 때만 mv_refresh를 막는다. F9가 WARN인
    # 것은 관측 전용이라는 뜻이고, 백업이 멈췄다고 적재까지 세우지는 않는다.
    assert report.severity_max == "WARN"
    assert report.summary["by_code"]["F9"] == 1
    assert report.summary["case_metadata"]["F9"]["stale"] is True


def test_f9_default_sla_has_one_source_shared_with_settings() -> None:
    # 코드 기본값과 env 기본값이 갈라지면 더 느슨한 쪽이 조용히 이긴다.
    assert BACKUP_LAST_SUCCESS_WARN_SECONDS == BACKUP_LAST_SUCCESS_WARN_HOURS_DEFAULT * 3600
    assert (
        KorTravelMapSettings().backup_last_success_warn_hours
        == BACKUP_LAST_SUCCESS_WARN_HOURS_DEFAULT
    )
    # 예약 주기 24h의 2배. 이 값이 24h 이하로 내려가면 정상적인 날에도 매일 운다.
    assert BACKUP_LAST_SUCCESS_WARN_SECONDS > 24 * 3600


def _artifact(
    *,
    manifest_status: str = "ok",
    created_at_utc: datetime | None = datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    checksum_count: int = 14,
) -> BackupArtifact:
    return BackupArtifact(
        backup_id="probe",
        path=Path("probe"),
        manifest_status=manifest_status,
        created_at_utc=created_at_utc,
        mode="docker-compose-cold-backup",
        components={},
        databases={},
        object_storage={},
        byte_size=1,
        checksum_count=checksum_count,
    )


@pytest.mark.parametrize(
    ("artifact", "expected"),
    [
        (_artifact(), True),
        # SHA256SUMS를 아직 못 쓴 상태 — 스크립트가 **마지막에** 쓰는 파일이다.
        (_artifact(checksum_count=0), False),
        # 시각을 못 읽으면 최근성의 근거가 될 수 없다.
        (_artifact(created_at_utc=None), False),
        # manifest 축은 지금은 위 시각 축에 **가려져 있다**(manifest가 없거나 깨지면
        # ``created_at_utc``도 None이 된다). 그래도 남겨 두는 이유는 그 가림이
        # ``infra.backup``의 현재 구현에만 의존하기 때문이다 — 언젠가 mtime 등으로
        # created_at을 보충하면 manifest 축이 유일한 방어가 된다. 그 축을 직접 세운다.
        (_artifact(manifest_status="missing"), False),
        (_artifact(manifest_status="invalid"), False),
    ],
)
def test_f9_success_predicate_rejects_every_incomplete_axis(
    artifact: BackupArtifact, expected: bool
) -> None:
    assert _is_successful_backup_artifact(artifact) is expected


def test_f9_a_future_dated_artifact_does_not_silence_the_check(tmp_path: Path) -> None:
    """**미래 날짜는 안심이 아니라 경보다.**

    `newest_age > sla`만 보면 시계가 한 번 앞으로 튄 동안 만들어진 artifact가
    **영원히 최신**이 되어 이 검사가 다시는 울리지 않는다 — 조용해지지 않는 것이
    이 검사의 존재 이유이므로 그 형태가 가장 나쁘다(2026-09-16 적대 리뷰가 사고
    fixture에 2027년 artifact 하나를 더해 실증했다: age -2580h → 조용).
    """

    root = _incident_root(tmp_path)
    _write_backup_artifact(
        root,
        "kor_travel_geo_backup_20270101",
        created_at=datetime(2027, 1, 1, tzinfo=UTC),
    )

    result = _check_f9_backup_staleness(
        root,
        sla_seconds=_SLA_48H,
        sample_limit=5,
        now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )

    assert result.count == 1, (
        "미래 날짜 artifact가 검사를 조용하게 만들었다 — 시계가 한 번 튀면 영영 울리지 "
        "않는다"
    )
    assert result.metadata["stale"] is True


def test_f9_an_unreadable_backup_root_warns_instead_of_killing_the_report(
    tmp_path: Path,
) -> None:
    """**artifact 하나가 F1~F8까지 죽이면 안 된다.**

    `list_backup_artifacts`는 `BackupArtifactError`만 잡고 `OSError`·
    `UnicodeDecodeError`는 흘려보낸다. F9의 호출부가 F1~F8과 같은 `cases` 목록에
    있으므로, 막지 않으면 **그 예외 하나가 일관성 리포트를 통째로 못 만들게 한다**
    (2026-09-16 적대 리뷰가 `SHA256SUMS`에 비-UTF-8 바이트를 넣어 실증했다).

    이 경로는 본질적으로 경합하기도 한다 — retention GC가 스캔 중에 artifact를
    지우면 `FileNotFoundError`가 난다. 그것은 고장이 아니라 정상 동작이고, 그때
    리포트 전체를 잃는 것이 훨씬 나쁘다.

    그리고 읽지 못한 것을 **OK로 두지 않는다** — 읽을 수 없으면 최신 성공을 증명할
    수 없고, 증명할 수 없는 것은 이 검사에서 경보다.
    """

    root = _incident_root(tmp_path)
    broken = root / "kor_travel_geo_backup_broken" / "meta"
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text('{"created_at_utc": "2026-09-16T00:00:00Z"}')
    (broken / "SHA256SUMS").write_bytes(b"0" * 64 + b"  caf\xe9.dump\n")

    result = _check_f9_backup_staleness(
        root,
        sla_seconds=_SLA_48H,
        sample_limit=5,
        now=datetime(2026, 9, 16, 12, 0, tzinfo=UTC),
    )

    assert result.code == "F9"
    assert result.severity == "WARN"
    assert result.count == 1
    assert result.metadata["observed"] is False
    assert "scan_error" in result.metadata


def test_f9_sla_setting_and_module_default_do_not_drift() -> None:
    """설정과 모듈 기본값이 **같은 수**에서 나온다.

    종전에는 `settings.backup_last_success_warn_hours`를 읽는 곳이 하나도 없었다 —
    `.env.example`과 필드 설명이 env를 광고하는데 바꿔도 아무 일이 없었다
    (2026-09-16 적대 리뷰). 지금은 CLI가 그것을 읽으므로 두 값이 갈라지면 안 된다.
    """

    from kortravelmap.settings import (
        BACKUP_LAST_SUCCESS_WARN_HOURS_DEFAULT,
        KorTravelMapSettings,
    )

    assert (
        KorTravelMapSettings().backup_last_success_warn_hours
        == BACKUP_LAST_SUCCESS_WARN_HOURS_DEFAULT
    )
    assert BACKUP_LAST_SUCCESS_WARN_SECONDS == BACKUP_LAST_SUCCESS_WARN_HOURS_DEFAULT * 3600
