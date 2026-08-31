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

_BASELINE_ROOT_CHECKPOINT = 'command.upgrade(config, "300")'
"""fresh installer가 봉인된 계약을 대조하려고 baseline root에서 한 번 끊는 자리."""


def test_head_consumers_do_not_hardcode_the_revision() -> None:
    """head를 쓰는 executable은 리터럴 대신 파생값을 써야 한다."""
    offenders: list[str] = []
    for name in _HEAD_CONSUMERS:
        path = DOCKER_DIR / name
        assert path.exists(), f"배포 executable이 사라졌다: {name}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if line.strip() == _BASELINE_ROOT_CHECKPOINT:
                # baseline root **체크포인트**의 목적지다. head가 아니다.
                # 리터럴이어야 하는 이유는
                # `test_active_runnable_paths_never_target_legacy_revision`이
                # upgrade 대상을 정적으로 해소해 retired revision이 아님을 증명하기
                # 때문이다 — 상수로 바꾸면 그 증명이 무력해진다. 값이 실제로 baseline
                # root인지는 `test_the_baseline_root_checkpoint_targets_the_root`가 본다.
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
        "fresh 설치 facet 검증이 최종 head 일치를 조건에 달고 있다 — head가 움직이면 "
        "검증이 조용히 사라진다"
    )

    # 봉인은 `300` step 콜백이 한다. 계약 SQL이 `alembic_version = ARRAY['300']`을
    # 요구하므로 그 순간에만 의미가 있고, alembic이 `update_to_step()`을 콜백보다
    # 먼저 부르므로 version row는 이미 `300`이다.
    assert "on_version_apply=[" in source, (
        "facet 봉인이 step 콜백으로 걸려 있지 않다 — `run_migrations()` 이후에 검증하면 "
        "child migration이 붙는 순간 계약이 어긋난다"
    )
    assert "_verify_fresh_300_destination_facet(connection)" in source

    # 콜백이 돌지 않았는데도 통과하는 자리가 있으면 안 된다.
    assert "and not facet_verified:" in source, (
        "봉인이 실제로 수행됐는지 확인하는 fail-close가 없다 — 조용히 꺼질 자리가 남는다"
    )


# -- head 리터럴이 숨을 수 있는 나머지 배포 자산 -----------------------------
#
# `_HEAD_CONSUMERS`(docker/*.py 4개)와 `alembic/env.py` 밖에도 head를 리터럴로 박은
# 자리가 있었고, 둘 다 **프로덕션을 죽이거나 가드를 조용히 끄는** 종류였다.
#
#   docker/api-entrypoint.sh          — production API가 head!=300이면 기동 실패
#   docker/dagster-storage-migrate.py — application DB 판정 arm이 조용히 False
#
# 스캔 범위를 넓혀 같은 부류가 다시 생기지 못하게 한다.

# 열거는 그 자체가 사각지대였다. `api-entrypoint.sh`/`dagster-storage-migrate.py`를
# 더한 뒤에도 `scripts/run-admin-stack.sh`가 `revisions != [("300",)]`로 자기 DB를
# 거절하고 있었고, 그것을 찾아낸 것은 이 게이트가 아니라 손으로 판 blast-radius
# 조사였다. 그래서 **열거를 버리고 전수로 훑는다.**
#
# 훑는 대상은 `docker/`와 `scripts/`의 모든 executable이다. 면제는 파일 단위로
# **사유와 함께** 선언해야 한다 — 새 파일이 조용히 사각지대에 들어가지 못한다.

SCRIPTS_DIR = REPO_ROOT / "scripts"

_BASELINE_MACHINERY: dict[str, str] = {
    "build-baseline.sh": (
        "baseline 제작기. 정의상 `300` baseline만 만든다 — 다른 head의 baseline은 "
        "재squash라는 별도 결정이다."
    ),
    "create-application-300-fresh-oracle.sh": (
        "`0236 → 300` baseline artifact 검증용 disposable oracle. 검증 대상이 "
        "baseline 그 자체이므로 목적지가 baseline root다."
    ),
    "rehearse-application-300-handoff.sh": (
        "`0236 → 300` handoff 리허설. handoff의 목적지가 baseline root다."
    ),
    "build-application-300-paired-candidate.sh": (
        "paired candidate receipt의 `forbidden_application_raw_revision`은 "
        "'Dagster metadata DB는 application raw revision을 갖지 않는다'는 격리 "
        "선언이며 baseline root를 가리킨다 — head가 아니다."
    ),
    "transition-application-schema-0236-to-300.py": (
        "handoff executable. stamp 목적지가 baseline root다 "
        "(`test_handoff_stamps_the_baseline_root_not_the_head`가 따로 고정한다)."
    ),
    "application-schema-fresh-300.py": (
        "baseline root 도달 시점의 facet 봉인 분기에서 `BASELINE_ROOT_REVISION`을 "
        "비교한다 — 상수를 통한 비교이므로 리터럴이 아니다."
    ),
}
"""head 리터럴 비교가 **정당한** 파일과 그 사유.

사유 없는 면제는 두지 않는다. 여기 이름을 더하는 것은 "이 파일의 `300`은 head가
아니라 baseline root다"라는 주장이고, 그 주장이 틀리면 프로덕션이 죽는다.
"""

_COMPARISON_TOKENS = ("!=", "==", "= ANY", " -eq ", " = ", "= [", "!= [")


def _deploy_assets() -> list[Path]:
    assets = [
        path
        for path in sorted(DOCKER_DIR.iterdir())
        if path.is_file() and path.suffix in {".py", ".sh"}
    ]
    assets += [
        path
        for path in sorted(SCRIPTS_DIR.iterdir())
        if path.is_file() and path.suffix in {".py", ".sh"}
    ]
    return assets


def test_the_exemption_list_has_no_dead_entries() -> None:
    """면제 목록이 실재하는 파일만 담아야 한다.

    죽은 항목이 남으면 "면제됐다"는 착각으로 새 파일이 그 이름을 물려받을 수 있다.
    """
    names = {path.name for path in _deploy_assets()}
    dead = sorted(set(_BASELINE_MACHINERY) - names)

    assert not dead, f"면제 목록에 존재하지 않는 파일이 있다: {dead}"


def test_every_exemption_states_a_reason() -> None:
    """사유 없는 면제를 금지한다."""
    empty = sorted(
        name for name, reason in _BASELINE_MACHINERY.items() if not reason.strip()
    )

    assert not empty, f"사유 없는 면제: {empty}"


def test_no_deploy_asset_pins_the_head_literal() -> None:
    """**이 게이트의 본체 — 전수.**

    `docker/`와 `scripts/`의 모든 executable을 훑는다. baseline root 상수를 통한
    비교는 허용하고, 금지하는 것은 **리터럴 비교**다.
    """
    offenders: list[str] = []
    for path in _deploy_assets():
        if path.name in _BASELINE_MACHINERY:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("#", "--")):
                continue
            if "BASELINE_ROOT_REVISION" in line:
                continue
            if not _HEAD_LITERAL.search(line) and "'300'" not in line:
                continue
            if any(token in line for token in _COMPARISON_TOKENS):
                offenders.append(f"{path.name}:{number}: {stripped[:80]}")

    assert not offenders, (
        "배포 자산이 application head를 리터럴로 비교한다 — head가 움직이면 "
        "프로덕션이 죽거나 가드가 조용히 꺼진다. 정당한 baseline root 비교라면 "
        "`_BASELINE_MACHINERY`에 사유와 함께 선언할 것:\n  " + "\n  ".join(offenders)
    )


def test_the_baseline_root_checkpoint_targets_the_root() -> None:
    """체크포인트 리터럴이 실제로 baseline root인지 본다.

    `test_head_consumers_do_not_hardcode_the_revision`이 이 한 줄을 면제하므로, 그
    면제가 정당한지는 여기서 값으로 확인한다. 면제와 확인을 같은 파일에 두어 한쪽만
    바뀌는 일을 막는다.
    """
    expected = f'command.upgrade(config, "{BASELINE_ROOT_REVISION}")'
    assert expected == _BASELINE_ROOT_CHECKPOINT

    source = (DOCKER_DIR / "application-schema-fresh-300.py").read_text(encoding="utf-8")

    assert _BASELINE_ROOT_CHECKPOINT in source, (
        "fresh installer가 baseline root 체크포인트를 잃었다 — 봉인된 catalog digest는 "
        "`300` 시점만 서술하므로, head까지 한 번에 올리면 대조할 대상이 사라진다"
    )
