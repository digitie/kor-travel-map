#!/bin/bash
# 재핀 사이클의 **후반부**: executor 이미지 → repin → ACL preflight → D1 →
# lane 정리 → D2.
#
# 정본은 저장소의 `scripts/n150/chain16.sh`다(ADR-102 결정 6). 운영자가 `/root`로
# 복사해 쓴다 — `scripts/n150/README.md`.
#
# chain12.sh와 같은 단계지만 회전(A)과 rebuild(B)는 빼 두었다 — 이미 끝난
# 사이클을 이어받을 때 그 둘을 다시 돌리면 71분을 버리고 원장에 중복 회전이
# 남는다. 대신 시작 전에 **핀 원장과 인자가 같은지 확인**한다. 리터럴로 박지
# 않는 이유는 그것이 드리프트의 출처이기 때문이다.
#
# D1과 D2는 **같은 체크아웃**에서 돈다 — `$MAP`의 `git archive`를 `$NEW`에 풀어 둔
# 평범한 트리다. 종전에는 D2가 root 소유 스냅샷(`/usr/local/lib/...`)에서 돌았고 그
# 스냅샷을 attestation으로 증명했다. ADR-102가 그 두 번째 증명을 걷어냈다.
#
#   chain16.sh MAP_SHA40 PINVI_SHA40 EXECBUILD_UNIT D2_UNIT TAG
set -uo pipefail

MAP="${1:?MAP}"
PINVI="${2:?PINVI}"
EB="${3:?execbuild unit}"
D2U="${4:?d2 unit}"
TAG="${5:?tag}"
FE=packages/kor-travel-map-admin/frontend
NEW=/home/digitie/ktm-c7-$MAP
R=/var/lib/kor-travel-map/admin-feature-live-acceptance
D1ROOT=/home/digitie/d1-$TAG

die() { echo "!! $1" >&2; exit 1; }
say() { printf '\n===== %s =====\n' "$1"; }

[[ "$MAP" =~ ^[0-9a-f]{40}$ ]] || die "MAP revision이 40-hex가 아니다"
[[ "$PINVI" =~ ^[0-9a-f]{40}$ ]] || die "PINVI revision이 40-hex가 아니다"

say "0. 핀 원장 대조"
PINSHOW="$(/opt/kor-travel-docker-manager/backend/.venv/bin/ktdctl pin show 2>/dev/null)"
LEDGER_MAP="$(printf '%s\n' "$PINSHOW" | awk '$1=="map"{print $2; exit}')"
LEDGER_PINVI="$(printf '%s\n' "$PINSHOW" | awk '$1=="pinvi"{print $2; exit}')"
echo "  ledger map  =$LEDGER_MAP"
echo "  ledger pinvi=$LEDGER_PINVI"
[ "$LEDGER_MAP" = "$MAP" ] || die "인자 MAP이 핀 원장과 다르다"
[ "$LEDGER_PINVI" = "$PINVI" ] || die "인자 PINVI가 핀 원장과 다르다"

say "C. executor 이미지 ($EB)"
sudo -u digitie git -C /home/digitie/ktm-c7-src fetch -q origin main
sudo -u digitie git -C /home/digitie/ktm-c7-src checkout -q --detach "$MAP" \
  || die "ktm-c7-src를 $MAP 으로 옮기지 못했다"
systemd-run --no-block --unit="$EB" --collect --property=Type=oneshot \
  --property=TimeoutStartSec=2400 --uid=digitie --gid=digitie \
  --working-directory=/home/digitie/ktm-c7-src --setenv=HOME=/home/digitie \
  /home/digitie/ktm-c7-src/scripts/build-c7-playwright-image.sh >/dev/null || die "이미지 기동 실패"
while [ "$(systemctl show "$EB" -p ActiveState --value)" = activating ]; do sleep 30; done
echo "  Result=$(systemctl show "$EB" -p Result --value)"
label="$(docker image inspect kor-travel-map-c7-playwright:local \
  --format '{{index .Config.Labels "io.kortravelmap.c7.repository-commit"}}' 2>/dev/null || true)"
echo "  라벨=$label"
[ "$label" = "$MAP" ] || die "이미지 라벨이 핀과 다르다 ($label != $MAP)"

say "D. repin (.d2-live.env)"
/root/repin.sh "$MAP" "$PINVI" 2>&1 | tail -12
[ "${PIPESTATUS[0]}" = 0 ] || die "repin 실패"

say "E. M01 ACL preflight"
set -a; . /root/.d2-live.env; set +a
API=$(docker ps -q --filter "label=com.docker.compose.service=$E2E_C7_MAP_API_SERVICE" | head -1)
[ -n "$API" ] || die "Map API 컨테이너를 찾지 못했다"
IMG=$(docker inspect "$API" --format '{{.Image}}')
SCRIPT=/tmp/m01_pf_$TAG.py
sudo -u digitie git -C /tmp/ktm-lint fetch -q origin main
sudo -u digitie git -C /tmp/ktm-lint show origin/main:scripts/m01_activation_preflight.py > "$SCRIPT"
chmod 0444 "$SCRIPT"
python3 - "$API" "$IMG" "$SCRIPT" <<'PY'
import json, os, subprocess, sys
api, image, script = sys.argv[1:]
record = json.loads(subprocess.run(["docker","inspect","--",api],check=True,
                                   capture_output=True,text=True).stdout)[0]
runtime_env = dict(item.partition("=")[::2] for item in record["Config"]["Env"])
proc_env = dict(os.environ); proc_env.update(runtime_env)
proc_env["KOR_TRAVEL_MAP_PG_DSN"] = os.environ["E2E_ADMIN_FEATURE_FIXTURE_PG_DSN"]
env_args = [v for n in sorted(runtime_env) for v in ("--env", n)]
cmd = ["docker","create","--pull=never","--network","host","--read-only",
       "--security-opt","no-new-privileges","--cap-drop","ALL",
       "--tmpfs","/tmp:rw,nosuid,nodev,noexec,mode=1777", *env_args,
       "--env","KOR_TRAVEL_MAP_PG_DSN","--volumes-from", f"{api}:ro",
       "--mount", f"type=bind,src={script},dst=/opt/pf.py,readonly",
       "--entrypoint","python", image, "/opt/pf.py","--json"]
cid = subprocess.run(cmd,check=True,capture_output=True,text=True,env=proc_env).stdout.strip()
subprocess.run(["docker","start","--",cid],check=True,capture_output=True)
subprocess.run(["docker","wait","--",cid],check=True,capture_output=True,text=True)
out = subprocess.run(["docker","logs","--",cid],capture_output=True,text=True)
subprocess.run(["docker","rm","--force","--",cid],capture_output=True)
try:
    payload = json.loads(out.stdout)
except Exception:
    print(out.stdout[:400]); print(out.stderr[-800:]); sys.exit(1)
print("  ", payload["counts"], payload["result"])
sys.exit(0 if payload["result"] == "passed" else 1)
PY
[ "$?" = 0 ] || die "ACL preflight 실패"
rm -f "$SCRIPT"

say "F. D1"
# 체크아웃은 매번 새로 푼다. D2는 root로 이 트리의 러너를 실행하므로, 지난 사이클이
# 남긴 트리를 재사용하면 "핀된 SHA의 평범한 체크아웃"이라는 전제가 증명되지 않는다.
# node_modules는 symlink라 다시 푸는 비용이 작다.
rm -rf "$NEW"; mkdir -p "$NEW"
git -c safe.directory=/home/digitie/ktm-c7-src -C /home/digitie/ktm-c7-src \
  archive --format=tar "$MAP" | tar -xf - -C "$NEW"
[ -f "$NEW/scripts/run-admin-feature-live-acceptance.sh" ] || die "체크아웃 추출 실패: $NEW"
chown -R digitie:digitie "$NEW"
[ -e "$NEW/node_modules" ] || sudo -u digitie ln -s /home/digitie/kor-travel-map/node_modules "$NEW/node_modules"
[ -e "$NEW/$FE/node_modules" ] || sudo -u digitie ln -s "/home/digitie/kor-travel-map/$FE/node_modules" "$NEW/$FE/node_modules"
rm -rf /tmp/kor-travel-map-playwright
D1OUT=$(sudo -u digitie -H \
  --preserve-env=E2E_BASE_URL,NEXT_PUBLIC_KOR_TRAVEL_MAP_API,E2E_DAGSTER_URL,E2E_ADMIN_USERNAME,E2E_ADMIN_PASSWORD,E2E_LIVE_ALLOW_PROD \
  bash -c "cd $NEW/$FE && export E2E_LIVE_WORKERS=1 PLAYWRIGHT_ARTIFACT_ROOT=$D1ROOT && rm -rf $D1ROOT && /home/digitie/kor-travel-map/node_modules/.bin/playwright test --config playwright.live.config.ts --workers=1 --reporter=line e2e/live/admin-scenario-catalog.live.spec.ts e2e/live/backups-restore.live.spec.ts e2e/live/home-dashboard-roundtrip.live.spec.ts e2e/live/logs.live.spec.ts 2>&1 | tail -3")
echo "$D1OUT"
echo "$D1OUT" | grep -qE '[0-9]+ passed' || die "D1 결과를 읽지 못했다"
echo "$D1OUT" | grep -qE '[0-9]+ (failed|flaky)' && die "D1 실패"

say "G. lane 정리"
if [ -e "$R/BLOCKED.json" ]; then /root/adjudicate.sh 2>&1 | tail -3; else echo "  BLOCKED 없음"; fi

say "H. D2 ($D2U)"
# D1과 같은 체크아웃($NEW)의 러너를 돌린다. 경로는 인자로 넘긴다 — 종전처럼
# run-d2.sh 본문의 스냅샷 경로를 sed로 고쳐 쓰지 않는다.
systemd-run --no-block --unit="$D2U" --collect --property=Type=oneshot \
  --property=TimeoutStartSec=5400 /root/run-d2.sh "$MAP" >/dev/null || die "D2 기동 실패"
echo "  시작 $(date -u +%FT%TZ)"
while [ "$(systemctl show "$D2U" -p ActiveState --value)" = activating ]; do sleep 30; done
echo "  종료 $(date -u +%FT%TZ)  Result=$(systemctl show "$D2U" -p Result --value)"
journalctl -u "$D2U" --no-pager -n 8 -o cat | tail -5
echo "--- lane 상태 ---"
for f in BLOCKED.json RESULT.json ACTIVE.json; do
  [ -e "$R/$f" ] && echo "  $f 존재" || echo "  $f 없음"
done
D=$(ls -dt "$R"/run-* 2>/dev/null | head -1)
echo "--- $(basename "${D:-none}") ---"
ls -1 "$D" 2>/dev/null | sed 's/^/    /'
echo "--- result.json ---"; cat "$D/result.json" 2>/dev/null
echo; echo "--- direct-api-audit.json ---"; cat "$D/direct-api-audit.json" 2>/dev/null
