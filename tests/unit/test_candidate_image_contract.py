"""candidate image 위생 — legacy migration 코드·host fixture가 섞여 들어가지 않는지.

원래 이름은 `test_h35_image_contract.py`였지만 실체는 H35와 무관한 **image 위생 가드**다.
H35 helper 세트가 T-VN-C01(2026-08-18)에서 퇴역하면서 이름과 내용을 실제에 맞췄다.

빠진 것과 그 이유:

- `test_main_wheel_excludes_historical_h35_execution_modules` — `setup.py`의 build 훅이
  wheel에서 H35 모듈을 빼는지 보던 테스트다. 모듈도 훅도 사라져 **뺄 대상이 없다.**
  (부수로 `uv` 의존이 사라진다.)
- `test_api_and_dagster_builders_use_the_h35_excluding_build_hook` — `COPY … setup.py …`를
  단언했는데 `setup.py`가 없어졌다.
- `rm -f src/kortravelmap/cli/_h35_*.py` 단언 — Dockerfile의 그 행이 함께 사라졌다.

대신 **되살아나지 않는지**를 지키는 가드를 넣었다. 지우기만 하고 검사기를 안 두면
같은 파일이 조용히 돌아온다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def test_candidate_image_excludes_legacy_migration_code() -> None:
    dockerfile = (_ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")

    assert "ARG KOR_TRAVEL_MAP_GIT_COMMIT=development" in dockerfile
    assert 'LABEL org.opencontainers.image.revision="$KOR_TRAVEL_MAP_GIT_COMMIT"' in dockerfile
    assert 'KOR_TRAVEL_MAP_IMAGE_REVISION="$KOR_TRAVEL_MAP_GIT_COMMIT"' in dockerfile
    # alembic을 통째로 COPY하면 legacy_versions까지 이미지에 들어간다.
    assert "COPY alembic ./alembic" not in dockerfile
    assert "COPY alembic/legacy_versions" not in dockerfile
    assert "COPY alembic/versions ./alembic/versions" in dockerfile
    assert (
        "COPY --chown=root:root resources/curations ./resources/curations" in dockerfile
    )
    assert "find /app/resources/curations -type d -exec chmod 0555" in dockerfile
    assert "find /app/resources/curations -type f -exec chmod 0444" in dockerfile
    assert "! mv /app/resources/curations/manifest.json" in dockerfile
    assert "USER appuser" in dockerfile


def test_image_contract_has_no_host_fixture_copy() -> None:
    """호스트 부산물이 이미지로 새지 않는지.

    `.env`·dump·로컬 노트는 비밀이나 대용량을 담는다. Dockerfile이 그것을 COPY하면
    이미지 배포가 곧 유출이다.
    """
    dockerfile = (_ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")

    assert "*.dump" not in dockerfile
    assert "*.local.md" not in dockerfile
    assert ".env" not in dockerfile
    assert "/home/" not in dockerfile


# T-VN-C01(2026-08-18)에서 지운 것들. 지우기만 하고 검사기를 안 두면 조용히 돌아온다.
_RETIRED_H35_PATHS = (
    "scripts/h35",
    "setup.py",
    "src/kortravelmap/cli/h35_cutover.py",
    "src/kortravelmap/cli/_h35_cache_target.py",
    "src/kortravelmap/cli/_h35_catalog.py",
    "src/kortravelmap/cli/_h35_contract.py",
    "src/kortravelmap/cli/_h35_csv5.py",
    "src/kortravelmap/cli/_h35_schema.py",
    "src/kortravelmap/cli/_h35_schema_version.py",
)


@pytest.mark.parametrize("relative", _RETIRED_H35_PATHS)
def test_retired_h35_helpers_stay_retired(relative: str) -> None:
    """퇴역한 H35 helper가 저장소로 돌아오지 않았는지.

    `h35-db-identity-v1` 계산만 살아 있고 그것은
    `src/kortravelmap/core/database_identity.py`에 있다 — `contracts/vnext/
    recovery-preflight-v1.json`이 요구하는 값이라 정의가 사라지면 안 됐다.
    """
    assert not (_ROOT / relative).exists(), (
        f"{relative}는 T-VN-C01에서 퇴역했다. 되살릴 이유가 생겼다면 "
        "docs/tasks-done.md의 퇴역 근거부터 뒤집어라."
    )


def test_database_identity_survived_the_retirement() -> None:
    """계약이 요구하는 실행 정의는 남아 있어야 한다.

    위 가드만 있으면 "다 지웠다"로 초록인데 계약이 참조하는 계산이 사라진 상태도
    통과한다. 살아야 할 쪽도 같이 고정한다.
    """
    from kortravelmap.core.database_identity import (
        DATABASE_IDENTITY_GOLDEN_VECTOR,
        compute_database_identity,
    )

    assert compute_database_identity(
        transaction_id=str(DATABASE_IDENTITY_GOLDEN_VECTOR["transaction_id"]),
        database=str(DATABASE_IDENTITY_GOLDEN_VECTOR["database"]),
        system_identifier=str(DATABASE_IDENTITY_GOLDEN_VECTOR["system_identifier"]),
    ) == DATABASE_IDENTITY_GOLDEN_VECTOR["digest"]
