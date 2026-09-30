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
# 남은 일은 다섯이다(전부 멱등):
#   0. 인자가 핀 원장과 같은지 본다(`ktdctl pin show` — Manager 내부 파일은 읽지 않는다).
#   1. C7 executor 이미지 라벨이 MAP인지 본다.
#   2. /root/.d2-live.env의 비밀이 아닌 두 키를 갱신하고 퇴역한 두 키를 지운다.
#   3. Dagster service 키를 Manager가 설치한 토폴로지(`ktdctl targets list --json`)에서
#      유도한다 — 공유 Dagster plane(Manager ADR-54)으로 옮긴 프로젝트의 Dagster는
#      code-server 하나다.
#   4. D2 fixture DSN을 실행 중인 Map API 컨테이너의 DSN에서 유도한다(ADR-103).
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
# D2 러너가 도는 compose project 디렉터리(`run-d2.sh`와 같은 곳).
COMPOSE_DIR=/opt/kor-travel-docker-manager
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

say "3. Dagster service 키 (Manager 토폴로지에서 유도)"
# 손으로 적은 service 이름은 Manager가 토폴로지를 바꾸면 조용히 낡는다 — PinVi가 공유
# Dagster plane으로 옮겨 가며 옛 Dagster service가 사라졌고(자리는 같은 image의 code-server),
# preflight는 없는 service에서 멈췄다. 그래서 매 주기 Manager가
# 설치한 모델에서 다시 읽는다. 프로젝트 target은 이름이 아니라 그 API service
# (`E2E_C7_MAP_API_SERVICE`·`E2E_C7_PINVI_API_SERVICE`)를 자기 runtime service로 가진
# target이다. 그 target의 `dagster.control_plane`이
#   - `shared`: 프로젝트가 가진 Dagster runtime service는 code-server 하나다. 그 이름을 쓴다
#     (Map은 web·daemon 두 키가 모두 그것을 가리킨다 — 러너는 두 키로 Map 설정을 읽는다).
#   - `own`: web·daemon·code-server가 따로 있다. 적힌 값이 그 target의 Dagster runtime
#     service인지 확인만 하고 바꾸지 않는다.
# Dagster runtime service는 이름에 `dagster`가 든 runtime service다(Manager의 service 명명).
# Map의 plane은 `E2E_C7_MAP_DAGSTER_CONTROL_PLANE`(own|shared)로도 적는다 — preflight는 이 값이
# `shared`일 때만 web·daemon 두 키가 한 service를 가리키도록 허용한다(전용 plane에서는 서로 달라야
# 한다). 이 키들은 손으로 고치지 않는다(지원하지 않는다) — 매 repin이 다시 쓴다.
# 값은 비밀이 아니다(compose service 이름). 쓰기는 4단계와 같은 0600 임시 파일 + rename이다.
# 토폴로지 JSON은 argv가 아니라 stdin으로 넘긴다(크기 제한·ps 노출 없이). 프로그램은 `-c`다.
set -a; . "$ENV_FILE"; set +a
TOPOLOGY="$("$KTDCTL" targets list --json 2>/dev/null)" || die "ktdctl targets list 실패"
DAGSTER_KEYS_PROGRAM="$(cat <<'PY'
import json, os, re, subprocess, sys, tempfile

env_file = sys.argv[1]
PLANE_KEY = "E2E_C7_MAP_DAGSTER_CONTROL_PLANE"
SERVICE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")


def refuse(reason):
    raise SystemExit(f"  {reason}")


try:
    targets = json.loads(sys.stdin.read())
except json.JSONDecodeError:
    refuse("ktdctl targets list --json 출력이 JSON이 아니다")
if not isinstance(targets, list) or not all(isinstance(t, dict) for t in targets):
    refuse("ktdctl targets list --json 모양이 다르다")


def project(api_env):
    api = os.environ.get(api_env, "")
    owners = [t for t in targets if api and api in (t.get("runtime_services") or [])]
    if len(owners) != 1:
        refuse(f"{api_env}를 runtime service로 가진 target이 정확히 하나가 아니다({len(owners)})")
    target = owners[0]
    plane = (target.get("dagster") or {}).get("control_plane")
    services = [s for s in target.get("runtime_services") or [] if "dagster" in s]
    if plane not in {"own", "shared"}:
        refuse(f"target {target.get('id')}의 dagster.control_plane을 모른다: {plane!r}")
    return target.get("id"), plane, services


derived = {}
for api_env, keys in (
    ("E2E_C7_MAP_API_SERVICE", ("E2E_C7_DAGSTER_WEB_SERVICE", "E2E_C7_DAGSTER_DAEMON_SERVICE")),
    ("E2E_C7_PINVI_API_SERVICE", ("E2E_C7_PINVI_DAGSTER_SERVICE",)),
):
    target_id, plane, services = project(api_env)
    if plane == "shared":
        if len(services) != 1:
            refuse(f"공유 plane target {target_id}의 Dagster runtime service가 하나가 아니다: {services}")
        derived.update(dict.fromkeys(keys, services[0]))
    else:
        current = [os.environ.get(key, "") for key in keys]
        if any(value not in services for value in current) or len(set(current)) != len(current):
            refuse(f"전용 plane target {target_id}: {', '.join(keys)}가 그 Dagster runtime service가 아니다")
        derived.update(zip(keys, current))
    if api_env == "E2E_C7_MAP_API_SERVICE":
        map_plane = plane
    print(f"  {target_id}: control_plane={plane} → " + ", ".join(f"{k}={derived[k]}" for k in keys))
for key, value in derived.items():
    # 파일은 따옴표 없이 source된다 — compose service 이름 문법 밖의 값은 쓰지 않는다.
    if SERVICE_NAME.fullmatch(value) is None:
        refuse(f"{key}의 유도 값이 compose service 이름이 아니다")

with open(env_file, encoding="utf-8") as handle:
    lines = handle.read().splitlines(keepends=True)
for key, value in derived.items():
    hits = [index for index, line in enumerate(lines) if line.startswith(key + "=")]
    if len(hits) != 1:
        refuse(f"{key} 줄이 정확히 하나가 아니다({len(hits)}줄)")
    lines[hits[0]] = f"{key}={value}\n"
# plane 키는 이 단계가 새로 만든 키다 — 없으면 덧붙이고, 있으면 정확히 한 줄이어야 한다.
plane_hits = [index for index, line in enumerate(lines) if line.startswith(PLANE_KEY + "=")]
if len(plane_hits) > 1:
    refuse(f"{PLANE_KEY} 줄이 여러 개다({len(plane_hits)}줄)")
if plane_hits:
    lines[plane_hits[0]] = f"{PLANE_KEY}={map_plane}\n"
else:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append(f"{PLANE_KEY}={map_plane}\n")
derived[PLANE_KEY] = map_plane

fd, tmp = tempfile.mkstemp(dir=os.path.dirname(env_file), prefix=".d2-live.env.")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.writelines(lines)
    os.chmod(tmp, 0o600)
    # 소비자와 같은 방법(`set -a; .`)으로 읽은 값을 대조한다. 이 프로세스는 옛 값을 env로
    # 물려받았으므로(위 셸의 `set -a`) 먼저 지운다 — 파일이 키를 못 세워도 옛 값이 가리지 않게.
    script = (
        f"unset {' '.join(derived)}; set -a; . \"$1\"; "
        + " ".join(f'printf "%s\\n" "${{{key}}}";' for key in derived)
    )
    sourced = subprocess.run(
        ["bash", "-c", script, "_", tmp], check=False, capture_output=True, text=True, timeout=60
    )
    if sourced.returncode != 0 or sourced.stdout.splitlines() != list(derived.values()):
        refuse("Dagster service 키를 source한 값이 유도한 값과 다르다")
    os.replace(tmp, env_file)
except BaseException:
    if os.path.exists(tmp):
        os.unlink(tmp)
    raise
PY
)"
printf '%s' "$TOPOLOGY" | python3 -I -c "$DAGSTER_KEYS_PROGRAM" "$ENV_FILE" ||
  die "Dagster service 키를 유도하지 못했다"

say "4. D2 fixture DSN (Map API 컨테이너에서 유도)"
# fixture DSN은 API 런타임 DSN과 사용자·host:port·DB·비밀번호가 같다(2026-09-28 실측).
# 손으로 적은 사본은 DB가 다른 instance로 옮겨 가면(ADR-103) 조용히 옛 instance를
# 가리킨다. 그래서 매 주기 실행 중인 API 컨테이너의 `KOR_TRAVEL_MAP_PG_DSN`에서 다시
# 유도한다 — instance 이름·port를 여기 적지 않는다. 값은 비밀이다: 출력하지 않고 호스트
# argv에도 싣지 않는다(helper가 `docker inspect`를 직접 불러 메모리에서만 다룬다).
# 대상 확인 두 키(`…CONFIRM_LOGIN_ROLE`·`…CONFIRM_DATABASE`)와 DSN이 맞아야만 쓴다.
set -a; . "$ENV_FILE"; set +a
# API 컨테이너는 D2 러너와 같은 방법으로 찾는다 — 러너가 도는 compose project(`run-d2.sh`의
# cwd)의 그 service, 정확히 하나. 같은 service 라벨을 단 다른 stack(격리 live 등)은 보지 않는다.
# stderr는 러너처럼 버린다: compose는 이 조회에서도 project의 `.env`를 해석하고, `$`가 든 값의
# 꼬리를 변수 이름으로 읽어 "variable is not set" 경고로 찍는다 — 비밀에서 나온 조각이 운영
# 로그(`chain16` D 단계의 `tail`)로 샌다(2026-09-29 n150 실측). 실패는 `|| die`와 64-hex 검사가 잡는다.
API="$(docker compose --project-directory "$COMPOSE_DIR" ps --no-trunc -q \
  "${E2E_C7_MAP_API_SERVICE:?E2E_C7_MAP_API_SERVICE}" 2>/dev/null)" || die "Map API compose 조회 실패"
[[ "$API" =~ ^[0-9a-f]{64}$ ]] || die "Map API 컨테이너가 정확히 하나가 아니다"
python3 -I - "$ENV_FILE" "$API" <<'PY' || die "fixture DSN을 유도하지 못했다"
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
# 이 파일은 bash가 `set -a; .`로 읽는다 — 따옴표 없이 source해도 한 단어로 남고 명령을 돌리지
# 않는 문자만 받는다. 이것만으로는 값이 보존되지 않는다: 대입의 `=` 뒤와 `:` 뒤의 `~`는
# tilde 확장된다(`:~:pw@` → `:/root:pw@`). 그래서 아래에서 source한 값을 직접 대조한다.
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
    # 소비자와 같은 방법으로 읽어 본다 — 바이트가 아니라 source한 **값**이 DSN이어야 한다.
    # 위 문자 검사를 지나온 값만 source하므로 명령 치환은 없다. 값은 비교만 한다. 이 프로세스는
    # 옛 값을 env로 물려받았으므로(위 셸의 `set -a`) 먼저 지운다.
    sourced = subprocess.run(
        ["bash", "-c", f'unset {KEY}; set -a; . "$1"; printf %s "${{{KEY}}}"', "_", tmp],
        check=False, capture_output=True, text=True, timeout=60,
    )
    if sourced.returncode != 0 or sourced.stdout != dsn:
        refuse(f"{KEY}를 source한 값이 API DSN과 다르다")
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
