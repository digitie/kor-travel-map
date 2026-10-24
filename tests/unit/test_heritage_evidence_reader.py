"""증거 reader 입력의 무한 iterable/형식/중복/별도 권한 의미 경계를 확인한다."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from kortravelmap.infra.heritage_evidence_reader import validate_heritage_evidence_request


def _key(index: int) -> str:
    return f"se_{index:064x}"


def test_request_retains_exact_target_order_without_granting_apply() -> None:
    request = validate_heritage_evidence_request(7, [_key(2), _key(1)])
    assert request.dataset_id == 7
    assert request.entity_keys == (_key(2), _key(1))


@pytest.mark.parametrize("dataset", [True, 0, -1, 2**63, 1.0, "1"])
def test_rejects_non_bigint_dataset(dataset: object) -> None:
    with pytest.raises(ValueError, match="positive PostgreSQL bigint"):
        validate_heritage_evidence_request(dataset, [_key(1)])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "keys",
    [
        [],
        [_key(1), _key(1)],
        ["se_" + "A" * 64],
        ["se_" + "a" * 63],
        ["se_" + "a" * 1_000_000],
        [None],
        _key(1),
    ],
)
def test_rejects_invalid_or_duplicate_keys(keys: object) -> None:
    with pytest.raises(ValueError, match="empty|duplicate|canonical|iterable"):
        validate_heritage_evidence_request(1, keys)  # type: ignore[arg-type]


def test_maximum_request_is_allowed() -> None:
    request = validate_heritage_evidence_request(1, (_key(i) for i in range(2730)))
    assert len(request.entity_keys) == 2730


def test_unbounded_input_consumes_only_max_plus_one() -> None:
    consumed = 0

    def stream() -> Iterator[str]:
        nonlocal consumed
        while True:
            consumed += 1
            yield _key(consumed)

    with pytest.raises(ValueError, match="2730"):
        validate_heritage_evidence_request(1, stream())
    assert consumed == 2731


def test_decode_known_rejection_is_not_apply_authority():
    from kortravelmap.infra.heritage_evidence_reader import decode_heritage_evidence

    request = validate_heritage_evidence_request(7, ["se_" + "a" * 64])
    result = decode_heritage_evidence(
        request,
        {
            "version": 1,
            "evidence_complete": False,
            "reason": "unsupported_membership",
            "dataset_id": 7,
            "policy_epoch": None,
            "items": [],
        },
    )
    assert result.evidence_complete is False
    assert result.items == ()
    assert result.reason.value == "unsupported_membership"


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"dataset_id": True},
        {"dataset_id": 8},
        {"reason": "unexpected_sql_failure"},
        {"policy_epoch": 1},
        {"items": [None]},
        {"evidence_complete": "false"},
        {"extra": "field"},
    ],
)
def test_decode_rejects_unbound_or_unknown_envelopes(change):
    from kortravelmap.infra.heritage_evidence_reader import decode_heritage_evidence

    request = validate_heritage_evidence_request(7, ["se_" + "a" * 64])
    value = {
        "version": 1,
        "evidence_complete": False,
        "reason": "shape_unsupported",
        "dataset_id": 7,
        "policy_epoch": None,
        "items": [],
    }
    value.update(change)
    with pytest.raises(ValueError, match="heritage evidence"):
        decode_heritage_evidence(request, value)


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        {"x": "x" * 1_048_577},
        {"x": [None] * 65_537},
        {"x": 2**64},
        {1: "invalid"},
        {"x": object()},
    ],
)
def test_response_budget_rejects_before_schema_processing(value):
    from kortravelmap.infra.heritage_evidence_reader import decode_heritage_evidence

    request = validate_heritage_evidence_request(7, ["se_" + "a" * 64])
    with pytest.raises(ValueError, match="heritage evidence"):
        decode_heritage_evidence(request, value)


@pytest.mark.asyncio
async def test_sql_errors_are_not_known_ineligibility():
    from kortravelmap.infra.heritage_evidence_reader import read_heritage_evidence

    original = RuntimeError("private driver failure")

    class Session:
        async def scalar(self, *_args, **_kwargs):
            raise original

    with pytest.raises(RuntimeError) as caught:
        await read_heritage_evidence(Session(), 7, ["se_" + "a" * 64])
    assert caught.value is original
