"""429 원문을 고정해 provider RC 진입 조건 외 전체 body/owner/ACL 경계를 검증한다."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from tests.unit.test_snapshot_recovery_schema import migration

_ROOT = Path(__file__).resolve().parents[2]
_FILENAME = "_430_provider_finalization_catalog_rc.sql"
_FROZEN = Path(__file__).with_name("fixtures") / "provider_finalization_catalog_429.sql"
_NAMES = (
    "refresh_curated_source_observation",
    "materialize_theme_candidate_generation",
    "sync_concierge_theme_catalog",
)


def _definition(source: str, name: str) -> str:
    found = re.findall(
        r"CREATE (?:OR REPLACE )?PROCEDURE feature\." + name + r"\(.*?\n\$\$;",
        source,
        re.DOTALL,
    )
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize("name", _NAMES)
def test_exact_old_ser_body_is_preserved_except_fenced_provider_rc_condition(name):
    old = _definition(_FROZEN.read_text(), name)
    current = _definition((_ROOT / "alembic/versions" / _FILENAME).read_text(), name)
    start = current.index("  -- 기존 SER은 그대로다.")
    end = current.index("  ) THEN", start) + len("  ) THEN")
    guard = current[start:end]
    restored = (
        current[:start]
        + "  IF current_setting('transaction_isolation') <> 'serializable' THEN"
        + current[end:]
    ).replace("CREATE OR REPLACE PROCEDURE", "CREATE PROCEDURE", 1)
    assert restored == old
    assert "current_setting('transaction_isolation') = 'read committed'" in guard
    assert guard.count("pid=pg_backend_pid() AND locktype='advisory' AND granted") == 2
    assert guard.count("WHERE datname=current_database()") == 2
    assert "classid=1369104691 AND objid=115 AND objsubid=2 AND mode='ExclusiveLock'" in guard
    assert (
        "classid=1590807301 AND objid=1746797985 AND objsubid=1 AND mode='ExclusiveLock'" in guard
    )
    assert "pg_advisory" not in guard  # 관측만 하며 blocking/승격을 추가하지 않는다.
    if name == "materialize_theme_candidate_generation":
        assert "p_generation_kind IS NOT DISTINCT FROM 'provider_full_snapshot'" in guard
    else:
        assert "p_generation_kind" not in guard


def test_existing_command_owner_definitions_have_no_new_acl_or_public_surface():
    declarations = dict(migration._SIDECARS)[_FILENAME]
    assert declarations == (
        (
            "feature.refresh_curated_source_observation",
            "PROCEDURE",
            "(bigint,uuid)",
            migration._COMMAND_OWNER,
            False,
            False,
        ),
        (
            "feature.materialize_theme_candidate_generation",
            "PROCEDURE",
            "(uuid,text,uuid,uuid,bigint,text,jsonb)",
            migration._COMMAND_OWNER,
            False,
            False,
        ),
        (
            "feature.sync_concierge_theme_catalog",
            "PROCEDURE",
            "(bigint,uuid)",
            migration._COMMAND_OWNER,
            False,
            False,
        ),
    )
    sections = migration._sections(_FILENAME, declarations)
    assert [owner for owner, _ in sections] == [migration._COMMAND_OWNER] * 3
    current = (_ROOT / "alembic/versions" / _FILENAME).read_text()
    assert "".join(body for _, body in sections) == current
    assert not any(word in current for word in ("GRANT ", "REVOKE ", "ALTER PROCEDURE"))


def test_frozen_429_definitions_have_exact_pinned_provenance():
    source = _FROZEN.read_text()
    assert "e1734f9365cbccbd5ebb45d09784c72994f6c175/alembic/head-schema.sql" in source
    assert "893e61bb8532bc1dd0c9c4d56aeec7941af33eac649a32bd9ca40ea305b3175f" in source
    assert [hashlib.sha256(_definition(source, name).encode()).hexdigest() for name in _NAMES] == [
        "2f36e1ea018c8f40e4ace8e687db833c07103b5e0bd30d0443eb07ad5d9af719",
        "ab5329559e4141395c1e8745edaa72ad24b454b6ee952317f8545a916aba286d",
        "da41f1ed851b7a3f1b3d3e926fabfa1045dca83f3914f301ee9ba918a65e9197",
    ]
