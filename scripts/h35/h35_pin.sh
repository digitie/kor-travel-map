#!/usr/bin/env bash
# T-VN-H35 step 1 — 현행 pair를 **비-컨테이너 참조로 고정**한다. 태그만 만든다(가역).
#
# 왜 필요한가: 다음 단계의 candidate build가 `:latest-main` 5개를 그 자리에서 덮는다.
# 그러면 현행 c8ed6164 이미지는 **실행 중 컨테이너에만** 걸려 있게 되고, recreate 후에는
# dangling이 되어 `docker image prune` 한 번에 사라진다. 롤백 대상을 잃는 것이다.
#
# 태그를 붙이는 것은 되돌릴 수 있고 디스크도 쓰지 않는다(같은 layer를 가리킬 뿐).
set -Eeuo pipefail
umask 077

OUT=/home/digitie/h35/rollback-pin.txt
: > "$OUT"

echo "=== 현행 런타임 image ID·revision 기록 ===" | tee -a "$OUT"
for n in kor-travel-map-api-latest kor-travel-map-ui-latest \
         kor-travel-map-dagster-latest kor-travel-map-dagster-daemon-latest \
         pinvi-api-latest; do
  img=$(docker inspect "$n" --format '{{.Image}}' 2>/dev/null || echo "")
  rev=$(docker inspect "$n" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || echo "")
  st=$(docker inspect "$n" --format '{{.State.Status}}' 2>/dev/null || echo "-")
  printf '  %-38s %s  rev=%s  (%s)\n' "$n" "${img:0:19}" "${rev:0:12}" "$st" | tee -a "$OUT"
done

echo | tee -a "$OUT"
echo "=== rollback 전용 immutable tag 부여 ===" | tee -a "$OUT"
# 두 dagster service가 같은 image를 써도 **service별로** 태그한다 — 나중에 각각을 정확히
# 되돌릴 수 있어야 하고, image ID가 같다는 사실에 기대면 안 된다.
for n in kor-travel-map-api-latest kor-travel-map-ui-latest \
         kor-travel-map-dagster-latest kor-travel-map-dagster-daemon-latest \
         pinvi-api-latest; do
  img=$(docker inspect "$n" --format '{{.Image}}' 2>/dev/null || echo "")
  [ -n "$img" ] || { echo "  ** $n image를 못 읽었다"; exit 1; }
  tag="ktm-h35-rollback/${n}:c8ed6164"
  docker tag "$img" "$tag"
  echo "  $tag -> ${img:0:19}" | tee -a "$OUT"
done

echo | tee -a "$OUT"
echo "=== 태그 확인 ===" | tee -a "$OUT"
docker image ls --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep '^ktm-h35-rollback/' | tee -a "$OUT"

echo | tee -a "$OUT"
echo "기록: $OUT"
