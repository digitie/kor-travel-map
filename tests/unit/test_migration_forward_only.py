"""forward-only migration의 ``downgrade()``가 실제로 거부하는지 검사한다.

이 게이트가 없어서 실제로 사고가 났다. 0092의 첫 판은 module docstring에 "이
revision은 되돌릴 수 있다 — 제약/함수 정의만 건드리기 때문"이라 적고 UNIQUE를
4열에서 3열로 **좁히는** ``downgrade()``를 실었다. 좁히기는 정의만 건드려도 데이터에
의존하고, 실패를 유발하는 상태(형제 operation이 같은 checksum을 갖는 행)를 만드는
것이 하필 같은 revision의 ``upgrade()``다. 저장소에는 downgrade 경로를 도는 테스트가
한 건도 없어서 그 진술이 거짓이라는 사실이 적대 검증 전까지 드러나지 않았다.

`300_schema_baseline`은 final schema를 새 DB에만 적재하는 single root다. 과거 active
lineage는 retired archive이며, downgrade가 허용되면 실제 운영 DB가 더는 존재하지 않는
revision을 가리킬 수 있다. 따라서 되돌릴 수 없다면 **되돌리려는 시도가 조용히 성공한
척해서는 안 된다**.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_ALEMBIC = Path(__file__).resolve().parents[2] / "alembic"
VERSIONS = _ALEMBIC / "versions"
_SEARCH_ROOTS = (VERSIONS,)

# 되돌릴 수 없다고 스스로 선언한 revision. 목록을 박아 두는 이유는, 선언 문자열만
# 검사하면 선언을 지우는 것으로 게이트를 통과할 수 있기 때문이다.
FORWARD_ONLY_REVISIONS = (
    "300_schema_baseline",
)


def _path_for(stem: str) -> Path:
    path = VERSIONS / f"{stem}.py"
    assert path.exists(), f"{stem}.py를 active alembic/versions에서 찾지 못했다"
    return path


def _load(stem: str) -> ModuleType:
    path = _path_for(stem)
    spec = importlib.util.spec_from_file_location(f"_forward_only_{stem}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("stem", FORWARD_ONLY_REVISIONS)
def test_forward_only_revision_refuses_to_downgrade(stem: str) -> None:
    module = _load(stem)

    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()


def test_every_revision_declaring_forward_only_actually_refuses() -> None:
    """선언과 구현이 갈리지 않게 한다.

    ``FORWARD_ONLY_REVISIONS``에 없더라도 본문에 forward-only를 진술한 revision이
    있으면 그것도 같은 규칙을 지켜야 한다. 반대 방향(목록에 있는데 선언이 없는 것)은
    위 parametrize가 잡는다.
    """

    declared = sorted(
        path.stem
        for root in _SEARCH_ROOTS
        for path in root.glob("[0-9]*.py")
        if "forward-only" in path.read_text(encoding="utf-8")
    )

    assert set(FORWARD_ONLY_REVISIONS) <= set(declared)

    for stem in declared:
        module = _load(stem)
        with pytest.raises(RuntimeError, match="forward-only"):
            module.downgrade()


def test_forward_only_downgrade_body_carries_no_ddl() -> None:
    """``downgrade()``가 raise 앞에 DDL을 실어 두지 않았는지 본다.

    raise만 있으면 본문이 한 줄이다. 앞에 ``op.`` 호출이 끼어 있으면 그 호출은
    실제로 실행된 뒤 raise되므로, "되돌릴 수 없다"는 선언과 달리 스키마가 절반만
    바뀐 상태가 남는다.
    """

    for stem in FORWARD_ONLY_REVISIONS:
        source = _path_for(stem).read_text(encoding="utf-8")
        body = source.split("def downgrade() -> None:", 1)[1]
        assert "op." not in body, f"{stem}: downgrade 본문에 DDL이 있다"
