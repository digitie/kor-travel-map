#!/bin/bash
# n150 사전 점검 — 재구축·chain·배포를 시작하기 전에 돌린다. 하나라도 FAIL이면 시작하지 않는다.
# usage: sudo bash ~/preflight.sh [rebuild|chain|deploy-transport|deploy-weather] [--allow-runs]
# 근거(2026-10-03~04 실패 기록): 부하 cold start → healthcheck 창 초과, /tmp(tmpfs=RAM) 압박,
# 빌드 동시 실행 → BuildKit grpc/timeout, deploy-status in_progress → full stop 경로, 진행 중 run 유실,
# Docker Hub TLS timeout, 옛 메타DB 차단 → storage migrate 실패, 다른 세션의 .env 변경(C6c leak).
set -u
KIND="${1:-rebuild}"; ALLOW_RUNS=0; [ "${2:-}" = "--allow-runs" ] && ALLOW_RUNS=1
fail=0; warn=0
ok(){ printf '  OK    %s\n' "$*"; }
bad(){ printf '  FAIL  %s\n' "$*"; fail=$((fail+1)); }
wrn(){ printf '  WARN  %s\n' "$*"; warn=$((warn+1)); }
K=/opt/kor-travel-docker-manager

echo "== 자원"
read l1 l5 l15 _ < /proc/loadavg
awk -v a="$l1" -v b="$l5" 'BEGIN{exit !(a<=8 && b<=9)}' && ok "load $l1/$l5 (≤8/9)" || bad "load $l1/$l5 높음 — 한가할 때"
avail=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)
[ "$avail" -ge 4 ] && ok "MemAvailable ${avail}G (≥4G)" || bad "MemAvailable ${avail}G 부족"
tmpu=$(df --output=pcent /tmp | tail -1 | tr -dc 0-9)
[ "$tmpu" -le 50 ] && ok "/tmp(tmpfs) ${tmpu}%" || bad "/tmp ${tmpu}% — 오래된 잔여 정리 필요"
rootu=$(df --output=pcent / | tail -1 | tr -dc 0-9)
[ "$rootu" -le 90 ] && ok "/ ${rootu}%" || bad "/ ${rootu}% 디스크 부족"
iow=$(vmstat 2 2 | tail -1 | awk '{print $16}')
[ "${iow:-0}" -le 35 ] && ok "iowait ${iow}%" || wrn "iowait ${iow}% 높음"

echo "== 겹치는 작업"
act=$(systemctl list-units --type=service --state=activating --no-legend 2>/dev/null | awk '{print $1}' | grep -E 'ktdm-rebuild|chain1[67]|guarded-rb|d2-|transport-(deploy|prep)|dagster-cutover|weather' || true)
[ -z "$act" ] && ok "진행 중인 rebuild/chain/deploy unit 없음" || bad "진행 중: $(echo $act)"
bk=$(pgrep -fc 'buildx|buildkit.*solve|docker-compose.* build' || true)
[ "${bk:-0}" -eq 0 ] && ok "진행 중 빌드 없음" || bad "빌드 ${bk}개 진행 중 — 겹치면 BuildKit 실패"
pt=$(pgrep -fc 'python.* -m pytest|pytest ' || true)
[ "${pt:-0}" -eq 0 ] && ok "pytest 없음" || wrn "pytest ${pt}개 실행 중(부하)"

echo "== Dagster 진행 중 run (공용 plane)"
runs=$(curl -s -m 20 http://127.0.0.1:11002/graphql -H 'content-type: application/json' \
  -d '{"query":"{ runsOrError(filter:{statuses:[STARTED,STARTING]}, limit:100){ ... on Runs { results { jobName tags{key value} } } } }"}' \
  | python3 -c 'import json,sys
from collections import Counter
r=json.load(sys.stdin)["data"]["runsOrError"]["results"]
c=Counter(next((t["value"] for t in x["tags"] if t["key"]=="dagster/code_location"),"?") for x in r)
print(" ".join(f"{k}={v}" for k,v in c.items()) or "none")' 2>/dev/null || echo "조회실패")
case "$KIND" in
  rebuild|chain) rel='kortravelmap|pinvi' ;;
  deploy-transport) rel='kor-travel-transport' ;;
  deploy-weather) rel='kortravelweather' ;;
  *) rel='^$' ;;
esac
if [ "$runs" = "조회실패" ]; then bad "공용 webserver 조회 실패"
elif echo "$runs" | tr ' ' '\n' | grep -qE "$rel"; then
  [ $ALLOW_RUNS = 1 ] && wrn "관련 run 진행 중: $runs (--allow-runs)" || bad "관련 run 진행 중: $runs — 끝나길 기다릴 것"
else ok "관련 run 없음 (전체: $runs)"; fi

echo "== Manager/핀 상태"
rev=$(tr -d '[:space:]' < $K/.ktdm-source-revision); ok "Manager $rev"
$K/backend/.venv/bin/ktdctl pin verify >/dev/null 2>&1 && ok "pin verify" || bad "pin verify 실패 — rebind 필요?"
$K/backend/.venv/bin/ktdctl pin show 2>/dev/null | grep -E '^(map|pinvi) ' | sed 's/^/        /'
ds=$(grep -E "^KTDM_PINNED_RUNTIME_STATE_ROOT=" "$(readlink -f $K/.env)" | cut -d= -f2-)/kor-travel-docker-manager/deploy-status.json
st=$(python3 -c "import json;print(json.load(open('$ds')).get('state'))" 2>/dev/null)
if [ "$KIND" = rebuild ] || [ "$KIND" = chain ]; then
  [ "$st" = committed ] && ok "deploy-status committed (같은 쌍이면 무중단 수렴)" || wrn "deploy-status=$st — full run(Map·PinVi 정지) 경로, 짧은 다운 감수·guarded 실행"
fi
envf=$(readlink -f $K/.env)
grep -q '^KOR_TRAVEL_CONCIERGE_REPO_DIR=' "$envf" && bad ".env에 KOR_TRAVEL_CONCIERGE_REPO_DIR 활성(C6c leak → rebuild 거부)" || ok "concierge REPO_DIR 비활성"
[ -e /opt/kor-travel-concierge ] && bad "/opt/kor-travel-concierge 존재(C6c leak)" || ok "/opt/kor-travel-concierge 없음"

echo "== 서비스 건강"
unh=$(docker ps --format '{{.Names}} {{.Status}}' | grep -E 'unhealthy|Restarting' || true)
[ -z "$unh" ] && ok "unhealthy/restarting 컨테이너 없음" || bad "비정상: $unh"
for u in https://${MAP_UI_HOST:?set MAP_UI_HOST}/login https://${MAP_API_HOST:?set MAP_API_HOST}/health https://${PINVI_API_HOST:?set PINVI_API_HOST}/health; do
  c=$(curl -s -o /dev/null -m 15 -w '%{http_code}' $u); [ "$c" = 200 ] && ok "$c $u" || bad "$c $u"; done

echo "== 외부 의존"
c=$(curl -s -o /dev/null -m 15 -w '%{http_code}' 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/node:pull')
[ "$c" = 200 ] && ok "Docker Hub auth $c" || wrn "Docker Hub auth $c — 빌드가 base image 확인에서 실패할 수 있음"

c=$(curl -s -o /dev/null -m 15 -w '%{http_code}' 'https://ghcr.io/token?scope=repository:astral-sh/uv:pull&service=ghcr.io')
[ "$c" = 200 ] && ok "ghcr.io auth $c" || wrn "ghcr.io auth $c — uv 등 ghcr base image 빌드가 실패할 수 있음"

echo "== 판정: FAIL=$fail WARN=$warn"
[ $fail -eq 0 ] && echo "PREFLIGHT_PASS" || echo "PREFLIGHT_FAIL"
exit $fail
