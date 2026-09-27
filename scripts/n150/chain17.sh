#!/bin/bash
# 전체 재핀 사이클: 회전 → rebuild → (chain16: executor 이미지 → repin → ACL
# preflight → D1 → lane 정리 → D2).
#
# 정본은 저장소의 `scripts/n150/chain17.sh`다(ADR-102 결정 6). 운영자가 `/root`로
# 복사해 쓴다 — `scripts/n150/README.md`.
#
# chain12.sh와 같은 일을 하지만 **리터럴을 하나도 들고 있지 않다**:
#   - Map revision: 인자
#   - PinVi revision: 핀 원장(`ktdctl pin show`)
#   - Manager revision: 설치본의 `.ktdm-source-revision`
# chain12는 Manager revision을 본문에 박아 두었고 그것이 낡아 재사용이 불가능했다.
#
# 회전과 rebuild는 Manager의 sanctioned launcher(`rotate-pinned-pair`,
# `run-pinned-rebuild-once`)가 한다. pair 계약 preflight(M05 `--rotation-preflight`)는
# 회전 전의 hard gate다 — 거부되면 아무것도 바꾸지 않고 멈춘다.
#
#   chain17.sh MAP_SHA40 REASON REBUILD_UNIT EXECBUILD_UNIT D2_UNIT TAG
set -uo pipefail

MAP="${1:?MAP}"
REASON="${2:?reason}"
RB="${3:?rebuild unit}"
EB="${4:?execbuild unit}"
D2U="${5:?d2 unit}"
TAG="${6:?tag}"

KTDCTL=/opt/kor-travel-docker-manager/backend/.venv/bin/ktdctl
DRIVER=/opt/kor-travel-docker-manager/scripts/m05_isolated_e2e.py
PYTHON=/opt/kor-travel-docker-manager/backend/.venv/bin/python

die() { echo "!! $1" >&2; exit 1; }
say() { printf '\n===== %s =====\n' "$1"; }

[[ "$MAP" =~ ^[0-9a-f]{40}$ ]] || die "MAP revision이 40-hex가 아니다"

say "0. 인자 유도"
PINVI="$("$KTDCTL" pin show 2>/dev/null | awk '$1=="pinvi"{print $2; exit}')"
[[ "$PINVI" =~ ^[0-9a-f]{40}$ ]] || die "핀 원장에서 PinVi revision을 읽지 못했다"
MGR="$(cat /opt/kor-travel-docker-manager/.ktdm-source-revision 2>/dev/null | tr -d '[:space:]')"
[[ "$MGR" =~ ^[0-9a-f]{40}$ ]] || die "설치된 Manager revision을 읽지 못했다"
echo "  map     =$MAP"
echo "  pinvi   =$PINVI  (핀 원장)"
echo "  manager =$MGR  (설치 매니페스트)"

say "A. 회전 preflight"
# driver는 거부 사유를 가린 한 줄로 stdout에 낸다(Manager ADR-51 잃는 보장 G-3). 버리지 않는다.
if ! PREFLIGHT="$("$PYTHON" -I "$DRIVER" --rotation-preflight "$MAP" "$PINVI")"; then
  die "rotation preflight 거부: ${PREFLIGHT:-(사유 줄 없음 — 위 stderr를 본다)}"
fi
echo "  OK"

say "B. 회전"
CURRENT_MAP="$("$KTDCTL" pin show 2>/dev/null | awk '$1=="map"{print $2; exit}')"
if [ "$CURRENT_MAP" = "$MAP" ]; then
  # C에서 실패한 뒤 다시 돌리는 경우다. 같은 pair로의 회전은 registry가 거부한다(바뀌는 revision 없음).
  echo "  이미 회전됨(원장 map=$MAP) — 건너뛴다"
else
  # 성공하면 history 두 줄만, 실패하면 출력 전체를 보인다 — 거르면 실패 사유가 사라진다.
  ROTATION="$(/opt/kor-travel-docker-manager/scripts/rotate-pinned-pair "$MAP" "$PINVI" "$REASON" 2>&1)"
  ROTATION_STATUS=$?
  if [ "$ROTATION_STATUS" -ne 0 ]; then
    printf '%s\n' "$ROTATION" >&2
    die "회전 실패(exit $ROTATION_STATUS)"
  fi
  printf '%s\n' "$ROTATION" | grep -A 1 'history ' | head -2
fi
NEWMAP="$("$KTDCTL" pin show 2>/dev/null | awk '$1=="map"{print $2; exit}')"
[ "$NEWMAP" = "$MAP" ] || die "회전 뒤에도 원장이 $MAP 을 가리키지 않는다"

say "C. rebuild ($RB)"
OUT="/root/rebuild-$RB"
[ -e "$OUT" ] && die "출력 디렉터리가 이미 있다: $OUT (launcher가 새 경로를 요구한다)"
systemd-run --no-block --unit="$RB" --collect --property=Type=oneshot \
  --property=TimeoutStartSec=7200 \
  /opt/kor-travel-docker-manager/scripts/run-pinned-rebuild-once "$MGR" "$OUT" >/dev/null \
  || die "rebuild 기동 실패"
while [ "$(systemctl show "$RB" -p ActiveState --value)" = activating ]; do sleep 45; done
echo "  Result=$(systemctl show "$RB" -p Result --value)"
if [ ! -f "$OUT/result.json" ]; then
  # launcher가 driver를 부르기 전에 멈췄다(revision 불일치·lock·claim). 원인은 unit 로그에 있다.
  journalctl -u "$RB" -n 60 --no-pager >&2
  die "rebuild가 result.json 없이 끝났다"
fi
if ! python3 -c "
import json, sys
d = json.load(open('$OUT/result.json'))
if d.get('success'):
    print('  success=', d.get('success'), 'phase=', d.get('phase'),
          'pinset=', d.get('pinset_sha256','')[:16])
    print('  heads=', d.get('schema_heads'))
    sys.exit(0)
# 실패 판정은 {status, stage?}다(Manager ADR-51 G-2). stage가 없으면 단계 밖에서 멈췄다.
print('  status=', d.get('status'), 'stage=', d.get('stage', '(단계 밖)'))
sys.exit(1)
"; then
  # 원인은 root 0600 stderr.log에 가린 원문으로 있다. 끝부분을 보인다 — 대화·문서로 옮기지 않는다.
  echo "  --- $OUT/stderr.log (끝 80줄) ---" >&2
  tail -n 80 "$OUT/stderr.log" >&2
  die "rebuild 실패"
fi

say "D. 나머지 사이클 (chain16)"
/root/chain16.sh "$MAP" "$PINVI" "$EB" "$D2U" "$TAG"
