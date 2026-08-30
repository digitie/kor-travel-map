"""application head가 **한 곳**에서만 정해지는지.

배포 계약은 "설치된 DB가 정확히 기대한 revision인가"를 네 지점에서 확인한다 — static
contract, fresh installer, fresh finalize, final permit. 그 엄격함은 옳다. 문제는
기대값이 파일마다 하드코딩된 리터럴이라 **여섯 사본이 일치한다는 것을 아무것도
강제하지 않았다**는 점이었다.

실제로 child migration을 하나 더하자 fresh installer가
``installed active Alembic graph head is not exactly 300``으로 거절했다. 스키마를 못
바꾸게 만든 것은 배포 안전성이 아니라 **리터럴의 산개**였다.

이 테스트는 그 상태로 되돌아가지 못하게 한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kortravelmap.infra.application_schema_head import (
    BASELINE_ROOT_REVISION,
    application_schema_head,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_DIR = REPO_ROOT / "docker"

_HEAD_CONSUMERS = (
    "application-schema-contract.py",
    "application-schema-fresh-300.py",
    "application-schema-fresh-finalize.py",
    "application-schema-final-permit.py",
)
"""현재 head를 기대값으로 쓰는 배포 executable.

``transition-application-schema-0236-to-300.py``는 여기 없다 — 그것이 stamp하는 `300`은
"현재 head"가 아니라 **baseline root**이고, migration이 쌓여도 바뀌지 않는다.
"""

_HEAD_LITERAL = re.compile(r'(?<![0-9])"300"(?![0-9])')


def test_head_consumers_do_not_hardcode_the_revision() -> None:
    """head를 쓰는 executable은 리터럴 대신 파생값을 써야 한다."""
    offenders: list[str] = []
    for name in _HEAD_CONSUMERS:
        path = DOCKER_DIR / name
        assert path.exists(), f"배포 executable이 사라졌다: {name}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if _HEAD_LITERAL.search(line):
                offenders.append(f"{name}:{number}: {line.strip()[:80]}")

    assert not offenders, (
        "application head를 리터럴로 박았다 — "
        "`kortravelmap.infra.application_schema_head.application_schema_head()`를 쓸 것:\n  "
        + "\n  ".join(offenders)
    )


def test_head_consumers_import_the_single_source() -> None:
    """리터럴이 없다는 것만으로는 부족하다 — 실제로 정본을 읽어야 한다."""
    missing = [
        name
        for name in _HEAD_CONSUMERS
        if "application_schema_head" not in (DOCKER_DIR / name).read_text(encoding="utf-8")
    ]

    assert not missing, f"head 정본을 import하지 않는 배포 executable: {missing}"


def test_derived_head_matches_the_alembic_script_directory() -> None:
    """파생 head가 alembic이 실제로 계산하는 head와 같아야 한다.

    graph JSON은 생성물이다. 그것과 ``alembic/versions/``가 어긋나면 배포는 graph를
    믿고 alembic은 파일을 믿어, 설치본이 기대값과 달라진다.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    # `alembic.ini`를 읽지 않는다 — configparser가 로캘 인코딩으로 열어 비ASCII 주석에서
    # 깨진다. 이 테스트가 보려는 것은 ini가 아니라 `alembic/versions/`의 graph다.
    config = Config()
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    heads = tuple(ScriptDirectory.from_config(config).get_heads())

    assert heads == (application_schema_head(),), (
        "파생 head와 alembic head가 다르다 — "
        "`python scripts/generate_application_migration_graph.py --write`로 재생성할 것"
    )


def test_baseline_root_stays_pinned() -> None:
    """baseline root는 역사적 좌표다 — head와 달리 움직이지 않는다."""
    assert BASELINE_ROOT_REVISION == "300"


def test_handoff_stamps_the_baseline_root_not_the_head() -> None:
    """`0236 → 300` handoff는 baseline root로 stamp하고 head로 결박하지 않는다.

    head로 결박하면 migration을 하나 더하는 순간 이 다리가 막힌다. 실제로 그랬다.
    """
    import importlib.util

    path = DOCKER_DIR / "transition-application-schema-0236-to-300.py"
    source = path.read_text(encoding="utf-8")

    assert "get_heads()) != (_DESTINATION_HEAD,)" not in source, (
        "handoff가 graph head로 결박돼 있다 — stamp 목적지가 graph에 있는지만 보아야 한다"
    )

    # 목적지는 리터럴이다(retired revision 스캔이 정적으로 해소해야 하므로).
    # 그 리터럴이 공유 상수와 같은지는 여기서 묶는다.
    spec = importlib.util.spec_from_file_location("_handoff_probe", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._DESTINATION_HEAD == BASELINE_ROOT_REVISION


@pytest.mark.parametrize("name", _HEAD_CONSUMERS)
def test_head_consumer_module_imports_cleanly(name: str) -> None:
    """배포 executable이 import 시점에 head를 확정할 수 있어야 한다.

    graph가 깨졌거나 분기됐으면 여기서 fail-close한다 — 배포 도중이 아니라.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"_head_probe_{name}", DOCKER_DIR / name)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    declared = getattr(module, "_HEAD", None) or getattr(module, "_DESTINATION_HEAD", None)
    assert declared == application_schema_head()


# -- alembic/env.py --------------------------------------------------------
#
# 이 파일은 `_HEAD_CONSUMERS`(docker/)에 없어서 위 스캔이 훑지 않는다. 실제로 그
# 사각지대에서 두 가지가 놓쳤다 — handoff가 graph head로 결박된 채 남아 있었고, fresh
# 설치 facet 검증이 head가 바뀌면 **조용히 꺼지는** 조건을 달고 있었다.

_ENV = Path(__file__).resolve().parents[2] / "alembic" / "env.py"


def test_env_baseline_constant_matches_the_shared_root() -> None:
    """`env.py`의 baseline 상수가 공유 정본과 같아야 한다.

    리터럴로 두는 것 자체는 문제가 아니다(retired revision 스캔이 정적으로 해소해야
    한다). 사본이 정본과 **어긋나는 것**이 문제다.
    """
    source = _ENV.read_text(encoding="utf-8")

    assert f'_BASELINE_300_REVISION = "{BASELINE_ROOT_REVISION}"' in source


def test_env_handoff_is_not_bound_to_the_graph_head() -> None:
    """handoff는 stamp 목적지가 graph에 있는지만 보아야 한다.

    `docker/transition-...`은 고쳤는데 `env.py`가 같은 결박을 들고 남아 있었다.
    """
    source = _ENV.read_text(encoding="utf-8")

    assert "script.get_heads()) != (_BASELINE_300_REVISION,)" not in source, (
        "env.py handoff가 graph head로 결박돼 있다 — child migration 하나면 막힌다"
    )


def test_fresh_install_facet_verification_cannot_be_silently_skipped() -> None:
    """**이 게이트의 본체.**

    종전 조건은 `raw_heads_before == () and raw_heads_after == (_BASELINE_300_REVISION,)`
    이었다. child migration이 생기면 뒤 절이 영구히 False가 되어
    `_verify_fresh_300_destination_facet`이 예외도 로그도 없이 **호출되지 않는다.**
    배포 executable 경로를 타지 않는 모든 설치가 facet 검증 없이 통과하게 된다.

    조용히 꺼지는 대신 시끄럽게 거절해야 한다.
    """
    source = _ENV.read_text(encoding="utf-8")

    assert (
        "if raw_heads_before == () and raw_heads_after == (_BASELINE_300_REVISION,):"
        not in source
    ), (
        "fresh 설치 facet 검증이 head 일치를 조건에 달고 있다 — head가 움직이면 "
        "검증이 조용히 사라진다. 도달점이 baseline root가 아니면 raise할 것"
    )
    assert "if raw_heads_before == ():" in source, (
        "fresh 설치 판정은 `raw_heads_before == ()` 하나여야 한다"
    )
    assert "_verify_fresh_300_destination_facet(connection)" in source
