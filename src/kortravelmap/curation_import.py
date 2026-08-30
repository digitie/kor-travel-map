"""큐레이션 전용 CSV의 순수 파싱·형식 검증 계약."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
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
    "source_component_key",
    "official_ordinal",
    "place_name",
    "address_hint",
    "feature_id",
    "sort_order",
    "item_title",
    "item_summary",
    "metadata_json",
)
CURATION_CSV_OPTIONAL_HEADERS: Final[tuple[str, ...]] = (
    "manual_feature_kind",
    "manual_feature_lon",
    "manual_feature_lat",
)
"""T-VN-M03 — 행이 manual Feature를 **만들도록** 지시하는 선택 header.

파일 단위 opt-in이다. 없으면 기존 CSV가 그대로 유효하고, 있으면 세 개가 함께 있어야
한다. 좌표를 `metadata_json`에 숨기지 않고 **typed 열**로 받는 이유는 설계
§6.1이 "`metadata_json`에 untyped input을 숨기지 않는다"를 요구하기 때문이고,
주소에서 좌표를 추론하지 않는 이유는 §7이 "CSV 제목·주소 기반 Feature 추정 생성"을
비목표로 명시하기 때문이다 — 그래서 좌표는 **명시적으로 실려야** 한다.
"""

_MANUAL_FEATURE_KINDS: Final[frozenset[str]] = frozenset({"place", "event"})

CURATION_CSV_MAX_BYTES: Final = 2 * 1024 * 1024
CURATION_CSV_MAX_ROWS: Final = 2_000
CURATION_CSV_MAX_CELL_LENGTH: Final = 10_000
CURATION_INTEGER_MAX: Final = 2_147_483_647

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
    "source_component_key",
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
    source_component_key: str
    official_ordinal: int | None
    place_name: str
    address_hint: str
    feature_id: str
    sort_order: int | None
    item_title: str
    item_summary: str
    metadata_json: dict[str, object]
    manual_feature_kind: str
    """비면 이 행은 manual Feature를 만들지 않는다. 아니면 ``place``/``event``."""

    manual_feature_lon: Decimal | None
    manual_feature_lat: Decimal | None
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
    known = set(CURATION_CSV_HEADERS) | set(CURATION_CSV_OPTIONAL_HEADERS)
    optional_present = sorted(h for h in CURATION_CSV_OPTIONAL_HEADERS if h in seen)
    if optional_present and len(optional_present) != len(CURATION_CSV_OPTIONAL_HEADERS):
        missing = sorted(set(CURATION_CSV_OPTIONAL_HEADERS) - set(optional_present))
        issues.append(
            CurationImportIssue(
                code="partial_manual_feature_headers",
                message=(
                    "manual Feature header는 전부 함께 있어야 합니다. "
                    f"없는 header: {', '.join(missing)}"
                ),
                column=missing[0],
            )
        )
    for header in headers:
        if header not in known:
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

    values = dict.fromkeys(CURATION_CSV_OPTIONAL_HEADERS, "")
    values.update(
        {
            header: (cells[index].strip() if index < len(cells) else "")
            for index, header in enumerate(headers)
        }
    )
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

    manual_kind = values["manual_feature_kind"]
    manual_lon = manual_lat = None
    if manual_kind:
        if manual_kind not in _MANUAL_FEATURE_KINDS:
            issues.append(
                CurationImportIssue(
                    code="invalid_manual_feature_kind",
                    message="manual_feature_kind는 place 또는 event여야 합니다.",
                    row_number=row_number,
                    column="manual_feature_kind",
                )
            )
        if values["feature_id"]:
            # 기존 Feature를 가리키면서 동시에 새로 만들 수는 없다. 둘 다 주면
            # 어느 쪽이 이기는지 파일만 보고 알 수 없으므로 거절한다.
            issues.append(
                CurationImportIssue(
                    code="manual_feature_conflicts_with_feature_id",
                    message="feature_id와 manual_feature_kind는 함께 쓸 수 없습니다.",
                    row_number=row_number,
                    column="manual_feature_kind",
                )
            )
        manual_lon = _parse_coordinate(
            values["manual_feature_lon"], row_number, "manual_feature_lon", 180, issues
        )
        manual_lat = _parse_coordinate(
            values["manual_feature_lat"], row_number, "manual_feature_lat", 90, issues
        )
    else:
        for column in ("manual_feature_lon", "manual_feature_lat"):
            if values[column]:
                issues.append(
                    CurationImportIssue(
                        code="manual_feature_kind_missing",
                        message=(
                            f"{column}이 있으면 manual_feature_kind도 있어야 합니다."
                        ),
                        row_number=row_number,
                        column=column,
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
        source_component_key=values["source_component_key"],
        official_ordinal=integers["official_ordinal"],
        place_name=values["place_name"],
        address_hint=values["address_hint"],
        feature_id=values["feature_id"],
        sort_order=integers["sort_order"],
        item_title=values["item_title"],
        item_summary=values["item_summary"],
        metadata_json=metadata,
        manual_feature_kind=manual_kind,
        manual_feature_lon=manual_lon,
        manual_feature_lat=manual_lat,
        issues=tuple(issues),
    )


def _parse_coordinate(
    value: str,
    row_number: int,
    column: str,
    limit: int,
    issues: list[CurationImportIssue],
) -> Decimal | None:
    """WGS84 좌표 한 성분을 ``Decimal``로 읽는다.

    ``float``가 아니라 ``Decimal``인 이유는 CSV에 적힌 자릿수를 그대로 보존해야
    canonical payload SHA-256이 재현 가능하기 때문이다 — ``0.1`` 같은 값이 float
    왕복에서 달라지면 같은 파일이 다른 SHA를 낸다.
    """
    if not value:
        issues.append(
            CurationImportIssue(
                code="manual_feature_coordinate_missing",
                message=f"manual Feature에는 {column}이 필요합니다.",
                row_number=row_number,
                column=column,
            )
        )
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        issues.append(
            CurationImportIssue(
                code="invalid_coordinate",
                message=f"좌표 형식이 아닙니다: {column}",
                row_number=row_number,
                column=column,
            )
        )
        return None
    if not parsed.is_finite() or abs(parsed) > limit:
        issues.append(
            CurationImportIssue(
                code="coordinate_out_of_range",
                message=f"{column}은 -{limit}~{limit} 범위여야 합니다.",
                row_number=row_number,
                column=column,
            )
        )
        return None
    return parsed


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
    if parsed > CURATION_INTEGER_MAX:
        issues.append(
            CurationImportIssue(
                code="integer_out_of_range",
                message=(f"{CURATION_INTEGER_MAX} 이하의 정수여야 합니다: {column}"),
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
    resolved_targets: set[tuple[str, str, str]] = set()
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
                        "같은 collection_key의 theme/title/edition/source 정의가 앞 행과 다릅니다."
                    ),
                    row_number=row.row_number,
                    column="collection_key",
                )
            )
        item_identity = (
            row.collection_key,
            row.source_item_key,
            row.source_component_key,
        )
        if item_identity in item_identities:
            issues.append(
                CurationImportIssue(
                    code="duplicate_item",
                    message="같은 collection/item/component 행이 파일 안에 중복되었습니다.",
                    row_number=row.row_number,
                    column="source_component_key",
                )
            )
        item_identities.add(item_identity)
        resolved_target = (
            row.collection_key,
            row.source_item_key,
            row.feature_id,
        )
        if row.feature_id and resolved_target in resolved_targets:
            issues.append(
                CurationImportIssue(
                    code="duplicate_feature_target",
                    message=(
                        "같은 collection/item의 component가 동일 Feature를 중복 참조합니다."
                    ),
                    row_number=row.row_number,
                    column="feature_id",
                )
            )
        if row.feature_id:
            resolved_targets.add(resolved_target)
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
