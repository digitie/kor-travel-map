"""migration이 ``provider_dataset_id`` 같은 대리키를 하드코딩하지 못하게 막는다.

TVN-C05(0230)가 prod 배포를 세운 이유가 정확히 이것이었다. ``provider_dataset_id``
는 ``Identity(always=True)`` 대리키이고 catalog identity의 정본은 자연키
``uq_provider_datasets_identity (provider, dataset_key)``다. 번호는 환경마다 다르며
실제로 달랐다 — baseline seed는 ``python-datagokr-api/standard_special_streets``를
69번으로 매기는데 prod는 73번을 배정해 뒀고, 0230이 그 73번을 자기 것으로 적어
둔 탓에 ``alembic upgrade head`` 전체가 매 재시도마다 롤백됐다.

그 사건을 막는 회귀 테스트는 0230 하나에만 붙어 있어서 **다음 migration에는
아무것도 강제하지 못한다.** 이 lint가 그 자리를 메운다: catalog 테이블에 쓰는
migration은 자연키로만 쓴다.

- ``OVERRIDING SYSTEM VALUE``는 identity가 정한 번호를 덮어쓰겠다는 선언이다.
  baseline dump(``alembic/baseline/seed.sql``)만 그럴 자격이 있고, 그건 이 lint의
  대상이 아니다(.py만 본다).
- catalog 테이블 INSERT의 ``VALUES`` 행이 정수 리터럴로 시작하면 대리키를 손으로
  적었다는 뜻이다. operation·scope는 자연키 JOIN으로 id를 되찾아야 한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic" / "versions"

_CATALOG_INSERT = re.compile(
    r"INSERT\s+INTO\s+provider_sync\.provider_dataset", re.IGNORECASE
)
_OVERRIDING_IDENTITY = re.compile(r"OVERRIDING\s+SYSTEM\s+VALUE", re.IGNORECASE)
#: ``VALUES`` 목록에서 정수 리터럴로 시작하는 행 — ``(70, 'python-...``
_LEADING_INTEGER_ROW = re.compile(r"\(\s*\d+\s*,")


def _sql_constants(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_migrations_never_pin_provider_dataset_surrogate_ids() -> None:
    violations: list[str] = []
    for path in sorted(_VERSIONS.glob("*.py")):
        relative = path.relative_to(_ROOT).as_posix()
        for lineno, sql in _sql_constants(path):
            if not _CATALOG_INSERT.search(sql):
                continue
            if _OVERRIDING_IDENTITY.search(sql):
                violations.append(
                    f"{relative}:{lineno}: OVERRIDING SYSTEM VALUE — "
                    "identity 대리키를 덮어쓰지 마라"
                )
            if _LEADING_INTEGER_ROW.search(sql):
                violations.append(
                    f"{relative}:{lineno}: catalog INSERT의 VALUES 행이 정수로 "
                    "시작한다 — provider_dataset_id는 자연키 JOIN으로 되찾아라"
                )

    assert violations == [], (
        "provider_sync catalog는 자연키 (provider, dataset_key)로만 쓴다. "
        "대리키 하드코딩: " + ", ".join(violations)
    )


def test_scanner_catches_the_tvn_c05_regression_shape() -> None:
    """scanner가 실제 사건 모양을 잡는지 — 잡지 못하면 위 테스트는 늘 초록이다."""

    regression = _ROOT / "alembic" / "versions"
    assert regression.is_dir()

    sample = (
        "INSERT INTO provider_sync.provider_datasets\n"
        "    (provider_dataset_id, provider, dataset_key)\n"
        "OVERRIDING SYSTEM VALUE\n"
        "VALUES (73, 'python-krforest-api', 'krforest_wildfire_risk_forecast')\n"
        "ON CONFLICT (provider_dataset_id) DO NOTHING;\n"
    )
    assert _OVERRIDING_IDENTITY.search(sample) is not None
    assert _CATALOG_INSERT.search(sample) is not None
    assert _LEADING_INTEGER_ROW.search(sample) is not None

    fixed = (
        "INSERT INTO provider_sync.provider_dataset_operations\n"
        "    (provider_dataset_id, operation_key)\n"
        "SELECT dataset.provider_dataset_id, declared.operation_key\n"
        "FROM (VALUES ('krforest_wildfire_risk_forecast', 'job')) AS declared\n"
        "JOIN provider_sync.provider_datasets AS dataset\n"
        "  ON dataset.dataset_key = declared.dataset_key;\n"
    )
    assert _OVERRIDING_IDENTITY.search(fixed) is None
    assert _LEADING_INTEGER_ROW.search(fixed) is None
