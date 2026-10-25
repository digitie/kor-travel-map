"""정본 Place DTO 예산의 경계와 serializer 실행 전 거부를 검증한다."""

from decimal import Decimal
from enum import Enum

import pytest
from pydantic import BaseModel, field_serializer

from kortravelmap.core.feature_projection import within_place_projection_budget
from kortravelmap.dto import PlaceDetail


@pytest.mark.parametrize(("count", "expected"), [(8191, True), (8192, False)])
def test_node_budget_includes_container(count, expected):
    assert within_place_projection_budget(([None] * count,)) is expected


@pytest.mark.parametrize(("depth", "expected"), [(64, True), (65, False)])
def test_depth_budget_rejects_next_level(depth, expected):
    value = None
    for _ in range(depth):
        value = [value]
    assert within_place_projection_budget((value,)) is expected


@pytest.mark.parametrize(("count", "expected"), [(1_048_566, True), (1_048_567, False)])
def test_encoded_byte_budget_includes_json_quotes_and_node_allowance(count, expected):
    assert within_place_projection_budget(("x" * count,)) is expected


def test_canonical_place_is_walked_without_calling_model_dump(monkeypatch):
    detail = PlaceDetail(feature_id="budget-fixture", place_kind="airport")

    def unexpected_dump(*_args, **_kwargs):
        raise AssertionError("예산 검사 중 serializer를 호출하면 안 된다")

    monkeypatch.setattr(PlaceDetail, "model_dump", unexpected_dump)
    assert within_place_projection_budget((detail,))
    assert detail.phones == []
    assert detail.feature_id == "budget-fixture"


def test_foreign_model_is_rejected_before_custom_serializer():
    calls = []

    class Foreign(BaseModel):
        value: str

        @field_serializer("value")
        def serialize_value(self, value):
            calls.append(value)
            raise AssertionError("외부 serializer 실행 금지")

    assert not within_place_projection_budget((Foreign(value="small"),))
    assert calls == []


def test_canonical_model_copy_undeclared_field_is_rejected():
    detail = PlaceDetail(feature_id="budget-fixture", place_kind="airport")
    changed = detail.model_copy(update={"undeclared": "x"})
    assert not within_place_projection_budget((changed,))
    assert "undeclared" in changed.__dict__


@pytest.mark.parametrize("payload", ["x" * 1_048_577, [None] * 8192, {"x": "y" * 1_048_577}])
def test_plain_enum_value_has_the_same_budget(payload):
    enum_type = Enum("BudgetEnum", {"ITEM": payload})
    assert not within_place_projection_budget((enum_type.ITEM,))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("Infinity")])
def test_nonfinite_numeric_is_rejected(value):
    assert not within_place_projection_budget((value,))


def test_cyclic_input_stops_at_the_existing_depth_bound():
    value = []
    value.append(value)
    assert not within_place_projection_budget((value,))
