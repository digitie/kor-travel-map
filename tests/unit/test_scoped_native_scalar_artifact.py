"""artifact의 재생 결정성과 직렬화 전 자원 상한을 검사한다."""

import pytest

from kortravelmap.infra import scoped_provider_refresh as native


def test_artifact_order_is_stable_for_presence_and_raw_object_keys():
    first = {"raw": {"b": 2, "a": 1}, "presence": frozenset(["place.phones", "core.name"])}
    second = {"presence": frozenset(["core.name", "place.phones"]), "raw": {"a": 1, "b": 2}}
    assert native._artifact_digest(first) == native._artifact_digest(second)
    assert native._artifact_digest(first) != native._artifact_digest({**first, "raw": {"a": 2}})


@pytest.mark.parametrize("kind", ["large-string", "deep-nesting", "many-items"])
def test_artifact_budget_rejects_before_json_copy(monkeypatch, kind):
    if kind == "large-string":
        value = {"raw": "x" * (native._MAX_INPUT_BYTES + 1)}
    elif kind == "deep-nesting":
        value = {}
        for _ in range(80):
            value = {"child": value}
    else:
        value = {"raw": [0] * (native._MAX_INPUT_BYTES // 8 + 1)}

    def copy_forbidden(*args, **kwargs):
        pytest.fail("oversized artifact reached JSON serialization")

    monkeypatch.setattr(native.json, "JSONEncoder", copy_forbidden)
    with pytest.raises(ValueError, match="budget|1 MiB"):
        native._artifact_digest(value)


def test_large_enum_value_is_rejected_before_json_serialization(monkeypatch):
    from enum import Enum

    class Large(Enum):
        VALUE = "x" * (native._MAX_INPUT_BYTES + 1)

    def serialization_forbidden(*args, **kwargs):
        pytest.fail("oversized Enum reached JSON serialization")

    monkeypatch.setattr(native.json, "JSONEncoder", serialization_forbidden)
    with pytest.raises(ValueError, match="budget|1 MiB"):
        native._artifact_digest({"payload": Large.VALUE})


def test_model_budget_walk_does_not_copy_the_entire_model_first(monkeypatch):
    from pydantic import BaseModel

    class Input(BaseModel):
        payload: str

    class CopyForbidden(dict):
        def __init__(self, *args, **kwargs):
            pytest.fail("budget walk copied a complete BaseModel")

    model = Input(payload="x" * (native._MAX_INPUT_BYTES + 1))
    monkeypatch.setattr(native, "dict", CopyForbidden, raising=False)
    with pytest.raises(ValueError, match="budget|1 MiB"):
        native._check_artifact_budget(model, [native._MAX_INPUT_BYTES])
