"""``test_import_linter`` — pyproject.toml의 import-linter 계약을 pytest로 wrap.

CI는 `lint-imports` CLI를 별도 job으로 실행하지만, 로컬 ``pytest`` 한 번
실행으로도 계약 위반을 감지할 수 있도록 본 테스트가 사용된다.

본 테스트는 ``importlinter.cli.lint_imports_command``를 subprocess로 호출한다.
``import_linter`` 패키지 미설치 시 ``pytest.skip``.

ADR 참조
--------
- ADR-002 — 의존 계층 강제 (``dto → core → infra → providers → client → cli``).
- ADR-020 — 메인 패키지는 FastAPI/Uvicorn 의존 금지 (디버그 UI는 별도 패키지).
- ADR-030 — in-memory cache 라이브러리 의존 금지
  (``cachetools``/``async_lru``/``aiocache``/``diskcache``).
- ADR-103 — Kafka/streaming consumer 의존 금지 (consumer는 TripMate
  ``apps/etl`` 책임).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HAS_IMPORTLINTER = importlib.util.find_spec("importlinter") is not None
pytestmark = pytest.mark.skipif(
    not _HAS_IMPORTLINTER,
    reason="import-linter not installed (`pip install -e .[dev]`)",
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHONPATH_ENTRIES = [
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "packages" / "kor-travel-map-admin" / "src",
    PROJECT_ROOT / "packages" / "kor-travel-map-dagster" / "src",
]


@pytest.mark.unit
def test_import_linter_contracts_pass() -> None:
    """pyproject.toml의 모든 import-linter 계약이 통과해야 한다.

    검증 대상 계약 (pyproject.toml ``[[tool.importlinter.contracts]]``):
    1. ``layered architecture`` (ADR-002)
    2. ``main package must not import fastapi/uvicorn`` (ADR-020)
    3. ``main package must not depend on cache libraries`` (ADR-030)
    4. ``main package must not depend on kafka/streaming libraries`` (ADR-103)
    """
    # `lint-imports` console script가 PATH에 없을 수 있으므로 Python 모듈로 실행.
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    pythonpath = os.pathsep.join(str(path) for path in PYTHONPATH_ENTRIES)
    if existing_pythonpath:
        pythonpath = os.pathsep.join([pythonpath, existing_pythonpath])
    env["PYTHONPATH"] = pythonpath
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; "
            "import sys; sys.argv=['lint-imports']; lint_imports_command()",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, (
        "import-linter 계약 위반:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}\n"
    )
