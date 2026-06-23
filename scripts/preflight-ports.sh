#!/usr/bin/env bash
set -euo pipefail

# dev 기동 전 고정 포트 가드 (run-admin-stack.sh / docker-up.sh가 호출).
#
# 정책(사용자 지시): 고정 포트가 **이미 사용 중이면 새 포트로 열지 않는다**. prod 환경
# 유무와 관계없이 기존 listener를 **강제종료할지 사용자에게 묻고**, 강제종료하지 않으면
# **dev 기동을 중지**한다(기존 서비스/prod 보존).
#
# 비대화형(no TTY: CI/스크립트/agent)에서는 기본이 **중지(강제종료 안 함)**다.
# 강제종료를 원하면 `KOR_TRAVEL_MAP_FORCE_KILL_PORTS=1`을 명시한다.
# (반대로 0/false면 프롬프트 없이 곧장 중지.)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 탐지 함수(find_*_for_port / port_has_listener / stop_fixed_ports)를 재사용한다.
# stop-fixed-ports.sh는 source되면 강제종료 main을 실행하지 않는다(BASH_SOURCE 가드).
# (stop-fixed-ports.sh가 load-env.sh를 source하므로 포트 env가 채워진다.)
# shellcheck source=stop-fixed-ports.sh
source "$ROOT_DIR/scripts/stop-fixed-ports.sh"

normalize_bool() {
  case "${1,,}" in
    1 | y | yes | true) echo 1 ;;
    0 | n | no | false) echo 0 ;;
    *) echo "" ;;
  esac
}

# no-arg 기본 가드 포트. API/admin/Dagster는 항상 포함하고, RustFS(API/console)는
# 로컬 compose로 띄울 때만 포함한다(stop-fixed-ports.sh의 5포트 기본과 정렬, #507).
#
# RustFS를 kor-travel-docker-manager 공유 인스턴스로 쓰는 모드
# (KOR_TRAVEL_MAP_OBJECT_STORE_EXTERNAL=true 또는 KOR_TRAVEL_MAP_INFRA_EXTERNAL=true)에서는
# 로컬에서 RustFS를 띄우지 않으므로 12101/12105를 가드/강제종료 대상에서 제외한다
# (공유 인스턴스를 죽이면 안 된다).
#
# 5432(Postgres) 정책: host 모드의 5432는 kor-travel-docker-manager가 소유한 **공유**
# PostGIS다. 의도적으로 preflight 가드/강제종료 대상에서 제외한다(공유 DB 보존).
# 5432에 비공유 충돌 listener가 있으면 자동으로 죽이지 않고 사용자가 직접 해결한다.
object_store_external="$(normalize_bool "${KOR_TRAVEL_MAP_OBJECT_STORE_EXTERNAL:-}")"
infra_external="$(normalize_bool "${KOR_TRAVEL_MAP_INFRA_EXTERNAL:-}")"

ports=("$@")
if [[ "${#ports[@]}" -eq 0 ]]; then
  ports=(
    "$KOR_TRAVEL_MAP_API_PORT"
    "$KOR_TRAVEL_MAP_ADMIN_WEB_PORT"
    "$KOR_TRAVEL_MAP_DAGSTER_PORT"
  )
  if [[ "$object_store_external" != "1" && "$infra_external" != "1" ]]; then
    ports+=(
      "$KOR_TRAVEL_MAP_RUSTFS_API_PORT"
      "$KOR_TRAVEL_MAP_RUSTFS_CONSOLE_PORT"
    )
  else
    echo "preflight: 공유 RustFS 모드 — 12101/12105 가드 생략 (OBJECT_STORE_EXTERNAL/INFRA_EXTERNAL)." >&2
  fi
fi

occupied=()
for port in "${ports[@]}"; do
  if port_has_listener "$port"; then
    occupied+=("$port")
  fi
done

if [[ "${#occupied[@]}" -eq 0 ]]; then
  echo "preflight: dev 고정 포트 비어 있음 (${ports[*]})"
  exit 0
fi

echo "preflight: 다음 고정 포트가 이미 사용 중입니다: ${occupied[*]}" >&2
for port in "${occupied[@]}"; do
  detail=""
  pids="$(find_pids_for_port "$port" | tr '\n' ' ')"
  [[ -n "${pids// /}" ]] && detail+="host-pid=${pids%% } "
  containers="$(find_docker_containers_for_port "$port" | tr '\n' ' ')"
  [[ -n "${containers// /}" ]] && detail+="docker=${containers%% } "
  echo "  - port $port: ${detail:-사용 중}" >&2
done

force="$(normalize_bool "${KOR_TRAVEL_MAP_FORCE_KILL_PORTS:-}")"
if [[ -z "$force" ]]; then
  if [[ -t 0 ]]; then
    printf '강제종료하고 dev를 기동할까요? 기존 서비스(혹은 prod)가 종료됩니다 [y/N] ' >&2
    read -r answer || answer=""
    force="$(normalize_bool "$answer")"
    [[ -z "$force" ]] && force=0
  else
    # 비대화형: 안전 기본값 = 강제종료 안 함(중지).
    echo "preflight: 비대화형 — 강제종료를 묻지 않고 중지합니다 (강제종료하려면 KOR_TRAVEL_MAP_FORCE_KILL_PORTS=1)." >&2
    force=0
  fi
fi

if [[ "$force" == "1" ]]; then
  echo "preflight: 강제종료 진행 (${occupied[*]})" >&2
  stop_fixed_ports "${occupied[@]}"
  exit 0
fi

echo "preflight: 강제종료하지 않음 — dev 기동을 중지합니다. 기존 서비스/포트를 보존합니다." >&2
echo "  새 포트로 열지 않습니다. 명시적으로 정리하려면 'npm run ports:stop',"  >&2
echo "  또는 프롬프트 없이 강제종료하려면 'KOR_TRAVEL_MAP_FORCE_KILL_PORTS=1'을 설정하세요." >&2
exit 1
