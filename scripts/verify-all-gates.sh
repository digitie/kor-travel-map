#!/usr/bin/env bash
# CI가 실제로 돌리는 게이트를 **전부** 한 번에 돌린다.
#
# 존재 이유: 2026-08-08에 같은 실수를 세 번 반복했다 — 변경 범위보다 좁은 집합만
# 검증하고 "green"이라 선언했다. (1) 파이썬만 돌리고 프론트를 안 봄, (2) 프론트
# `tsc --noEmit`만 돌리고 CI가 실제로 쓰는 `type-check`(tsc 두 번)의 절반을 빠뜨림,
# (3) 바뀐 헬퍼를 호출하는 다른 테스트 파일과 파생 산출물을 안 돌림. 세 번째는
# 그 실수를 사과하는 커밋 안에서 다시 났다.
#
# 그래서 "무엇을 돌릴지"를 매번 판단하지 않는다. 이 스크립트를 돌린다.
#
# 사용:  bash scripts/verify-all-gates.sh [worktree-절대경로]
# 기본값은 이 스크립트가 있는 저장소 루트.

set -uo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# 세 형태를 모두 받는다: `F:\dev\x`(Windows), `/f/dev/x`(Git Bash), `/mnt/f/dev/x`(WSL).
# sed로 백슬래시를 다루면 셸 인용 층이 겹쳐 깨진다 — 파라미터 확장을 쓴다.
WSL_ROOT="$(printf '%s' "$ROOT" | tr '\\' '/')"
case "$WSL_ROOT" in
  /mnt/*) ;;
  [A-Za-z]:/*)
    drive="${WSL_ROOT%%:*}"
    WSL_ROOT="/mnt/$(printf '%s' "$drive" | tr 'A-Z' 'a-z')${WSL_ROOT#*:}"
    ;;
  /?/*) WSL_ROOT="/mnt${WSL_ROOT}" ;;
esac
IMAGE="${KTM_BATTERY_IMAGE:-ktm-battery:t37}"
FAILED=()

run_gate() {
  local name="$1"; shift
  echo "───── $name"
  if "$@"; then
    echo "  OK"
  else
    echo "  FAIL"
    FAILED+=("$name")
  fi
}

py() {
  MSYS_NO_PATHCONV=1 wsl -e docker run --rm --network host \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$WSL_ROOT:/src" -e TESTCONTAINERS_RYUK_DISABLED=true "$IMAGE" \
    sh -c "cd /repo && rm -rf src tests packages contracts alembic \
      && cp -r /src/src /src/tests /src/packages /src/contracts /src/alembic . \
      && cp /src/alembic.ini . 2>/dev/null; $1"
}

front() {
  MSYS_NO_PATHCONV=1 wsl -e bash -lc \
    "cd $WSL_ROOT/packages/kor-travel-map-admin/frontend && $1"
}

run_gate "ruff"        py 'python -m ruff check src/ tests/ packages/'
run_gate "mypy core"   py 'python -m mypy --strict -p kortravelmap'
run_gate "mypy api"    py 'python -m mypy --strict -p kortravelmap.api'
run_gate "mypy dagster" py 'python -m mypy --strict -p kortravelmap.dagster'
run_gate "lint-imports" py 'python -m lint_imports 2>/dev/null || lint-imports'
run_gate "openapi drift" py 'python packages/kor-travel-map-api/scripts/export_openapi.py --profile all --check'
# 파이프를 걸면 안 된다. 컨테이너 안 `sh`에는 pipefail이 없어 exit code가 마지막
# 명령(`tail`)의 것이 되고, pytest가 몇 개를 실패시키든 이 게이트는 늘 통과한다 —
# 이 스크립트를 만든 이유(거짓 green)를 스크립트가 그대로 재현하게 된다.
# 출력을 파일로 받고 exit code는 pytest 것을 그대로 쓴다.
run_gate "pytest (전체 3개 루트)" py \
  'timeout 3000 python -m pytest -q -p no:randomly --tb=short -rf tests/ packages/kor-travel-map-api/tests/ packages/kor-travel-map-dagster/tests/ > /tmp/pytest.log 2>&1; rc=$?; tail -30 /tmp/pytest.log; exit $rc'

# 프론트 게이트 — 파이썬 컨테이너 하네스는 이 셋을 **구조적으로 못 본다**.
run_gate "frontend gen:types:check" front \
  '../../../node_modules/.bin/openapi-typescript ../../kor-travel-map-api/openapi.json -o src/api/types.ts --check'
run_gate "frontend tsc (app)" front '../../../node_modules/.bin/tsc --noEmit'
run_gate "frontend tsc (e2e)" front '../../../node_modules/.bin/tsc -p e2e/tsconfig.json --noEmit'

echo
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "모든 게이트 통과"
  exit 0
fi
echo "실패한 게이트 ${#FAILED[@]}개:"
printf '  - %s\n' "${FAILED[@]}"
exit 1
