"""``test_cli_mutex_keys`` — CLI mutex lock key 컨벤션 (순수, ADR-039).

SPRINT-4 §2.8 lock key 포맷을 검증한다 (advisory lock 동작은 integration에서).
"""

from __future__ import annotations

from krtour.map.cli import (
    alembic_upgrade_lock_key,
    dedup_merge_lock_key,
    import_lock_key,
)


def test_import_lock_key() -> None:
    assert (
        import_lock_key("python-mois-api", "mois_license_features_bulk")
        == "import:python-mois-api:mois_license_features_bulk"
    )


def test_dedup_merge_lock_key() -> None:
    assert (
        dedup_merge_lock_key("f_1111010100_p_deadbeef")
        == "dedup-merge:f_1111010100_p_deadbeef"
    )


def test_alembic_upgrade_lock_key() -> None:
    assert alembic_upgrade_lock_key() == "alembic-upgrade"


def test_keys_are_distinct() -> None:
    keys = {
        import_lock_key("python-mois-api", "bulk"),
        import_lock_key("python-knps-api", "bulk"),
        dedup_merge_lock_key("f_a"),
        alembic_upgrade_lock_key(),
    }
    assert len(keys) == 4
