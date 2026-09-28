#!/bin/bash
# 새 pinset 한 주기의 D2 입력을 맞춘다 (executor 이미지 빌드 이후 ~ D1 직전).
#
#   repin.sh MAP_SHA40 PINVI_SHA40
#
# 정본은 저장소의 `scripts/n150/repin.sh`다(ADR-102 결정 6). 운영자가 `/root`로 복사해
# 쓴다 — `scripts/n150/README.md`.
#
# ADR-102 이전의 repin은 Manager의 v6 manifest·v8 journal을 `/etc`에 사본으로 뜨고,
# 러너 두 벌을 root 소유 스냅샷으로 설치하고, host attestation을 발행·검증했다. 그
# 두 번째 증명은 걷어냈다 — Manager가 이미 모든 컨테이너 image를 핀된 세대와 대조한다.
# 남은 일은 넷이다(전부 멱등):
#   0. 인자가 핀 원장과 같은지 본다(`ktdctl pin show` — Manager 내부 파일은 읽지 않는다).
#   1. C7 executor 이미지 라벨이 MAP인지 본다.
#   2. /root/.d2-live.env의 비밀이 아닌 두 키를 갱신하고 퇴역한 두 키를 지운다.
#   3. D2 fixture DSN을 실행 중인 Map API 컨테이너의 DSN에서 유도한다(ADR-103).
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: repin.sh MAP_SHA40 PINVI_SHA40" >&2
  exit 2
fi
MAP="$1"
PINVI="$2"
[[ "$MAP" =~ ^[0-9a-f]{40}$ ]] || { echo "MAP revision is not 40-hex" >&2; exit 2; }
[[ "$PINVI" =~ ^[0-9a-f]{40}$ ]] || { echo "PINVI revision is not 40-hex" >&2; exit 2; }
[[ "$(id -u)" == "0" ]] || { echo "must run as root" >&2; exit 2; }

KTDCTL=/opt/kor-travel-docker-manager/backend/.venv/bin/ktdctl
ENV_FILE=/root/.d2-live.env
IMAGE_TAG=kor-travel-map-c7-playwright:local

die() { echo "!! $1" >&2; exit 1; }
say() { printf '\n=== %s ===\n' "$1"; }

say "0. 핀 원장 대조"
PINSHOW="$("$KTDCTL" pin show 2>/dev/null)" || die "ktdctl pin show 실패"
LEDGER_MAP="$(printf '%s\n' "$PINSHOW" | awk '$1=="map"{print $2; exit}')"
LEDGER_PINVI="$(printf '%s\n' "$PINSHOW" | awk '$1=="pinvi"{print $2; exit}')"
[[ "$LEDGER_MAP" == "$MAP" ]] || die "인자 MAP이 핀 원장과 다르다"
[[ "$LEDGER_PINVI" == "$PINVI" ]] || die "인자 PINVI가 핀 원장과 다르다"
echo "  map ${MAP:0:8} / pinvi ${PINVI:0:8}"

say "1. C7 executor 이미지"
current="$(docker image inspect "$IMAGE_TAG" \
  --format '{{index .Config.Labels "io.kortravelmap.c7.repository-commit"}}' 2>/dev/null || true)"
if [[ "$current" != "$MAP" ]]; then
  echo "  현재 라벨=${current:-없음} → 빌드 필요. 아래를 따로 돌려라(10분):"
  echo "    ssh n150 'cd ~/ktm-c7-src && git checkout -q --detach $MAP && sudo systemd-run --unit=c7-execbuild --collect --property=Type=oneshot --property=TimeoutStartSec=2400 --uid=digitie --gid=digitie --working-directory=/home/digitie/ktm-c7-src --setenv=HOME=/home/digitie /home/digitie/ktm-c7-src/scripts/build-c7-playwright-image.sh'"
  exit 3
fi
IMAGE="$(docker image inspect "$IMAGE_TAG" --format '{{.Id}}')"
[[ "$IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]] || die "executor image ID를 읽지 못했다"
echo "  라벨=$MAP  id=${IMAGE:0:19}"

say "2. .d2-live.env 갱신"
# 두 키는 비밀이 아니다(commit SHA와 image ID). 비밀 키는 건드리지 않는다.
# 퇴역한 두 키(v6 manifest·v8 journal 사본 경로)는 러너가 더 읽지 않으므로 지운다.
cp -a "$ENV_FILE" "$ENV_FILE.bak-${MAP:0:8}"
sed -i -E \
  -e "s|^E2E_C7_EXPECTED_GIT_COMMIT=.*|E2E_C7_EXPECTED_GIT_COMMIT=$MAP|" \
  -e "s|^E2E_C7_PLAYWRIGHT_IMAGE=.*|E2E_C7_PLAYWRIGHT_IMAGE=$IMAGE|" \
  -e '/^E2E_C7_(PINNED_RUNTIME_MANIFEST|REBUILD_JOURNAL)=/d' \
  "$ENV_FILE"
# sed의 치환은 키가 없으면 조용히 아무것도 하지 않는다 — 결과를 직접 센다.
[[ "$(grep -c "^E2E_C7_EXPECTED_GIT_COMMIT=$MAP\$" "$ENV_FILE")" == 1 ]] ||
  die "E2E_C7_EXPECTED_GIT_COMMIT가 정확히 한 줄로 갱신되지 않았다"
[[ "$(grep -c "^E2E_C7_PLAYWRIGHT_IMAGE=$IMAGE\$" "$ENV_FILE")" == 1 ]] ||
  die "E2E_C7_PLAYWRIGHT_IMAGE가 정확히 한 줄로 갱신되지 않았다"
grep -E "^E2E_C7_(EXPECTED_GIT_COMMIT|PLAYWRIGHT_IMAGE)=" "$ENV_FILE"

say "3. D2 fixture DSN (Map API 컨테이너에서 유도)"
# fixture DSN은 API 런타임 DSN과 사용자·host:port·DB·비밀번호가 같다(2026-09-28 실측).
# 손으로 적은 사본은 DB가 다른 instance로 옮겨 가면(ADR-103) 조용히 옛 instance를
# 가리킨다. 그래서 매 주기 실행 중인 API 컨테이너의 `KOR_TRAVEL_MAP_PG_DSN`에서 다시
# 유도한다 — instance 이름·port를 여기 적지 않는다. 값은 비밀이다: 출력하지 않고 호스트
# argv에도 싣지 않는다(helper가 `docker inspect`를 직접 불러 메모리에서만 다룬다).
# 대상 확인 두 키(`…CONFIRM_LOGIN_ROLE`·`…CONFIRM_DATABASE`)와 DSN이 맞아야만 쓴다.
set -a; . "$ENV_FILE"; set +a
mapfile -t APIS < <(docker ps -q \
  --filter "label=com.docker.compose.service=${E2E_C7_MAP_API_SERVICE:?E2E_C7_MAP_API_SERVICE}")
[[ "${#APIS[@]}" == 1 ]] || die "Map API 컨테이너가 정확히 하나가 아니다 (${#APIS[@]}개)"
python3 -I - "$ENV_FILE" "${APIS[0]}" <<'PY' || die "fixture DSN을 유도하지 못했다"
import json, os, re, subprocess, sys, tempfile
from urllib.parse import urlsplit

env_file, api = sys.argv[1], sys.argv[2]
KEY = "E2E_ADMIN_FEATURE_FIXTURE_PG_DSN"


def refuse(reason):
    # 값(비밀)은 메시지에 넣지 않는다.
    raise SystemExit(f"  {reason}")


record = json.loads(subprocess.run(
    ["docker", "inspect", "--", api],
    check=True, capture_output=True, text=True, timeout=60,
).stdout)[0]
runtime_env = dict(item.partition("=")[::2] for item in record["Config"]["Env"])
dsn = runtime_env.get("KOR_TRAVEL_MAP_PG_DSN", "")
parts = urlsplit(dsn)
# 러너(`run-admin-feature-live-acceptance.sh` validate_env)가 받는 scheme과 같다.
if parts.scheme not in {"postgresql", "postgresql+asyncpg"}:
    refuse("API DSN의 scheme이 postgresql / postgresql+asyncpg가 아니다")
if parts.username != os.environ["E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_LOGIN_ROLE"]:
    refuse("API DSN의 사용자가 E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_LOGIN_ROLE와 다르다")
if parts.path != "/" + os.environ["E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_DATABASE"]:
    refuse("API DSN의 DB가 E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_DATABASE와 다르다")
# 이 파일은 bash가 `set -a; .`로 읽는다 — 따옴표 없이 source해도 한 단어로 남는 문자만 받는다.
if not re.fullmatch(r"[A-Za-z0-9+:/@._~%-]+", dsn):
    refuse("API DSN에 따옴표 없이 source할 수 없는 문자가 있다")

with open(env_file, encoding="utf-8") as handle:
    lines = handle.read().splitlines(keepends=True)
hits = [index for index, line in enumerate(lines) if line.startswith(KEY + "=")]
if len(hits) != 1:
    refuse(f"{KEY} 줄이 정확히 하나가 아니다({len(hits)}줄)")
lines[hits[0]] = f"{KEY}={dsn}\n"

# 같은 디렉터리의 0600 임시 파일에 쓰고 rename한다 — 도중에 죽어도 옛 파일이 온전하다.
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(env_file), prefix=".d2-live.env.")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.writelines(lines)
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_file)
except BaseException:
    if os.path.exists(tmp):
        os.unlink(tmp)
    raise

# 치환은 결과를 직접 센다(2단계와 같은 규약). 값은 비교만 하고 출력하지 않는다.
with open(env_file, encoding="utf-8") as handle:
    written = [line.rstrip("\n") for line in handle if line.startswith(KEY + "=")]
if written != [f"{KEY}={dsn}"]:
    refuse(f"{KEY}가 정확히 한 줄로 갱신되지 않았다")
print(f"  {KEY} = API DSN (사용자·DB 확인, 값은 출력하지 않는다)")
PY

say "완료 — 다음은 D1, 그 다음 D2 (같은 체크아웃)"
