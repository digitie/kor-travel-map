"""Consistency dry-run report rendering helpers for ``kor-travel-map`` CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from kortravelmap.infra.consistency import ConsistencyReport, FileObjectRef

__all__ = [
    "ConsistencyReportOptions",
    "load_file_object_refs",
    "render_consistency_report_json",
    "render_consistency_report_markdown",
]


@dataclass(frozen=True)
class ConsistencyReportOptions:
    """CLI report metadata and threshold options."""

    generated_at: datetime
    persisted: bool
    sample_limit: int
    dedup_pending_threshold: int
    provider_last_success_sla_seconds: int
    dedup_score_regression_warn_points: float
    known_file_objects_source: str | None = None
    known_file_objects_count: int | None = None

    @property
    def mode(self) -> str:
        return "persisted" if self.persisted else "dry-run"

    def thresholds_json(self) -> dict[str, int | float]:
        return {
            "dedup_pending_threshold": self.dedup_pending_threshold,
            "provider_last_success_sla_seconds": self.provider_last_success_sla_seconds,
            "dedup_score_regression_warn_points": self.dedup_score_regression_warn_points,
            "sample_limit": self.sample_limit,
        }


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"file object ref requires non-empty string field: {key}")
    return value


def _ref_from_mapping(data: object) -> FileObjectRef:
    if not isinstance(data, dict):
        raise ValueError("file object ref must be a JSON object")
    return FileObjectRef(
        storage_backend=_required_str(data, "storage_backend"),
        bucket=_required_str(data, "bucket"),
        object_key=_required_str(data, "object_key"),
    )


def load_file_object_refs(path: Path) -> list[FileObjectRef]:
    """Load F8 object-store snapshot refs from JSON array or JSONL.

    각 항목은 ``storage_backend``/``bucket``/``object_key`` 문자열을 가져야 한다.
    RustFS/S3 listing 도구가 만든 JSONL을 그대로 주입할 수 있게 줄 단위 객체도
    허용한다.
    """
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if raw.startswith("["):
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("file object ref JSON array expected")
        return [_ref_from_mapping(item) for item in parsed]
    refs: list[FileObjectRef] = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            refs.append(_ref_from_mapping(json.loads(stripped)))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_no}: {exc}") from exc
    return refs


def _md_cell(value: object) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")


def _format_samples(samples: list[str]) -> str:
    if not samples:
        return "-"
    return "\n".join(f"- `{sample}`" for sample in samples)


def render_consistency_report_markdown(
    report: ConsistencyReport,
    *,
    options: ConsistencyReportOptions,
) -> str:
    """Render a human-readable ADR-033 Phase 2 report."""
    lines = [
        "# T-201b Phase 2 consistency dry-run report",
        "",
        "## 실행 정보",
        "",
        f"- 생성 시각: `{options.generated_at.isoformat()}`",
        f"- 모드: `{options.mode}`",
        f"- batch_id: `{report.batch_id}`",
        f"- severity_max: `{report.severity_max}`",
        f"- total_violations: `{report.summary.get('total_violations', 0)}`",
        f"- cases_evaluated: `{report.summary.get('cases_evaluated', len(report.cases))}`",
        f"- sample_limit: `{options.sample_limit}`",
        f"- F4 dedup pending threshold: `{options.dedup_pending_threshold}`",
        f"- F5 provider SLA seconds: `{options.provider_last_success_sla_seconds}`",
        f"- F7 score regression warn points: `{options.dedup_score_regression_warn_points:g}`",
        (
            f"- F8 object snapshot: `{options.known_file_objects_source}` "
            f"({options.known_file_objects_count} objects)"
            if options.known_file_objects_source is not None
            else "- F8 object snapshot: `not provided`"
        ),
        "",
        "## 케이스 요약",
        "",
        "| code | effective severity | configured severity | count | description |",
        "|------|--------------------|---------------------|-------|-------------|",
    ]
    for case in report.cases:
        effective = case.severity if case.count else "OK"
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(case.code),
                    _md_cell(effective),
                    _md_cell(case.severity),
                    _md_cell(case.count),
                    _md_cell(case.description),
                ]
            )
            + " |"
        )
    lines.extend(["", "## 샘플", ""])
    for case in report.cases:
        lines.extend(
            [
                f"### {case.code}",
                "",
                _format_samples(case.sample_ids),
                "",
            ]
        )
    lines.extend(
        [
            "## 판정",
            "",
            (
                "- `ERROR` 위반이 있어 실제 gate에서는 `mv_refresh`가 차단된다."
                if report.severity_max == "ERROR"
                else "- `ERROR` 위반은 없다. 실제 gate에서는 OK/WARN이면 다음 단계로 진행 가능하다."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def render_consistency_report_json(
    report: ConsistencyReport,
    *,
    options: ConsistencyReportOptions,
) -> str:
    """Render a machine-readable report payload."""
    payload: dict[str, Any] = {
        "generated_at": options.generated_at.isoformat(),
        "mode": options.mode,
        "persisted": options.persisted,
        "thresholds": options.thresholds_json(),
        "known_file_objects": {
            "source": options.known_file_objects_source,
            "count": options.known_file_objects_count,
        },
        "report": {
            "batch_id": report.batch_id,
            "severity_max": report.severity_max,
            "summary": report.summary,
            "cases": report.cases_json(),
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
