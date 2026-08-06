"""큐레이션 전용 CSV parser 단위 테스트."""

from __future__ import annotations

import csv
import io

import pytest

from kortravelmap.curation_import import (
    CURATION_CSV_HEADERS,
    CURATION_CSV_MAX_BYTES,
    CURATION_CSV_MAX_CELL_LENGTH,
    CURATION_CSV_MAX_ROWS,
    CURATION_INTEGER_MAX,
    parse_curation_csv,
)

pytestmark = pytest.mark.unit


def test_parse_curation_csv_accepts_bom_and_quoted_comma() -> None:
    content = _csv_bytes(
        _valid_row(
            place_name="창덕궁, 후원",
            official_ordinal="3",
            sort_order="10",
            metadata_json='{"course": "왕가의 길"}',
        ),
        bom=True,
    )

    preview = parse_curation_csv(content)

    assert preview.has_errors is False
    assert preview.headers == CURATION_CSV_HEADERS
    assert preview.rows_total == 1
    row = preview.rows[0]
    assert row.row_number == 2
    assert row.status == "valid"
    assert row.place_name == "창덕궁, 후원"
    assert row.official_ordinal == 3
    assert row.sort_order == 10
    assert row.metadata_json == {"course": "왕가의 길"}


def test_parse_curation_csv_reports_bad_json_and_integer() -> None:
    content = _csv_bytes(
        _valid_row(official_ordinal="first", sort_order="1.5", metadata_json="{broken")
    )

    preview = parse_curation_csv(content)

    assert preview.invalid_rows == 1
    assert preview.rows[0].status == "invalid"
    assert {(issue.code, issue.column) for issue in preview.rows[0].issues} == {
        ("invalid_integer", "official_ordinal"),
        ("invalid_integer", "sort_order"),
        ("invalid_json", "metadata_json"),
    }


def test_parse_curation_csv_requires_json_object() -> None:
    preview = parse_curation_csv(_csv_bytes(_valid_row(metadata_json='["not", "object"]')))

    assert preview.rows[0].status == "invalid"
    assert preview.rows[0].issues[0].code == "json_object_required"


def test_parse_curation_csv_rejects_duplicate_header() -> None:
    headers = (*CURATION_CSV_HEADERS, "collection_key")

    preview = parse_curation_csv(_csv_bytes(_valid_row(), headers=headers))

    assert preview.rows == ()
    assert ("duplicate_header", "collection_key") in {
        (issue.code, issue.column) for issue in preview.issues
    }


def test_parse_curation_csv_rejects_missing_header() -> None:
    headers = tuple(header for header in CURATION_CSV_HEADERS if header != "metadata_json")

    preview = parse_curation_csv(_csv_bytes(_valid_row(), headers=headers))

    assert preview.rows == ()
    assert ("missing_header", "metadata_json") in {
        (issue.code, issue.column) for issue in preview.issues
    }


def test_parse_curation_csv_rejects_oversize_file() -> None:
    preview = parse_curation_csv(b"x" * (CURATION_CSV_MAX_BYTES + 1))

    assert preview.has_errors is True
    assert preview.issues[0].code == "file_too_large"


def test_parse_curation_csv_rejects_too_many_rows() -> None:
    row = _valid_row()
    content = _csv_bytes(*(row for _ in range(CURATION_CSV_MAX_ROWS + 1)))

    preview = parse_curation_csv(content)

    assert preview.rows_total == CURATION_CSV_MAX_ROWS + 1
    assert len(preview.rows) == CURATION_CSV_MAX_ROWS
    assert preview.issues[0].code == "too_many_rows"


@pytest.mark.parametrize(
    "missing",
    [
        "collection_key",
        "theme_slug",
        "theme_name",
        "theme_group",
        "title",
        "provider_dataset_id",
        "source_name",
        "source_item_key",
        "source_component_key",
    ],
)
def test_parse_curation_csv_rejects_empty_required_value(missing: str) -> None:
    preview = parse_curation_csv(_csv_bytes(_valid_row(**{missing: ""})))

    assert ("required_value_missing", missing) in {
        (issue.code, issue.column) for issue in preview.rows[0].issues
    }


def test_parse_curation_csv_requires_feature_id_or_place_name() -> None:
    preview = parse_curation_csv(_csv_bytes(_valid_row(place_name="", feature_id="")))

    assert preview.rows[0].status == "invalid"
    assert "feature_reference_missing" in {issue.code for issue in preview.rows[0].issues}


def test_parse_curation_csv_accepts_feature_id_without_place_name() -> None:
    preview = parse_curation_csv(
        _csv_bytes(_valid_row(place_name="", feature_id="01J00000000000000000000000"))
    )

    assert preview.rows[0].status == "valid"


def test_parse_curation_csv_rejects_long_cell() -> None:
    preview = parse_curation_csv(
        _csv_bytes(_valid_row(item_summary="가" * (CURATION_CSV_MAX_CELL_LENGTH + 1)))
    )

    assert ("cell_too_long", "item_summary") in {
        (issue.code, issue.column) for issue in preview.rows[0].issues
    }


def test_parse_curation_csv_rejects_negative_order() -> None:
    preview = parse_curation_csv(_csv_bytes(_valid_row(sort_order="-1")))

    assert ("negative_integer", "sort_order") in {
        (issue.code, issue.column) for issue in preview.rows[0].issues
    }


@pytest.mark.parametrize("column", ["official_ordinal", "sort_order"])
def test_parse_curation_csv_rejects_postgres_integer_overflow(column: str) -> None:
    preview = parse_curation_csv(_csv_bytes(_valid_row(**{column: str(CURATION_INTEGER_MAX + 1)})))

    assert ("integer_out_of_range", column) in {
        (issue.code, issue.column) for issue in preview.rows[0].issues
    }


def test_parse_curation_csv_rejects_conflicting_collection_definition() -> None:
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(source_item_key="item-1"),
            _valid_row(source_item_key="item-2", title="다른 제목"),
        )
    )

    assert preview.invalid_rows == 1
    assert preview.rows[1].issues[-1].code == "collection_definition_conflict"


def test_parse_curation_csv_rejects_duplicate_item_identity() -> None:
    row = _valid_row()
    preview = parse_curation_csv(_csv_bytes(row, row))

    assert preview.invalid_rows == 1
    assert preview.rows[1].issues[-1].code == "duplicate_item"


def test_parse_curation_csv_accepts_distinct_unresolved_components() -> None:
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(source_component_key="component-01"),
            _valid_row(
                source_component_key="component-02",
                place_name="다른 공식 표기",
            ),
        )
    )

    assert preview.invalid_rows == 0


def test_parse_curation_csv_accepts_mixed_linked_and_unresolved_components() -> None:
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(source_component_key="component-01"),
            _valid_row(
                source_component_key="component-02",
                feature_id="feature:linked",
                place_name="",
            ),
        )
    )

    assert preview.invalid_rows == 0


def test_parse_curation_csv_rejects_duplicate_feature_target_across_components() -> None:
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(
                source_component_key="component-01",
                feature_id="feature:linked",
            ),
            _valid_row(
                source_component_key="component-02",
                feature_id="feature:linked",
            ),
        )
    )

    assert preview.invalid_rows == 1
    assert "duplicate_feature_target" in {
        issue.code for issue in preview.rows[1].issues
    }


def _valid_row(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(CURATION_CSV_HEADERS, "")
    row.update(
        {
            "collection_key": "visit-korea-100:2025-2026",
            "theme_slug": "visit-korea-100",
            "theme_name": "한국관광 100선",
            "theme_group": "관광",
            "title": "2025-2026 한국관광 100선",
            "provider_dataset_id": "101",
            "source_name": "한국관광공사",
            "source_item_key": "2025-2026:1",
            "source_component_key": "primary",
            "place_name": "창덕궁",
        }
    )
    row.update(overrides)
    return row


def _csv_bytes(
    *rows: dict[str, str],
    headers: tuple[str, ...] = CURATION_CSV_HEADERS,
    bom: bool = False,
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    content = stream.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + content) if bom else content
