"""H28 evidence scripts가 typed geo credential로 구성되는지 확인한다."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest
from pydantic import SecretStr

_ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "script_name",
    ["h28a_final.py", "h28b_recovery_check.py"],
)
def test_h28_evidence_script_uses_secret_str(
    monkeypatch: pytest.MonkeyPatch,
    script_name: str,
) -> None:
    monkeypatch.setenv("CONCIERGE_BASE", "http://127.0.0.1:1")
    monkeypatch.setenv("CONCIERGE_KEY", "concierge-test-key")
    monkeypatch.setenv("GEO_BASE", "http://127.0.0.1:2")
    monkeypatch.setenv("GEO_KEY", "geo-test-key")

    namespace = runpy.run_path(str(_ROOT / "scripts" / script_name))

    credential = namespace["GKEY"]
    assert isinstance(credential, SecretStr)
    assert credential.get_secret_value() == "geo-test-key"
