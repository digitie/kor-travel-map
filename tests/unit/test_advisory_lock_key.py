"""``test_advisory_lock_key`` — advisory lock 키 해싱 (순수, ADR-011).

``advisory_lock_key``는 문자열 → signed int64 결정적 해시. PostgreSQL advisory
lock 인자(bigint) 범위를 벗어나지 않고, 같은 입력은 항상 같은 정수여야 한다.
"""

from __future__ import annotations

from kortravelmap.infra.advisory_lock import advisory_lock_key

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def test_deterministic() -> None:
    assert advisory_lock_key("import:python-mois-api:bulk") == advisory_lock_key(
        "import:python-mois-api:bulk"
    )


def test_within_signed_int64_range() -> None:
    for key in (
        "",
        "a",
        "import:python-mois-api:mois_license_features_bulk",
        "dedup-merge:f_1111010100_p_deadbeef",
        "alembic-upgrade",
        "x" * 500,
    ):
        value = advisory_lock_key(key)
        assert _INT64_MIN <= value <= _INT64_MAX
        assert isinstance(value, int)


def test_distinct_keys_differ() -> None:
    keys = {
        advisory_lock_key(k)
        for k in (
            "import:python-mois-api:bulk",
            "import:python-mois-api:history",
            "import:python-knps-api:bulk",
            "dedup-merge:abc",
            "alembic-upgrade",
        )
    }
    # 충돌 없이 5개 모두 distinct.
    assert len(keys) == 5
