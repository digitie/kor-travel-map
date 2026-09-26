#!/bin/bash
# rebuild가 가로지른 BLOCKED lane을 판정으로 정리한다.
#
# `begin-recovery`는 BLOCKED의 execution identity와 현재 identity의 일치를 요구하는데
# rebuild가 API 이미지를 바꾼다 — 즉 lane recovery가 구조적으로 불가능하다. 이때의 정본
# 경로는 **잔여물을 직접 측정해 0임을 확인한 뒤** `clear-blocked`로 정리하고 증거를 남기는
# 것이다. 잔여물이 하나라도 있으면 여기서 멈춘다.
#
# 정본은 저장소의 `scripts/n150/adjudicate.sh`다(ADR-102 결정 6). 상태 helper는 D1·D2와 같은
# 핀된 SHA의 평범한 체크아웃(`/home/digitie/ktm-c7-$E2E_C7_EXPECTED_GIT_COMMIT`)에서 부른다.
# 그 helper는 v4 BLOCKED만 읽는다 — 옛 v3 BLOCKED는 그것을 만든 커밋의 도구로 정리한다
# (runbook `admin-feature-live-acceptance.md` §6).
set -euo pipefail

R=/var/lib/kor-travel-map/admin-feature-live-acceptance
B="$R/BLOCKED.json"
[[ -e "$B" ]] || { echo "BLOCKED.json이 없다 — 할 일 없음"; exit 0; }
[[ "$(id -u)" == 0 ]] || { echo "root로 실행하라" >&2; exit 2; }

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
ARCH="$R/adjudicated-$STAMP"
install -d -o root -g root -m 0700 "$ARCH"
cp -a "$B" "$ARCH/BLOCKED.json"

python3 - "$ARCH/adjudication.json" "$STAMP" "$B" <<'PY'
import json, os, pathlib, subprocess, sys

out, stamp, blocked_path = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
blocked = json.loads(blocked_path.read_bytes())
# 소유권 키는 **name**이다 — fixture가 만드는 모든 행 이름에 run_id가 들어간다
# (`_admin_fixture_name` / `E2E suppressed {weather,price} {run_id}`). `feature_id`는 uuid라
# `e2e_live_acceptance::...` 문자열과 비교할 수 없다. legacy 주소가 남은 행을 가리킬 수
# 있으므로 alias도 함께 센다.
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
    input=sql, check=True, capture_output=True, text=True, timeout=120,
)
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
record = {
    "adjudicated_at": stamp,
    "blocked_run_id": blocked["run_id"],
    "blocked_phase": blocked["phase"],
    "blocked_recovery_attempt": blocked["recovery_attempt"],
    "blocked_execution": blocked["execution"],
    "current_execution": {
        "api_image_id": api_image,
        "playwright_image_id": os.environ["E2E_C7_PLAYWRIGHT_IMAGE"],
        "source_commit": os.environ["E2E_C7_EXPECTED_GIT_COMMIT"],
    },
    "reason": (
        "rebuild가 BLOCKED을 가로질렀다. begin-recovery는 BLOCKED.execution과 현재 "
        "execution의 일치를 요구하는데 rebuild가 API 이미지를 바꿔 lane recovery가 "
        "구조적으로 불가능하다. 아래 실측으로 잔여물 0을 확인하고 clear-blocked로 정리한다."
    ),
    "residue_measured": residue,
    "version": 2,
}
out.write_bytes(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
print("  잔여물 실측:", residue)
print("  blocked run:", blocked["run_id"], blocked["phase"])
PY

chmod 0600 "$ARCH"/*
python3 -I -B "$HELPER" clear-blocked --path "$B"
echo "  clear-blocked 완료 — 증거: $ARCH"
if [[ -e "$B" ]]; then echo "!! BLOCKED 잔존" >&2; exit 1; fi
echo "  BLOCKED.json 제거됨"
