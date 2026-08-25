#!/usr/bin/env bash
# backup 생성 host script의 공통 durable Docker effect fence 계약.

require_domain_command_effect_identity() {
  local name
  for name in \
    KOR_TRAVEL_MAP_COMMAND_ID \
    KOR_TRAVEL_MAP_COMMAND_OPERATION \
    KOR_TRAVEL_MAP_COMMAND_EFFECT_TOKEN \
    KOR_TRAVEL_MAP_COMMAND_FENCE_PREACQUIRED \
    KOR_TRAVEL_MAP_COMMAND_MARKER_KEY \
    KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND \
    KOR_TRAVEL_MAP_COMMAND_BACKUP_ID \
    KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST; do
    if [[ -z "${!name:-}" ]]; then
      echo "domain command effect identity가 없습니다: $name" >&2
      echo "backup 생성은 admin REST command로만 실행하세요." >&2
      exit 2
    fi
  done
}

domain_command_fence() {
  local action="$1"
  local python_bin
  python_bin="$(select_python)"
  "$python_bin" "$ROOT_DIR/scripts/docker-domain-command-fence.py" \
    "$action" \
    --effect-token "$KOR_TRAVEL_MAP_COMMAND_EFFECT_TOKEN" \
    --command-id "$KOR_TRAVEL_MAP_COMMAND_ID" \
    --operation "$KOR_TRAVEL_MAP_COMMAND_OPERATION" \
    --effect-kind "$KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND" \
    --input-digest "$KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST" \
    --marker-key "$KOR_TRAVEL_MAP_COMMAND_MARKER_KEY" \
    --backup-id "$KOR_TRAVEL_MAP_COMMAND_BACKUP_ID"
}

acquire_domain_command_fence() {
  require_domain_command_effect_identity
  if [[ "${KOR_TRAVEL_MAP_COMMAND_RECOVERY:-0}" != "0" ]]; then
    echo "marker 없는 effect_started recovery는 자동 재실행하지 않습니다." >&2
    exit 4
  fi
  if [[ "$KOR_TRAVEL_MAP_COMMAND_FENCE_PREACQUIRED" != "1" ]]; then
    echo "API가 pre-acquire한 Docker fence evidence가 없습니다." >&2
    exit 2
  fi
  domain_command_fence verify
}

release_domain_command_fence() {
  # Marker write가 성공한 뒤에만 호출해야 한다.
  require_domain_command_effect_identity
  domain_command_fence release
}
