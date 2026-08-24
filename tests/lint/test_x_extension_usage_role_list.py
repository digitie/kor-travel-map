"""`x_extension` USAGE를 받는 역할 목록이 **세 곳에서 일치하는지** 본다.

같은 목록이 세 파일에 각자 적혀 있다:

1. `docker/postgres-role-bootstrap.sh` — **정본.** 실제 배포가 GRANT를 거는 곳.
2. `tests/integration/_application_300_bootstrap.py` — 통합 테스트용 거울.
3. `alembic/versions/300_schema_baseline.py` — baseline이 "이 역할들이 USAGE를
   갖고 있는가"를 검사하는 전제 조건.

(2)의 주석이 이미 위험을 적어 뒀다 — "정본은 bootstrap.sh이고 여기는 그 거울이다,
어긋나면 **통합 테스트만 통과하고 실제 배포가 깨지는** 상태가 만들어진다." (3)이
어긋나면 반대로 배포는 되는데 baseline이 이유 없이 거부한다.

이 축이 실제로 샌 적이 있다. squash baseline은 세 스키마만 재현하는데 체인에서는
`0095`가 주던 `x_extension` USAGE가 빠져, `ktm_feature_runtime`이 PostGIS를 통째로
잃고도 카탈로그 비교는 "2486행 일치"로 초록이었다(2026-08-14). 목록을 세 번 적는 한
그 종류의 사고는 다시 난다 — 그래서 **복사본을 없애는 대신 어긋남을 실패로 만든다.**

## 이 가드가 못 하는 것

**세 곳이 함께 틀리면 통과한다.** 여기서 보는 것은 일치이지 내용의 정당성이 아니다.
이 테스트를 만들며 실제로 겪었다 — 변이 실험이 세 파일을 모두 바꿔 놓은 채 남았는데,
셋이 서로 같으니 초록이었다. 그러니 "역할을 하나 빼도 된다"는 판단은 이 테스트가
아니라 `300_schema_baseline`의 런타임 전제 검사와 실제 배포가 막는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]

_BOOTSTRAP_SH = _ROOT / "docker" / "postgres-role-bootstrap.sh"
_TEST_BOOTSTRAP = _ROOT / "tests" / "integration" / "_application_300_bootstrap.py"
_BASELINE = _ROOT / "alembic" / "versions" / "300_schema_baseline.py"

#: 역할 이름 하나. 목록 추출 결과를 이 모양으로만 받는다 — 정규식이 빗나가 엉뚱한
#: 토큰을 주워도 여기서 걸린다.
_ROLE = re.compile(r"^ktm_[a-z_]+$")


def _roles(source: str, where: str) -> frozenset[str]:
    names = {token.strip() for token in source.replace("\n", " ").split(",")}
    names = {name for name in names if name}
    bad = sorted(name for name in names if not _ROLE.match(name))
    assert not bad, f"{where}: 역할 이름이 아닌 토큰을 주웠다 — 추출기를 고쳐라: {bad}"
    return frozenset(names)


def _from_bootstrap_sh() -> frozenset[str]:
    text = _BOOTSTRAP_SH.read_text(encoding="utf-8")
    match = re.search(
        r"GRANT\s+USAGE\s+ON\s+SCHEMA\s+x_extension\s+TO\s+([^;]+);", text, re.IGNORECASE
    )
    assert match is not None, (
        f"{_BOOTSTRAP_SH.name}에서 `GRANT USAGE ON SCHEMA x_extension TO …;`를 찾지 못했다 —"
        " 정본이 옮겨졌다면 이 추출기도 함께 옮겨라"
    )
    return _roles(match.group(1), _BOOTSTRAP_SH.name)


def _from_test_bootstrap() -> frozenset[str]:
    text = _TEST_BOOTSTRAP.read_text(encoding="utf-8")
    # 파이썬 인접 문자열 리터럴로 쪼개져 있다: `"GRANT … x_extension " "TO a, b"`.
    joined = re.sub(r'"\s*\n?\s*"', "", text)
    match = re.search(r"GRANT USAGE ON SCHEMA x_extension TO ([^\"]+)", joined)
    assert match is not None, (
        f"{_TEST_BOOTSTRAP.name}에서 x_extension USAGE GRANT를 찾지 못했다"
    )
    return _roles(match.group(1), _TEST_BOOTSTRAP.name)


def _from_baseline() -> frozenset[str]:
    text = _BASELINE.read_text(encoding="utf-8")
    # `WITH expected(role_name, should_have_usage) AS (VALUES ...)` 구간의 true role만
    # 읽는다. false row까지 섞으면 grant 대상과 아닌 역할을 구별하지 못한다.
    match = re.search(
        r"WITH expected\(role_name, should_have_usage\) AS \(\s*VALUES(.*?)\)\s*\n"
        r"\s*SELECT 1\s*\n\s*FROM expected",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        f"{_BASELINE.name}에서 x_extension USAGE 전제 검사의 VALUES 목록을 찾지 못했다"
    )
    literals = re.findall(r"\('([a-z_]+)',\s*true\)", match.group(1))
    assert literals, f"{_BASELINE.name}: VALUES 구간에서 역할 리터럴을 하나도 못 찾았다"
    return _roles(",".join(literals), _BASELINE.name)


def test_all_three_sites_declare_the_same_roles() -> None:
    """세 목록이 같아야 한다. 다르면 어느 한쪽만 초록인 상태가 만들어진다."""

    sh = _from_bootstrap_sh()
    mirror = _from_test_bootstrap()
    baseline = _from_baseline()

    assert sh, "정본 목록이 비었다"
    assert sh == mirror, (
        "배포 bootstrap과 통합 테스트 거울의 x_extension USAGE 대상이 다르다 —"
        " 통합 테스트만 통과하고 실제 배포가 깨지는 상태다.\n"
        f"  {_BOOTSTRAP_SH.name}: {sorted(sh)}\n"
        f"  {_TEST_BOOTSTRAP.name}: {sorted(mirror)}"
    )
    assert sh == baseline, (
        "배포 bootstrap과 300 baseline의 전제 검사 대상이 다르다 —"
        " 배포는 되는데 baseline이 이유 없이 거부하거나, 반대로 결손을 못 본다.\n"
        f"  {_BOOTSTRAP_SH.name}: {sorted(sh)}\n"
        f"  {_BASELINE.name}: {sorted(baseline)}"
    )
