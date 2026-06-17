"""``test_ids`` — ``kortravelmap.core.ids`` 결정적 ID 생성 검증.

ADR-009 (``feature_id`` 결정적 생성) 명세를 강제한다. SPEC V8 D-2 입력 예제는
``docs/architecture/data-model.md §11`` + ``docs/test-strategy.md §3.3`` 참고.
"""

from __future__ import annotations

import hashlib

import pytest

from kortravelmap.core.ids import FEATURE_ID_HASH_LENGTH, make_feature_id

# -- 결정성 / 멱등 -----------------------------------------------------------


def test_same_input_yields_same_id() -> None:
    """같은 입력은 항상 같은 ID를 낳는다 (idempotent upsert 전제)."""
    a = make_feature_id(
        bjd_code="1168010100",
        kind="place",
        category="PLACE_RESTAURANT",
        source_type="krex_rest_area",
        source_natural_key="RA00012",
    )
    b = make_feature_id(
        bjd_code="1168010100",
        kind="place",
        category="PLACE_RESTAURANT",
        source_type="krex_rest_area",
        source_natural_key="RA00012",
    )
    assert a == b


def test_id_format_matches_adr_009_spec() -> None:
    """ID 포맷: ``f_{bjd_code}_{kind[0]}_{sha1[:16]}``."""
    fid = make_feature_id(
        bjd_code="1168010100",
        kind="place",
        category="PLACE_RESTAURANT",
        source_type="krex_rest_area",
        source_natural_key="RA00012",
    )
    assert fid.startswith("f_1168010100_p_")
    parts = fid.split("_")
    assert len(parts) == 4
    assert parts[0] == "f"
    assert parts[1] == "1168010100"
    assert parts[2] == "p"
    assert len(parts[3]) == FEATURE_ID_HASH_LENGTH == 16
    # hex only
    int(parts[3], 16)


def test_bjd_code_none_uses_global() -> None:
    """``bjd_code=None`` → ``'global'`` placeholder (행정구역 외)."""
    fid = make_feature_id(
        bjd_code=None,
        kind="event",
        category="EVENT_FESTIVAL",
        source_type="tour_api",
        source_natural_key="EVT001",
    )
    assert fid.startswith("f_global_e_")


def test_bjd_code_empty_string_uses_global() -> None:
    """``bjd_code=''`` (빈 문자열) → ``'global'``."""
    fid = make_feature_id(
        bjd_code="",
        kind="event",
        category="EVENT_FESTIVAL",
        source_type="tour_api",
        source_natural_key="EVT001",
    )
    assert fid.startswith("f_global_e_")


# -- 변화 감지 (충돌 회피) ---------------------------------------------------


@pytest.mark.parametrize(
    ("field", "new_value"),
    [
        ("bjd_code", "1168010200"),
        ("kind", "event"),
        ("category", "PLACE_CAFE"),
        ("source_type", "krex_rest_area_v2"),
        ("source_natural_key", "RA00013"),
    ],
)
def test_changing_any_component_yields_different_id(
    field: str, new_value: str
) -> None:
    """구성요소 중 하나라도 바뀌면 ID도 바뀌어야 한다."""
    base = {
        "bjd_code": "1168010100",
        "kind": "place",
        "category": "PLACE_RESTAURANT",
        "source_type": "krex_rest_area",
        "source_natural_key": "RA00012",
    }
    a = make_feature_id(**base)
    modified = {**base, field: new_value}
    b = make_feature_id(**modified)
    assert a != b, f"changing {field} did not change ID"


def test_content_hash_option_changes_id() -> None:
    """``content_hash`` 옵션이 다르면 ID도 달라야 한다 (payload 버전 분리)."""
    a = make_feature_id(
        bjd_code="1168010100",
        kind="place",
        category="PLACE_RESTAURANT",
        source_type="krex_rest_area",
        source_natural_key="RA00012",
    )
    b = make_feature_id(
        bjd_code="1168010100",
        kind="place",
        category="PLACE_RESTAURANT",
        source_type="krex_rest_area",
        source_natural_key="RA00012",
        content_hash="abc123",
    )
    assert a != b


def test_content_hash_none_equals_empty_string_implicit() -> None:
    """``content_hash=None``과 ``content_hash=''``은 같은 ID여야 한다.

    내부 구현이 ``content_hash or ''``로 평탄화되므로 두 입력은 동치.
    """
    a = make_feature_id(
        bjd_code="1100000000",
        kind="notice",
        category="NOTICE_GENERAL",
        source_type="kma",
        source_natural_key="N001",
        content_hash=None,
    )
    b = make_feature_id(
        bjd_code="1100000000",
        kind="notice",
        category="NOTICE_GENERAL",
        source_type="kma",
        source_natural_key="N001",
        content_hash="",
    )
    assert a == b


# -- kind prefix 7종 ---------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected_prefix"),
    [
        ("place", "p"),
        ("event", "e"),
        ("notice", "n"),
        ("price", "p"),  # price도 p로 시작 — bjd가 같으면 place와 prefix가 겹침
        ("weather", "w"),
        ("route", "r"),
        ("area", "a"),
    ],
)
def test_kind_prefix_first_char(kind: str, expected_prefix: str) -> None:
    """``kind``의 첫 글자가 ID prefix에 박힌다 (ADR-009)."""
    fid = make_feature_id(
        bjd_code="1100000000",
        kind=kind,
        category="GENERIC",
        source_type="provider_x",
        source_natural_key="K001",
    )
    assert f"_{expected_prefix}_" in fid


def test_place_and_price_can_share_prefix_but_full_id_differs() -> None:
    """``place``/``price``는 둘 다 ``p``로 시작하나 sha1이 달라 ID는 다르다."""
    p_place = make_feature_id(
        bjd_code="1100000000",
        kind="place",
        category="PLACE_RESTAURANT",
        source_type="provider_x",
        source_natural_key="K001",
    )
    p_price = make_feature_id(
        bjd_code="1100000000",
        kind="price",
        category="PRICE_GASOLINE",
        source_type="provider_x",
        source_natural_key="K001",
    )
    assert p_place != p_price
    assert p_place.startswith("f_1100000000_p_")
    assert p_price.startswith("f_1100000000_p_")


# -- StrEnum 호환 -----------------------------------------------------------


def test_strenum_kind_works() -> None:
    """``StrEnum`` 멤버(FeatureKind.PLACE 등)를 그대로 넘겨도 동작한다.

    PR#19에서 dto에 정의될 ``FeatureKind`` (StrEnum)는 ``str``의 서브클래스이므로
    본 함수는 별도 분기 없이 ``str(kind)``로 안전하게 처리한다.
    """
    from enum import StrEnum

    class _MockFeatureKind(StrEnum):
        PLACE = "place"

    fid_enum = make_feature_id(
        bjd_code="1100000000",
        kind=_MockFeatureKind.PLACE,
        category="PLACE_RESTAURANT",
        source_type="provider_x",
        source_natural_key="K001",
    )
    fid_str = make_feature_id(
        bjd_code="1100000000",
        kind="place",
        category="PLACE_RESTAURANT",
        source_type="provider_x",
        source_natural_key="K001",
    )
    assert fid_enum == fid_str


# -- validation -------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["kind", "category", "source_type", "source_natural_key"],
)
def test_empty_required_component_raises(field: str) -> None:
    """필수 구성요소가 빈 문자열이면 ValueError."""
    base = {
        "bjd_code": "1100000000",
        "kind": "place",
        "category": "PLACE_RESTAURANT",
        "source_type": "provider_x",
        "source_natural_key": "K001",
    }
    base[field] = ""
    with pytest.raises(ValueError, match=field):
        make_feature_id(**base)


@pytest.mark.parametrize(
    "field",
    ["kind", "category", "source_type", "source_natural_key"],
)
def test_pipe_in_component_raises(field: str) -> None:
    """``|``는 구분자 — 어느 필드에 들어가도 ID 결정성 깨짐, ValueError."""
    base = {
        "bjd_code": "1100000000",
        "kind": "place",
        "category": "PLACE_RESTAURANT",
        "source_type": "provider_x",
        "source_natural_key": "K001",
    }
    base[field] = "bad|value"
    with pytest.raises(ValueError, match=r"\|"):
        make_feature_id(**base)


# -- SHA1 정합성 -------------------------------------------------------------


def test_sha1_matches_explicit_computation() -> None:
    """내부 SHA1 계산이 명시적 hashlib 호출과 일치해야 한다.

    회귀 방지 — 입력 포맷이 미세하게라도 바뀌면 본 테스트가 깨진다.
    같은 입력은 영원히 같은 ID를 낳아야 (DB에 박힌 ID 무효화 방지).
    """
    bjd = "1168010100"
    kind = "place"
    category = "PLACE_RESTAURANT"
    stype = "krex_rest_area"
    snk = "RA00012"
    chash = ""

    expected_input = f"{bjd}|{kind}|{category}|{stype}|{snk}|{chash}"
    expected_digest = hashlib.sha1(
        expected_input.encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:16]
    expected_id = f"f_{bjd}_{kind[0]}_{expected_digest}"

    actual = make_feature_id(
        bjd_code=bjd,
        kind=kind,
        category=category,
        source_type=stype,
        source_natural_key=snk,
    )
    assert actual == expected_id
