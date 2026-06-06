"""``krtour-map consistency-report`` formatter/parser 단위 테스트."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from krtour.map.cli.consistency_report import (
    ConsistencyReportOptions,
    load_file_object_refs,
    render_consistency_report_json,
    render_consistency_report_markdown,
)
from krtour.map.dto._time import KST
from krtour.map.infra.consistency import CaseResult, ConsistencyReport


def _report() -> ConsistencyReport:
    return ConsistencyReport(
        batch_id="batch-dryrun",
        severity_max="WARN",
        cases=[
            CaseResult(
                code="F1",
                severity="ERROR",
                description="orphan source_record",
                count=0,
                sample_ids=[],
            ),
            CaseResult(
                code="F5",
                severity="WARN",
                description="provider SLA",
                count=2,
                sample_ids=["provider:a:default", "provider:b:default"],
            ),
        ],
        summary={
            "total_violations": 2,
            "cases_evaluated": 2,
            "by_severity": {"ERROR": 0, "WARN": 2},
            "by_code": {"F1": 0, "F5": 2},
        },
    )


def _options(*, persisted: bool = False) -> ConsistencyReportOptions:
    return ConsistencyReportOptions(
        generated_at=datetime(2026, 6, 6, 15, 30, tzinfo=KST),
        persisted=persisted,
        sample_limit=20,
        dedup_pending_threshold=1000,
        provider_last_success_sla_seconds=86400,
        dedup_score_regression_warn_points=10.0,
        known_file_objects_source="objects.jsonl",
        known_file_objects_count=3,
    )


def test_render_consistency_report_markdown() -> None:
    markdown = render_consistency_report_markdown(_report(), options=_options())

    assert "# T-201b Phase 2 consistency dry-run report" in markdown
    assert "- 모드: `dry-run`" in markdown
    assert "| F5 | WARN | WARN | 2 | provider SLA |" in markdown
    assert "- `provider:a:default`" in markdown
    assert "`objects.jsonl` (3 objects)" in markdown
    assert "실제 gate에서는 OK/WARN이면 다음 단계로 진행 가능" in markdown


def test_render_consistency_report_json() -> None:
    rendered = render_consistency_report_json(_report(), options=_options(persisted=True))
    payload = json.loads(rendered)

    assert payload["mode"] == "persisted"
    assert payload["thresholds"]["dedup_pending_threshold"] == 1000
    assert payload["known_file_objects"]["count"] == 3
    assert payload["report"]["severity_max"] == "WARN"
    assert payload["report"]["cases"][1]["sample_ids"] == [
        "provider:a:default",
        "provider:b:default",
    ]


def test_load_file_object_refs_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "objects.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "storage_backend": "rustfs",
                        "bucket": "krtour-map",
                        "object_key": "features/a.jpg",
                    }
                ),
                json.dumps(
                    {
                        "storage_backend": "rustfs",
                        "bucket": "krtour-map",
                        "object_key": "features/b.jpg",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    refs = load_file_object_refs(path)

    assert [ref.sample_id() for ref in refs] == [
        "rustfs:krtour-map:features/a.jpg",
        "rustfs:krtour-map:features/b.jpg",
    ]


def test_load_file_object_refs_json_array(tmp_path: Path) -> None:
    path = tmp_path / "objects.json"
    path.write_text(
        json.dumps(
            [
                {
                    "storage_backend": "rustfs",
                    "bucket": "krtour-map",
                    "object_key": "features/a.jpg",
                }
            ]
        ),
        encoding="utf-8",
    )

    refs = load_file_object_refs(path)

    assert len(refs) == 1
    assert refs[0].object_key == "features/a.jpg"


def test_load_file_object_refs_rejects_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"storage_backend":"rustfs","bucket":"krtour-map"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="object_key"):
        load_file_object_refs(path)
