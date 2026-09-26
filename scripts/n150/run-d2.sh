#!/bin/bash
# D2(admin feature live acceptance)를 핀된 SHA의 평범한 체크아웃에서 돌린다.
#
#   run-d2.sh MAP_SHA40
#
# 정본은 저장소의 `scripts/n150/run-d2.sh`다(ADR-102 결정 6). chain16이 systemd-run
# unit으로 부른다. 체크아웃은 chain16의 D1 단계가 푼 `/home/digitie/ktm-c7-$MAP`이다 —
# 종전의 root 소유 스냅샷(`/usr/local/lib/...`)은 더 쓰지 않는다. cwd는 compose project
# 디렉터리여야 한다(러너가 `docker compose --project-directory "$PWD"`를 쓴다).
set -uo pipefail

MAP="${1:?MAP}"
[[ "$MAP" =~ ^[0-9a-f]{40}$ ]] || { echo "!! MAP revision이 40-hex가 아니다" >&2; exit 2; }
SRC="/home/digitie/ktm-c7-$MAP"
RUNNER="$SRC/scripts/run-admin-feature-live-acceptance.sh"
[ -f "$RUNNER" ] || { echo "!! D2 러너가 없다: $RUNNER (chain16 D1이 먼저 푼다)" >&2; exit 2; }

set -a; . /root/.d2-live.env; set +a
# env가 가리키는 commit과 이 체크아웃이 같은 사이클이어야 한다. repin을 건너뛰고
# 돌리면 러너는 새 트리에서 옛 commit을 기대하게 된다.
[ "${E2E_C7_EXPECTED_GIT_COMMIT:-}" = "$MAP" ] ||
  { echo "!! .d2-live.env의 E2E_C7_EXPECTED_GIT_COMMIT가 $MAP 이 아니다 (repin 필요)" >&2; exit 2; }

cd /opt/kor-travel-docker-manager || { echo "!! compose project 디렉터리로 가지 못했다" >&2; exit 2; }
/bin/bash "$RUNNER" run
status=$?
echo "runner exit=$status"
exit "$status"
