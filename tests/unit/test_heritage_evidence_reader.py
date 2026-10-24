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
