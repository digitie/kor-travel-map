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
"$PYTHON" -I "$DRIVER" --rotation-preflight "$MAP" "$PINVI" >/dev/null 2>&1 \
  || die "rotation preflight 거부"
echo "  OK"

say "B. 회전"
/opt/kor-travel-docker-manager/scripts/rotate-pinned-pair "$MAP" "$PINVI" "$REASON" 2>&1 \
  | grep -A 1 'history ' | head -2
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
python3 -c "
import json, sys
d = json.load(open('$OUT/result.json'))
print('  success=', d.get('success'), 'phase=', d.get('phase'),
      'pinset=', d.get('pinset_sha256','')[:16])
print('  heads=', d.get('schema_heads'))
sys.exit(0 if d.get('success') else 1)
" || die "rebuild 실패"

say "D. 나머지 사이클 (chain16)"
/root/chain16.sh "$MAP" "$PINVI" "$EB" "$D2U" "$TAG"
