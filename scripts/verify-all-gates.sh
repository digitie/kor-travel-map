#!/usr/bin/env bash
# CI의 **차단 스텝을 1:1로 미러링**한다.
#
# 존재 이유: 2026-08-08에 같은 실수를 네 번 반복했다 — 변경 범위보다 좁은 집합만
# 검증하고 "green"이라 선언했다. (1) 파이썬만 돌리고 프론트를 안 봄, (2) 프론트
# `tsc --noEmit`만 돌리고 CI가 쓰는 `type-check`(tsc 두 번)의 절반을 빠뜨림,
# (3) 바뀐 헬퍼를 호출하는 다른 테스트 파일과 파생 산출물을 안 돌림, (4) 이 파일의
# 첫 판이 CI 차단 스텝 22개 중 10개만 돌리면서 상단에 "전부 돌린다"고 적었다 —
# 그 사각에서 branch-caused ESLint 실패가 실제로 나왔다.
#
# 그래서 목록을 **추측하지 않는다.** 아래는 `.github/workflows/{ci,lint,openapi,
# frontend}.yml`의 `run:` 스텝을 그대로 옮긴 것이다. 워크플로가 바뀌면 이 파일도
# 같이 바꾼다 — `tests/unit/test_gate_script_mirrors_ci.py`가 그 누락을 검사한다.
#
# **의도적으로 제외한 것**(CI에서도 안 돈다):
#   - `lint.yml` `ruff format --check` — `if: false`. 이 저장소는 자동 format을
#     쓰지 않는다(286 파일이 재포맷 대상). 켜지면 여기에도 넣어야 한다.
#
# **여기서 재현 불가한 것**(로컬 하네스의 한계 — 반드시 인지하고 있어야 한다):
#   - Python 3.11/3.12 매트릭스: 컨테이너는 3.13 하나다.
#
# coverage는 재현한다 — 아래 api/dagster 게이트가 CI와 같은 `--cov-fail-under`를
# 건다. (통합 job의 합산 `fail_under=80`은 `pyproject.toml`이 들고 있어
# integration 게이트가 그대로 적용받는다.)
#
# 사용:  bash scripts/verify-all-gates.sh [worktree-절대경로]

set -uo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# 세 형태를 모두 받는다: `F:\dev\x`(Windows), `/f/dev/x`(Git Bash), `/mnt/f/dev/x`(WSL).
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
NPM="npx --yes npm@12.0.1"
ADMIN="packages/kor-travel-map-admin/frontend"
FAILED=()

run_gate() {
  local name="$1"; shift
  printf '%s\n' "--- $name"
  if "$@"; then
    echo "  OK"
  else
    echo "  FAIL"
    FAILED+=("$name")
  fi
}

# 파이썬 게이트는 컨테이너 안에서 돈다. **파이프를 걸지 마라** — 컨테이너 `sh`에는
# pipefail이 없어 exit code가 마지막 명령의 것이 되고, 게이트가 늘 통과한다.
py() {
  MSYS_NO_PATHCONV=1 wsl -e docker run --rm --network host \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$WSL_ROOT:/src" -e TESTCONTAINERS_RYUK_DISABLED=true "$IMAGE" \
    sh -c "cd /repo && rm -rf src tests packages contracts alembic scripts .github \
      && cp -r /src/src /src/tests /src/packages /src/contracts /src/alembic \
            /src/scripts /src/.github . \
      && cp /src/alembic.ini . 2>/dev/null; $1"
}

# `scripts/`와 `.github/`는 위에서 복사한다. 안 하면 test_gate_script_mirrors_ci가
# 이미지의 낡은 스크립트/워크플로를 읽어, 방금 고쳐도 옛 내용으로 판정한다
# (실제로 한 번 그렇게 실패했다).
#
# 반면 루트 **파일**(package.json / package-lock.json / pyproject.toml /
# docker-compose*.yml / .env.example)은 위 복사에
# 포함되지 않아 **이미지에 구워진 사본**이 쓰인다. 그 파일을 읽는 테스트는 로컬에서
# false-pass/false-fail이 난다 — 루트 파일을 고쳤다면 이미지를 다시 빌드하라.

repo() { MSYS_NO_PATHCONV=1 wsl -e bash -lc "cd $WSL_ROOT && $1"; }

# git이 필요한 게이트는 Git Bash(Windows) 쪽에서 돈다 — 위 주석 참조.
host_py() { ( cd "$ROOT" && eval "$1" ); }

echo "===== lint.yml"
# 이 스크립트는 `git ls-files`를 쓴다. 워크트리의 `.git`이 Windows 경로를 담고 있어
# WSL/컨테이너에서는 "not a git repository"로 죽는다 — Git Bash 쪽에서 돌려야 한다.
run_gate "check_prod_redaction" host_py 'python scripts/check_prod_redaction.py' 
run_gate "ruff check (CI 경로)" py 'python -m ruff check src tests packages/kor-travel-map-api/src packages/kor-travel-map-api/tests packages/kor-travel-map-dagster/src packages/kor-travel-map-dagster/tests'
run_gate "mypy core"    py 'python -m mypy --strict -p kortravelmap'
run_gate "mypy api"     py 'python -m mypy --strict -p kortravelmap.api'
run_gate "mypy dagster" py 'python -m mypy --strict -p kortravelmap.dagster'
run_gate "import-linter" py 'python -c "from importlinter.cli import lint_imports_command; lint_imports_command.main([])"'

echo "===== openapi.yml"
run_gate "OpenAPI drift" py 'python packages/kor-travel-map-api/scripts/export_openapi.py --profile all --check'

echo "===== ci.yml"
run_gate "pytest unit+lint" py \
  'timeout 1800 python -m pytest tests/unit tests/lint -q > /tmp/g1.log 2>&1; rc=$?; tail -20 /tmp/g1.log; exit $rc'
run_gate "pytest api" py \
  'timeout 1800 python -m pytest packages/kor-travel-map-api/tests/ -q --cov=packages/kor-travel-map-api/src/kortravelmap/api --cov-report=term-missing --cov-fail-under=70 > /tmp/g2.log 2>&1; rc=$?; tail -20 /tmp/g2.log; exit $rc'
run_gate "pytest dagster" py \
  'timeout 1800 python -m pytest packages/kor-travel-map-dagster/tests/ -q --cov=packages/kor-travel-map-dagster/src/kortravelmap/dagster --cov-report=term-missing --cov-fail-under=80 > /tmp/g3.log 2>&1; rc=$?; tail -20 /tmp/g3.log; exit $rc'
run_gate "pytest integration" py \
  'timeout 3000 python -m pytest tests/integration -q > /tmp/g4.log 2>&1; rc=$?; tail -25 /tmp/g4.log; exit $rc'

echo "===== frontend.yml"
run_gate "audit:high"              repo "$NPM run audit:high"
run_gate "audit:dev"               repo "$NPM run audit:dev"
run_gate "verify:npm-tree"         repo "$NPM run verify:npm-tree"
run_gate "verify:frontend-eslint"  repo "$NPM run verify:frontend-eslint"
run_gate "admin eslint (0 warnings)" repo "$NPM -w $ADMIN run lint"
run_gate "verify:react-doctor-config" repo "$NPM run verify:react-doctor-config"
run_gate "admin react-doctor"      repo "$NPM -w $ADMIN run doctor"
run_gate "verify:next-sharp"       repo "$NPM run verify:next-sharp"
run_gate "admin gen:types:check"   repo "$NPM -w $ADMIN run gen:types:check"
run_gate "user-client gen:types:check" repo "$NPM -w packages/kor-travel-map-user-client run gen:types:check"
run_gate "user-client type-check"  repo "$NPM -w packages/kor-travel-map-user-client run type-check"
# admin `type-check`는 tsc를 **두 번** 돌린다(app + e2e). 하나만 돌리면 절반이다.
run_gate "admin type-check (app+e2e)" repo "$NPM -w $ADMIN run type-check"
# CI는 이 스텝에 NEXT_PUBLIC_* 를 넣는다(frontend.yml). build-time inline이라 실
# 호출은 없고 임의 값이면 된다 — 안 넘기면 prerender가 "required in production"으로
# 죽어 코드 결함처럼 보인다.
run_gate "admin next build" repo   "NEXT_PUBLIC_KOR_TRAVEL_MAP_API=http://127.0.0.1:8087    NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL=http://127.0.0.1:12302    NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL=http://127.0.0.1:12201    $NPM -w $ADMIN run build"

echo
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "미러링한 CI 차단 스텝을 모두 통과했다."
  echo "주의: Python 3.11/3.12 매트릭스는 로컬에서 재현하지 않는다(컨테이너는 3.13)."
  exit 0
fi
echo "실패한 게이트 ${#FAILED[@]}개:"
printf '  - %s\n' "${FAILED[@]}"
exit 1
