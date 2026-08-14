"""forward-only migration의 ``downgrade()``가 실제로 거부하는지 검사한다.

이 게이트가 없어서 실제로 사고가 났다. 0092의 첫 판은 module docstring에 "이
revision은 되돌릴 수 있다 — 제약/함수 정의만 건드리기 때문"이라 적고 UNIQUE를
4열에서 3열로 **좁히는** ``downgrade()``를 실었다. 좁히기는 정의만 건드려도 데이터에
의존하고, 실패를 유발하는 상태(형제 operation이 같은 checksum을 갖는 행)를 만드는
것이 하필 같은 revision의 ``upgrade()``다. 저장소에는 downgrade 경로를 도는 테스트가
한 건도 없어서 그 진술이 거짓이라는 사실이 적대 검증 전까지 드러나지 않았다.

0090/0091/0092는 T-VN-33 cutover 3종이다. ADR-088의 재적재 전제(최종 스키마로 fresh
PostGIS 재적재) 위에서만 성립하므로 되돌릴 수 없고, 되돌릴 수 없다면 **되돌리려는
시도가 조용히 성공한 척해서는 안 된다**.
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
# squash(`0200`) 이후 체인은 실행되지 않는 아카이브다(`alembic/legacy_versions/README.md`).
# 그래도 함께 훑는다 — 아카이브는 동결돼 있으니 비용이 0이고, 빼면 "선언과 구현이
# 갈리지 않는다"는 이 파일의 명제가 조용히 절반짜리가 된다.
LEGACY_VERSIONS = _ALEMBIC / "legacy_versions"
_SEARCH_ROOTS = (VERSIONS, LEGACY_VERSIONS)

# 되돌릴 수 없다고 스스로 선언한 revision. 목록을 박아 두는 이유는, 선언 문자열만
# 검사하면 선언을 지우는 것으로 게이트를 통과할 수 있기 때문이다.
FORWARD_ONLY_REVISIONS = (
    "0090_tvn33_constraints",
    "0091_tvn33_cutover_fence",
    "0092_tvn33_offline_cleanup",
    "0200_schema_baseline",
    # bridge도 forward-only다. 목록에 없으면 동적 스캔에만 걸리는데, 이 파일 자신이
    # "선언 문자열만 검사하면 선언을 지우는 것으로 게이트를 통과할 수 있다"고 적어 둔
    # 바로 그 무방비 상태가 된다. 파일 stem으로 적는다 — revision id는 옛 head다.
    "0201_squash_bridge",
)


def _path_for(stem: str) -> Path:
    # 같은 stem이 양쪽에 있으면 **먼저 찾은 쪽을 조용히 검사**하게 된다. squash 이후
    # 그 상태가 실제로 만들어질 수 있어(bridge가 옛 head id를 되살렸다) 모호하면 선다.
    found = [root / f"{stem}.py" for root in _SEARCH_ROOTS if (root / f"{stem}.py").exists()]
    assert found, f"{stem}.py를 versions/ 에도 legacy_versions/ 에도 찾지 못했다"
    assert len(found) == 1, (
        f"{stem}.py가 versions/와 legacy_versions/ 양쪽에 있다 — 어느 쪽을 검사하는지"
        f" 이름만으로는 정해지지 않는다: {[str(path) for path in found]}"
    )
    return found[0]


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
