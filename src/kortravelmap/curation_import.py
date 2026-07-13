"""큐레이션 전용 CSV의 순수 파싱·형식 검증 계약."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, replace
from typing import Final, Literal, cast

CURATION_CSV_HEADERS: Final[tuple[str, ...]] = (
    "collection_key",
    "theme_slug",
    "theme_name",
    "theme_group",
    "title",
    "edition_key",
    "subcourse",
    "provider",
    "dataset_key",
    "source_name",
    "source_url",
    "source_item_key",
    "official_ordinal",
    "place_name",
    "address_hint",
    "feature_id",
    "sort_order",
    "item_title",
    "item_summary",
    "metadata_json",
)
CURATION_CSV_MAX_BYTES: Final = 2 * 1024 * 1024
CURATION_CSV_MAX_ROWS: Final = 2_000
CURATION_CSV_MAX_CELL_LENGTH: Final = 10_000

_REQUIRED_VALUES: Final[tuple[str, ...]] = (
    "collection_key",
    "theme_slug",
    "theme_name",
    "theme_group",
    "title",
    "provider",
    "dataset_key",
    "source_name",
    "source_item_key",
)
_INTEGER_COLUMNS: Final[tuple[str, ...]] = ("official_ordinal", "sort_order")


@dataclass(frozen=True)
class CurationImportIssue:
    """큐레이션 CSV의 파일 또는 행 검증 오류."""

    code: str
    message: str
    row_number: int | None = None
    column: str | None = None


@dataclass(frozen=True)
class CurationImportRow:
    """정규화한 큐레이션 CSV 한 행과 해당 행의 검증 상태."""

    row_number: int
    status: Literal["valid", "invalid"]
    collection_key: str
    theme_slug: str
    theme_name: str
    theme_group: str
    title: str
    edition_key: str
    subcourse: str
    provider: str
    dataset_key: str
    source_name: str
    source_url: str
    source_item_key: str
    official_ordinal: int | None
    place_name: str
    address_hint: str
    feature_id: str
    sort_order: int | None
    item_title: str
    item_summary: str
    metadata_json: dict[str, object]
    issues: tuple[CurationImportIssue, ...]

    @property
    def errors(self) -> tuple[CurationImportIssue, ...]:
        """HTTP preview에서 사용할 행 오류 alias."""
        return self.issues


@dataclass(frozen=True)
class CurationImportPreview:
    """큐레이션 CSV 전체 preview와 파일·행 검증 결과."""

    headers: tuple[str, ...]
    rows: tuple[CurationImportRow, ...]
    rows_total: int
    valid_rows: int
    invalid_rows: int
    issues: tuple[CurationImportIssue, ...]

    @property
    def has_errors(self) -> bool:
        """파일 또는 행 오류가 하나라도 있는지 반환한다."""
        return bool(self.issues or self.invalid_rows)

    @property
    def errors(self) -> tuple[CurationImportIssue, ...]:
        """HTTP preview에서 사용할 파일 오류 alias."""
        return self.issues


def parse_curation_csv(content: bytes) -> CurationImportPreview:
    """UTF-8 CSV를 정규화하고 DB 접근 없이 계약 위반을 모두 반환한다."""
    if len(content) > CURATION_CSV_MAX_BYTES:
        return _empty_preview(
            CurationImportIssue(
                code="file_too_large",
                message=f"CSV 파일은 {CURATION_CSV_MAX_BYTES} bytes 이하여야 합니다.",
            )
        )

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _empty_preview(
            CurationImportIssue(
                code="invalid_encoding",
                message="CSV 파일은 UTF-8 또는 UTF-8 BOM 형식이어야 합니다.",
            )
        )

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        raw_headers = next(reader)
    except StopIteration:
        return _empty_preview(
            CurationImportIssue(code="missing_header", message="CSV header가 없습니다.")
        )
    except csv.Error as exc:
        return _empty_preview(
            CurationImportIssue(code="invalid_csv", message=f"CSV header를 읽을 수 없습니다: {exc}")
        )

    headers = tuple(header.strip() for header in raw_headers)
    header_issues = _validate_headers(headers)
    if header_issues:
        return CurationImportPreview(
            headers=headers,
            rows=(),
            rows_total=0,
            valid_rows=0,
            invalid_rows=0,
            issues=header_issues,
        )

    rows: list[CurationImportRow] = []
    file_issues: list[CurationImportIssue] = []
    rows_total = 0
    try:
        for row_number, cells in enumerate(reader, start=2):
            if not cells or not any(cell.strip() for cell in cells):
                continue
            rows_total += 1
            if rows_total > CURATION_CSV_MAX_ROWS:
                continue
            rows.append(_parse_row(row_number, headers, cells))
    except csv.Error as exc:
        file_issues.append(
            CurationImportIssue(code="invalid_csv", message=f"CSV 본문을 읽을 수 없습니다: {exc}")
        )

    if rows_total > CURATION_CSV_MAX_ROWS:
        file_issues.append(
            CurationImportIssue(
                code="too_many_rows",
                message=f"CSV 데이터 행은 {CURATION_CSV_MAX_ROWS}개 이하여야 합니다.",
            )
        )

    rows = _validate_collection_consistency(rows)
    valid_rows = sum(row.status == "valid" for row in rows)
    return CurationImportPreview(
        headers=headers,
        rows=tuple(rows),
        rows_total=rows_total,
        valid_rows=valid_rows,
        invalid_rows=len(rows) - valid_rows,
        issues=tuple(file_issues),
    )


def _validate_headers(headers: tuple[str, ...]) -> tuple[CurationImportIssue, ...]:
    issues: list[CurationImportIssue] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for header in headers:
        if header in seen:
            duplicates.add(header)
        seen.add(header)
    for header in sorted(duplicates):
        issues.append(
            CurationImportIssue(
                code="duplicate_header",
                message=f"중복 header입니다: {header}",
                column=header,
            )
        )

    for header in CURATION_CSV_HEADERS:
        if header not in seen:
            issues.append(
                CurationImportIssue(
                    code="missing_header",
                    message=f"필수 header가 없습니다: {header}",
                    column=header,
                )
            )
    for header in headers:
        if header not in CURATION_CSV_HEADERS:
            issues.append(
                CurationImportIssue(
                    code="unexpected_header",
                    message=f"지원하지 않는 header입니다: {header}",
                    column=header or None,
                )
            )
    return tuple(issues)


def _parse_row(
    row_number: int,
    headers: tuple[str, ...],
    cells: list[str],
) -> CurationImportRow:
    issues: list[CurationImportIssue] = []
    if len(cells) != len(headers):
        issues.append(
            CurationImportIssue(
                code="column_count_mismatch",
                message=f"열 수가 header와 다릅니다: expected={len(headers)}, actual={len(cells)}",
                row_number=row_number,
            )
        )

    values = {
        header: (cells[index].strip() if index < len(cells) else "")
        for index, header in enumerate(headers)
    }
    for index, cell in enumerate(cells):
        if len(cell) > CURATION_CSV_MAX_CELL_LENGTH:
            column = headers[index] if index < len(headers) else None
            issues.append(
                CurationImportIssue(
                    code="cell_too_long",
                    message=f"셀은 {CURATION_CSV_MAX_CELL_LENGTH}자 이하여야 합니다.",
                    row_number=row_number,
                    column=column,
                )
            )

    for column in _REQUIRED_VALUES:
        if not values[column]:
            issues.append(
                CurationImportIssue(
                    code="required_value_missing",
                    message=f"필수값이 비어 있습니다: {column}",
                    row_number=row_number,
                    column=column,
                )
            )
    if not values["feature_id"] and not values["place_name"]:
        issues.append(
            CurationImportIssue(
                code="feature_reference_missing",
                message="feature_id 또는 place_name 중 하나가 필요합니다.",
                row_number=row_number,
            )
        )

    integers = {
        column: _parse_integer(values[column], row_number, column, issues)
        for column in _INTEGER_COLUMNS
    }
    metadata = _parse_metadata(values["metadata_json"], row_number, issues)
    return CurationImportRow(
        row_number=row_number,
        status="invalid" if issues else "valid",
        collection_key=values["collection_key"],
        theme_slug=values["theme_slug"],
        theme_name=values["theme_name"],
        theme_group=values["theme_group"],
        title=values["title"],
        edition_key=values["edition_key"],
        subcourse=values["subcourse"],
        provider=values["provider"],
        dataset_key=values["dataset_key"],
        source_name=values["source_name"],
        source_url=values["source_url"],
        source_item_key=values["source_item_key"],
        official_ordinal=integers["official_ordinal"],
        place_name=values["place_name"],
        address_hint=values["address_hint"],
        feature_id=values["feature_id"],
        sort_order=integers["sort_order"],
        item_title=values["item_title"],
        item_summary=values["item_summary"],
        metadata_json=metadata,
        issues=tuple(issues),
    )


def _parse_integer(
    value: str,
    row_number: int,
    column: str,
    issues: list[CurationImportIssue],
) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        issues.append(
            CurationImportIssue(
                code="invalid_integer",
                message=f"정수 형식이 아닙니다: {column}",
                row_number=row_number,
                column=column,
            )
        )
        return None
    if parsed < 0:
        issues.append(
            CurationImportIssue(
                code="negative_integer",
                message=f"음수일 수 없는 열입니다: {column}",
                row_number=row_number,
                column=column,
            )
        )
        return None
    return parsed


def _validate_collection_consistency(
    rows: list[CurationImportRow],
) -> list[CurationImportRow]:
    """같은 collection_key가 서로 다른 묶음 정의로 덮어쓰이지 않게 한다."""

    signatures: dict[str, tuple[str, ...]] = {}
    item_identities: set[tuple[str, str, str]] = set()
    resolution_modes: dict[tuple[str, str], set[bool]] = {}
    for row in rows:
        resolution_modes.setdefault(
            (row.collection_key, row.source_item_key), set()
        ).add(bool(row.feature_id))
    validated: list[CurationImportRow] = []
    for row in rows:
        signature = (
            row.theme_slug,
            row.theme_name,
            row.theme_group,
            row.title,
            row.edition_key,
            row.provider,
            row.dataset_key,
            row.source_name,
            row.source_url,
        )
        previous = signatures.setdefault(row.collection_key, signature)
        issues = list(row.issues)
        if previous != signature:
            issues.append(
                CurationImportIssue(
                    code="collection_definition_conflict",
                    message=(
                        "같은 collection_key의 theme/title/edition/source 정의가 "
                        "앞 행과 다릅니다."
                    ),
                    row_number=row.row_number,
                    column="collection_key",
                )
            )
        feature_reference = row.feature_id or "__unresolved__"
        item_identity = (
            row.collection_key,
            row.source_item_key,
            feature_reference,
        )
        if item_identity in item_identities:
            issues.append(
                CurationImportIssue(
                    code="duplicate_item",
                    message="같은 collection/item/Feature 행이 파일 안에 중복되었습니다.",
                    row_number=row.row_number,
                    column="source_item_key",
                )
            )
        item_identities.add(item_identity)
        if len(resolution_modes[(row.collection_key, row.source_item_key)]) > 1:
            issues.append(
                CurationImportIssue(
                    code="mixed_resolved_unresolved_item",
                    message=(
                        "같은 collection/item에 Feature 연결 행과 미연결 행을 "
                        "함께 둘 수 없습니다."
                    ),
                    row_number=row.row_number,
                    column="feature_id",
                )
            )
        validated.append(
            replace(
                row,
                status="invalid" if issues else "valid",
                issues=tuple(issues),
            )
        )
    return validated


def _parse_metadata(
    value: str,
    row_number: int,
    issues: list[CurationImportIssue],
) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        issues.append(
            CurationImportIssue(
                code="invalid_json",
                message="metadata_json이 올바른 JSON이 아닙니다.",
                row_number=row_number,
                column="metadata_json",
            )
        )
        return {}
    if not isinstance(parsed, dict):
        issues.append(
            CurationImportIssue(
                code="json_object_required",
                message="metadata_json은 JSON object여야 합니다.",
                row_number=row_number,
                column="metadata_json",
            )
        )
        return {}
    return cast(dict[str, object], parsed)


def _empty_preview(issue: CurationImportIssue) -> CurationImportPreview:
    return CurationImportPreview(
        headers=(),
        rows=(),
        rows_total=0,
        valid_rows=0,
        invalid_rows=0,
        issues=(issue,),
    )
