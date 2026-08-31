"""큐레이션 전용 CSV parser 단위 테스트."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

import pytest

from kortravelmap.curation_import import (
    CURATION_CSV_HEADERS,
    CURATION_CSV_MAX_BYTES,
    CURATION_CSV_MAX_CELL_LENGTH,
    CURATION_CSV_MAX_ROWS,
    CURATION_CSV_OPTIONAL_HEADERS,
    CURATION_INTEGER_MAX,
    manual_feature_payload,
    manual_feature_payload_sha256,
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
        "provider",
        "dataset_key",
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
            "provider": "kto",
            "dataset_key": "visit_korea_100",
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


# -- T-VN-M03 manual Feature 선택 header -----------------------------------
#
# 좌표를 `metadata_json`이 아니라 typed 열로 받는다(설계 §6.1). 주소에서 추론하지
# 않는다(§7). 그래서 파일이 좌표를 **명시적으로** 실어야 하고, 그 계약을 여기서
# 고정한다.

_MANUAL_HEADERS = (*CURATION_CSV_HEADERS, *CURATION_CSV_OPTIONAL_HEADERS)


def test_manual_feature_headers_are_optional() -> None:
    """선택 header가 없는 기존 CSV는 그대로 유효하고 manual Feature를 만들지 않는다."""
    preview = parse_curation_csv(_csv_bytes(_valid_row()))

    assert preview.has_errors is False
    row = preview.rows[0]
    assert row.manual_feature_kind == ""
    assert row.manual_feature_lon is None
    assert row.manual_feature_lat is None


def test_manual_feature_row_parses_typed_coordinates() -> None:
    """좌표는 CSV에 적힌 자릿수 그대로 ``Decimal``로 보존된다.

    canonical payload SHA-256이 재현 가능해야 하므로 float 왕복을 쓰지 않는다.
    """
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(
                manual_feature_kind="place",
                manual_feature_category="12010000",
                manual_feature_lon="126.99100",
                manual_feature_lat="37.57960",
            ),
            headers=_MANUAL_HEADERS,
        )
    )

    assert preview.has_errors is False
    row = preview.rows[0]
    assert row.manual_feature_kind == "place"
    assert row.manual_feature_category == "12010000"
    assert row.manual_feature_lon == Decimal("126.99100")
    assert row.manual_feature_lat == Decimal("37.57960")
    assert str(row.manual_feature_lon) == "126.99100"


def test_manual_feature_headers_must_appear_together() -> None:
    """셋 중 일부만 있으면 거절한다 — 좌표 없는 kind는 만들 수 없다."""
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(),
            headers=(*CURATION_CSV_HEADERS, "manual_feature_kind"),
        )
    )

    codes = {issue.code for issue in preview.issues}
    assert "partial_manual_feature_headers" in codes


@pytest.mark.parametrize(
    ("kind", "lon", "lat", "expected_code"),
    [
        ("shop", "127.0", "37.5", "invalid_manual_feature_kind"),
        ("place", "", "37.5", "manual_feature_coordinate_missing"),
        ("place", "127.0", "", "manual_feature_coordinate_missing"),
        ("place", "동경", "37.5", "invalid_coordinate"),
        ("place", "181.0", "37.5", "coordinate_out_of_range"),
        ("place", "127.0", "91.0", "coordinate_out_of_range"),
    ],
)
def test_manual_feature_row_rejects_bad_values(
    kind: str, lon: str, lat: str, expected_code: str
) -> None:
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(
                manual_feature_kind=kind,
                manual_feature_lon=lon,
                manual_feature_lat=lat,
            ),
            headers=_MANUAL_HEADERS,
        )
    )

    row = preview.rows[0]
    assert row.status == "invalid"
    assert expected_code in {issue.code for issue in row.issues}


def test_manual_feature_cannot_coexist_with_feature_id() -> None:
    """기존 Feature를 가리키면서 새로 만들 수는 없다.

    둘 다 주면 어느 쪽이 이기는지 파일만 보고 알 수 없으므로 거절한다 — 조용히
    한쪽을 고르면 import 결과가 파일과 다른 것을 뜻하게 된다.
    """
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(
                feature_id="place:kto:visit_korea_100:1",
                manual_feature_kind="place",
                manual_feature_lon="127.0",
                manual_feature_lat="37.5",
            ),
            headers=_MANUAL_HEADERS,
        )
    )

    row = preview.rows[0]
    assert row.status == "invalid"
    assert "manual_feature_conflicts_with_feature_id" in {i.code for i in row.issues}


def test_coordinates_without_kind_are_rejected() -> None:
    """좌표만 있고 kind가 없으면 만들 의도인지 알 수 없다 — 조용히 무시하지 않는다."""
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(manual_feature_lon="127.0", manual_feature_lat="37.5"),
            headers=_MANUAL_HEADERS,
        )
    )

    row = preview.rows[0]
    assert row.status == "invalid"
    assert "manual_feature_kind_missing" in {i.code for i in row.issues}


def test_manual_feature_payload_is_none_without_kind() -> None:
    preview = parse_curation_csv(_csv_bytes(_valid_row()))

    assert manual_feature_payload(preview.rows[0]) is None


def test_manual_feature_category_must_be_an_eight_digit_code() -> None:
    """writer가 category를 요구하므로 manual 행은 8자리 code가 있어야 한다."""
    for bad in ("", "1201", "abcd1234", "120100001"):
        preview = parse_curation_csv(
            _csv_bytes(
                _valid_row(
                    manual_feature_kind="place",
                    manual_feature_category=bad,
                    manual_feature_lon="127.0",
                    manual_feature_lat="37.5",
                ),
                headers=_MANUAL_HEADERS,
            )
        )
        assert "invalid_manual_feature_category" in {
            issue.code for issue in preview.rows[0].issues
        }, bad


def test_manual_feature_row_requires_place_name_for_the_feature_name() -> None:
    """Feature 이름은 place_name이 소유한다 — manual 행에서 비울 수 없다."""
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(
                place_name="",
                manual_feature_kind="place",
                manual_feature_category="12010000",
                manual_feature_lon="127.0",
                manual_feature_lat="37.5",
            ),
            headers=_MANUAL_HEADERS,
        )
    )
    assert "manual_feature_name_missing" in {
        issue.code for issue in preview.rows[0].issues
    }


def test_category_without_manual_kind_is_rejected() -> None:
    """kind 없는 category는 지시가 불완전하다."""
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(manual_feature_category="12010000"),
            headers=_MANUAL_HEADERS,
        )
    )
    assert "manual_feature_kind_missing" in {
        issue.code for issue in preview.rows[0].issues
    }


def test_manual_feature_payload_preserves_written_precision() -> None:
    """canonical SHA가 재현 가능하려면 CSV에 적힌 자릿수가 살아 있어야 한다.

    JSON number로 담으면 ``126.99100``이 ``126.991``로 정규화돼 같은 파일이 다른
    child identity를 만들 수 있다.
    """
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(
                manual_feature_kind="place",
                manual_feature_category="12010000",
                manual_feature_lon="126.99100",
                manual_feature_lat="37.57960",
            ),
            headers=_MANUAL_HEADERS,
        )
    )

    payload = manual_feature_payload(preview.rows[0])

    assert payload == {
        "kind": "place",
        "category": "12010000",
        "coord": {"lon": "126.99100", "lat": "37.57960"},
    }


def test_manual_feature_payload_sha256_is_stable_and_precision_sensitive() -> None:
    same = manual_feature_payload_sha256(
        {"kind": "place", "coord": {"lon": "127.0", "lat": "37.5"}}
    )
    reordered = manual_feature_payload_sha256(
        {"coord": {"lat": "37.5", "lon": "127.0"}, "kind": "place"}
    )
    trimmed = manual_feature_payload_sha256(
        {"kind": "place", "coord": {"lon": "127.00", "lat": "37.5"}}
    )

    assert same == reordered, "key 순서가 identity를 바꾸면 안 된다"
    assert same != trimmed, "자릿수가 다르면 다른 payload다"
    assert len(same) == 64


def test_manual_feature_payload_omits_server_owned_fields() -> None:
    """서버가 소유하는 값을 payload에 넣지 않는다.

    ``create_manual_curation_item_with_feature_command``가 명시적으로 거절하는 키들이라,
    여기서 만들지 않는 것이 그 계약과 일치한다.
    """
    preview = parse_curation_csv(
        _csv_bytes(
            _valid_row(
                manual_feature_kind="event",
                manual_feature_category="15020000",
                manual_feature_lon="127.0",
                manual_feature_lat="37.5",
            ),
            headers=_MANUAL_HEADERS,
        )
    )

    payload = manual_feature_payload(preview.rows[0])

    assert payload is not None
    forbidden = {
        "feature_id",
        "feature_uuid",
        "origin_kind",
        "creator_principal_id",
        "lifecycle_state",
        "publication_state",
        "quality_state",
        "operator",
        "idempotency_key",
    }
    assert forbidden.isdisjoint(payload)
