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
# 남은 일은 셋이다(전부 멱등):
#   0. 인자가 핀 원장과 같은지 본다(`ktdctl pin show` — Manager 내부 파일은 읽지 않는다).
#   1. C7 executor 이미지 라벨이 MAP인지 본다.
#   2. /root/.d2-live.env의 비밀이 아닌 두 키를 갱신하고 퇴역한 두 키를 지운다.
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

say "완료 — 다음은 D1, 그 다음 D2 (같은 체크아웃)"
