#!/bin/bash
# 멈춘 BLOCKED lane을 판정으로 정리한다.
#
# 흔한 경우는 rebuild가 BLOCKED을 가로지른 것이다 — `begin-recovery`는 BLOCKED의 execution
# identity와 현재 identity의 일치를 요구하는데 rebuild가 API 이미지를 바꾸므로 lane recovery가
# 구조적으로 불가능하다. 정본 경로는 lane이 정말 멈췄는지(lock·ACTIVE·run 컨테이너) 보고
# **잔여물을 직접 측정해 0임을 확인한 뒤** `clear-blocked`로 정리하고 증거를 남기는 것이다.
# 무엇 하나라도 걸리면 여기서 멈춘다. 판정 기록은 execution 일치 여부를 함께 남긴다.
#
# 정본은 저장소의 `scripts/n150/adjudicate.sh`다(ADR-102 결정 6). 상태 helper는 D1·D2와 같은
# 핀된 SHA의 평범한 체크아웃(`/home/digitie/ktm-c7-$E2E_C7_EXPECTED_GIT_COMMIT`)에서 부른다.
# 그 helper는 v4 BLOCKED만 읽는다 — 옛 v3 BLOCKED는 그것을 만든 커밋의 도구로 정리한다
# (runbook `admin-feature-live-acceptance.md` §6).
set -euo pipefail

R=/var/lib/kor-travel-map/admin-feature-live-acceptance
B="$R/BLOCKED.json"
[[ "$(id -u)" == 0 ]] || { echo "root로 실행하라" >&2; exit 2; }
[[ -e "$B" ]] || { echo "BLOCKED.json이 없다 — 할 일 없음"; exit 0; }

# lane이 정말 멈춰 있을 때만 판정한다. 러너와 같은 lock을 잡고(도는 run의 BLOCKED를 지우지
# 않는다), 종결되지 않은 작업(ACTIVE)이나 남은 run 컨테이너가 있으면 멈춘다 — 그것은
# runbook §5의 operator recovery 몫이다. 잔여물 0만으로는 늦게 커밋되는 seed를 막지 못한다.
exec 9>"$R/orchestrator.lock"
flock -n 9 || { echo "!! 다른 D2 orchestrator가 lock을 잡고 있다" >&2; exit 2; }
if [[ -e "$R/ACTIVE.json" || -L "$R/ACTIVE.json" ]]; then
  echo "!! ACTIVE.json이 남아 있다 — 종결되지 않은 작업은 runbook §5의 operator recovery로" >&2
  exit 2
fi
leftover="$(docker ps -aq --filter label=io.kortravelmap.admin-feature-acceptance.run-key)"
[[ -z "$leftover" ]] || {
  echo "!! D2 run 컨테이너가 남아 있다: $(echo "$leftover" | tr '\n' ' ')" >&2
  exit 2
}

set -a; . /root/.d2-live.env; set +a
SRC="/home/digitie/ktm-c7-${E2E_C7_EXPECTED_GIT_COMMIT:?E2E_C7_EXPECTED_GIT_COMMIT}"
HELPER="$SRC/scripts/admin_feature_live_state.py"
[[ -f "$HELPER" ]] || { echo "!! 상태 helper가 없다: $HELPER (chain16 D1이 먼저 푼다)" >&2; exit 2; }
version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version"))' "$B")"
[[ "$version" == 4 ]] || {
  echo "!! BLOCKED v$version — 이 helper는 v4만 정리한다. runbook §6대로 그것을 만든 커밋의 도구로 정리하라" >&2
  exit 2
}

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RECORD="$(mktemp "$R/.adjudication-$STAMP.XXXXXX")"
trap 'rm -f "$RECORD"' EXIT

python3 - "$RECORD" "$STAMP" "$B" <<'PY'
import json, os, pathlib, subprocess, sys

out, stamp, blocked_path = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
blocked = json.loads(blocked_path.read_bytes())
# 소유권 키는 **name**이다 — fixture가 만드는 모든 행 이름에 run_id가 들어가고 `E2E `로
# 시작한다(`_admin_fixture_name` / `E2E suppressed {weather,price} {run_id}`). `feature_id`는
# uuid라 run_id 문자열과 비교할 수 없다. alias·request 두 줄은 옛 주소 체계의 잔재까지
# 넓게 센다(지금 스키마에서는 대개 0이다).
run_id = blocked["run_id"]
run_literal = "'" + run_id.replace("'", "''") + "'"
owned_by_run = f"name LIKE '%' || {run_literal} || '%'"
sql = (
    "SELECT 'owned_features', count(*) FROM feature.features "
    f"WHERE {owned_by_run} "
    "UNION ALL SELECT 'any_acceptance_prefix', count(*) FROM feature.features "
    "WHERE name LIKE 'E2E %' OR name LIKE 'e2e_live_acceptance::%' "
    "UNION ALL SELECT 'acceptance_aliases', count(*) FROM feature.feature_aliases "
    "WHERE alias LIKE 'e2e_live_acceptance::%' "
    "UNION ALL SELECT 'feature_requests', count(*) FROM ops.feature_requests "
    "WHERE resolved_feature_id IN (SELECT feature_id FROM feature.features "
    f"WHERE {owned_by_run});"
)
proc = subprocess.run(
    ["docker", "exec", "-i", "kor-travel-map-postgres", "psql", "-U", "kor_travel_map",
     "-p", "12700", "-d", "kor_travel_map", "-t", "-A", "-F", " ", "-v", "ON_ERROR_STOP=1"],
    input=sql, check=False, capture_output=True, text=True, timeout=120,
)
if proc.returncode != 0:
    raise SystemExit(f"잔여물 측정 실패(psql exit {proc.returncode}): {proc.stderr.strip()[-400:]}")
residue = {}
for line in proc.stdout.strip().splitlines():
    name, _, count = line.strip().partition(" ")
    residue[name] = int(count)
if len(residue) != 4:
    raise SystemExit(f"잔여물 측정 결과가 네 줄이 아니다 — 판정 불가: {residue}")
if any(residue.values()):
    raise SystemExit(f"잔여물이 있다 — clear-blocked 금지: {residue}")

# 현재 execution identity는 env와 실측 image에서 유도한다(손으로 적지 않는다). 필드는
# BLOCKED v4의 세 필드와 같다.
api = subprocess.run(
    ["docker", "ps", "-q", "--filter",
     f"label=com.docker.compose.service={os.environ['E2E_C7_MAP_API_SERVICE']}"],
    check=True, capture_output=True, text=True, timeout=60,
).stdout.split()[0]
api_image = subprocess.run(
    ["docker", "inspect", api, "--format", "{{.Image}}"],
    check=True, capture_output=True, text=True, timeout=60,
).stdout.strip()
current = {
    "api_image_id": api_image,
    "playwright_image_id": os.environ["E2E_C7_PLAYWRIGHT_IMAGE"],
    "source_commit": os.environ["E2E_C7_EXPECTED_GIT_COMMIT"],
}
record = {
    "adjudicated_at": stamp,
    "blocked_run_id": blocked["run_id"],
    "blocked_phase": blocked["phase"],
    "blocked_recovery_attempt": blocked["recovery_attempt"],
    "blocked_execution": blocked["execution"],
    "current_execution": current,
    # 같으면 lane recovery가 가능했을 수도 있다 — 그래도 잔여물 0·ACTIVE 없음·run 컨테이너
    # 없음이면 정리할 것이 없다. 다르면(rebuild가 가로질렀다) recovery는 구조적으로 불가능하다.
    "execution_matches_current": blocked["execution"] == current,
    "reason": (
        "lane이 멈춰 있다(lock 획득, ACTIVE 없음, run 컨테이너 없음). 아래 실측으로 잔여물 "
        "0을 확인하고 clear-blocked로 정리한다."
    ),
    "residue_measured": residue,
    "version": 2,
}
out.write_bytes(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
print("  잔여물 실측:", residue)
print("  blocked run:", blocked["run_id"], blocked["phase"])
PY

# 판정이 통과한 뒤에만 증거 디렉터리를 만든다 — 거부된 시도가 "adjudicated"로 남지 않는다.
ARCH="$R/adjudicated-$STAMP"
install -d -o root -g root -m 0700 "$ARCH"
cp -a "$B" "$ARCH/BLOCKED.json"
install -o root -g root -m 0600 "$RECORD" "$ARCH/adjudication.json"
chmod 0600 "$ARCH"/*
python3 -I -B "$HELPER" clear-blocked --path "$B"
echo "  clear-blocked 완료 — 증거: $ARCH"
if [[ -e "$B" ]]; then echo "!! BLOCKED 잔존" >&2; exit 1; fi
echo "  BLOCKED.json 제거됨"
