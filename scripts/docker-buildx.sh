#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

manual_create_key_in_root_env() {
  local wanted_key="$1"
  local line key
  [[ -f "$ENV_FILE" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    [[ "$line" == export\ * ]] && line="${line#export }"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    [[ "$key" == "$wanted_key" ]] && return 0
  done <"$ENV_FILE"
  return 1
}
manual_create_raw="${KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN:-}"
manual_create_digest="${KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256:-}"
reject_exported_manual_feature_create_aliases \
  "$manual_create_raw" \
  "$manual_create_digest"
manual_create_raw=""
manual_create_digest=""

for manual_create_key in \
  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN \
  KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 \
  KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED; do
  if manual_create_key_in_root_env "$manual_create_key"; then
    echo "$manual_create_key must not be configured in root env because build children do not consume M01 credentials" >&2
    exit 1
  fi
  unset "$manual_create_key"
done

cd "$ROOT_DIR"

IMAGE_REGISTRY="${KOR_TRAVEL_MAP_IMAGE_REGISTRY:-ghcr.io/digitie}"
IMAGE_NAMESPACE="${KOR_TRAVEL_MAP_IMAGE_NAMESPACE:-kor-travel-map}"
if ! GIT_REVISION="$(git rev-parse HEAD)"; then
  echo "failed to resolve the Git revision for the build context" >&2
  exit 2
fi
if [[ ! "$GIT_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "exact 40-character Git HEAD is required; got $GIT_REVISION" >&2
  exit 2
fi
if ! GIT_STATUS="$(git status --porcelain=v1 --untracked-files=all)"; then
  echo "failed to verify that the Git worktree is clean" >&2
  exit 2
fi
if [[ -n "$GIT_STATUS" ]]; then
  echo "clean Git worktree is required for an exact source revision build" >&2
  exit 2
fi

# 실제 Docker context는 worktree가 아니라 위에서 고정한 commit의 tracked bytes다.
# ignored 파일 혼입과 세 순차 build 사이의 TOCTOU를 함께 차단한다. directory에 풀지 않고
# 단일 tar를 세 build의 stdin으로 재사용해 materialize 도중 취소와 writer의 cleanup 경합도 없앤다.
BUILD_CONTEXT_ARCHIVE="$(mktemp "${TMPDIR:-/tmp}/kor-travel-map-buildx.XXXXXX.tar")"
# writer 정리는 `$!`를 대입한 변수가 아니라 bash의 job 표(`jobs -p`)로 한다. `git archive … &`가 fork된
# 직후, `archive_pid="$!"`가 실행되기 **전에** TERM이 오면 trap이 먼저 돈다 — 변수는 아직 비어 있어
# writer가 고아로 남는다(부하 중 n150에서 실제로 났다: 테스트의 가짜 git이 몇 시간 CPU를 썼다).
# job 표는 fork와 같은 명령 안에서 채워지고 trap은 명령 사이에서만 돌므로 이 경주가 없다.
cleanup() {
  local writers
  writers="$(jobs -p)"
  if [[ -n "$writers" ]]; then
    # shellcheck disable=SC2086 # pid 목록을 낱개 인자로 넘긴다.
    kill $writers >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    wait $writers >/dev/null 2>&1 || true
  fi
  rm -f -- "$BUILD_CONTEXT_ARCHIVE"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
git archive --format=tar "$GIT_REVISION" >"$BUILD_CONTEXT_ARCHIVE" &
if wait "$!"; then
  archive_status=0
else
  archive_status="$?"
fi
trap - INT TERM
if [[ "$archive_status" -ne 0 ]]; then
  echo "failed to materialize the exact Git revision build context" >&2
  exit 2
fi

IMAGE_TAG="${KOR_TRAVEL_MAP_IMAGE_TAG:-${GIT_REVISION:0:12}}"
PLATFORMS="${KOR_TRAVEL_MAP_DOCKER_PLATFORMS:-linux/amd64,linux/arm64}"
BUILDER="${KOR_TRAVEL_MAP_BUILDX_BUILDER:-kor-travel-map-builder}"
OUTPUT="${KOR_TRAVEL_MAP_BUILDX_OUTPUT:-registry}"

API_IMAGE="${KOR_TRAVEL_MAP_API_IMAGE:-$IMAGE_REGISTRY/$IMAGE_NAMESPACE-api}"
FRONTEND_IMAGE="${KOR_TRAVEL_MAP_FRONTEND_IMAGE:-$IMAGE_REGISTRY/$IMAGE_NAMESPACE-admin}"
DAGSTER_IMAGE="${KOR_TRAVEL_MAP_DAGSTER_IMAGE:-$IMAGE_REGISTRY/$IMAGE_NAMESPACE-dagster}"
# daemon은 dagster와 **같은 Dockerfile·같은 build args**를 쓰고 command만 다르다
# (compose의 두 build 블록이 동일하다). 그런데 이 스크립트는 오래 "map 이미지는 3개"라는
# 잘못된 모델을 성문화하고 있었고, `docker-build.sh:12`는 4개를 제대로 나열해 두 파일이
# 서로 모순됐다. 2026-08-13 prod 재빌드에서 정확히 그 누락이 나 daemon만 8일 묵은 코드로
# 남았고, TVN33 커토버 이후 `feature_update_request_queue_sensor`가 30초마다 죽었다
# (dagster metadata DB 실측 consecutive_failure_count=2020).
DAGSTER_DAEMON_IMAGE="${KOR_TRAVEL_MAP_DAGSTER_DAEMON_IMAGE:-$IMAGE_REGISTRY/$IMAGE_NAMESPACE-dagster-daemon}"

output_args=()
case "$OUTPUT" in
  registry)
    output_args=(--push)
    ;;
  docker)
    if [[ "$PLATFORMS" == *,* ]]; then
      echo "KOR_TRAVEL_MAP_BUILDX_OUTPUT=docker supports one platform only; got $PLATFORMS" >&2
      exit 2
    fi
    output_args=(--load)
    ;;
  oci)
    if [[ ${KOR_TRAVEL_MAP_BUILDX_OCI_PATH+x} == x ]]; then
      echo "KOR_TRAVEL_MAP_BUILDX_OCI_PATH was removed; use KOR_TRAVEL_MAP_BUILDX_OCI_DIR" >&2
      exit 2
    fi
    OCI_OUTPUT_DIR="${KOR_TRAVEL_MAP_BUILDX_OCI_DIR:-dist/kor-travel-map-images-oci}"
    mkdir -p "$OCI_OUTPUT_DIR"
    ;;
  *)
    echo "unsupported KOR_TRAVEL_MAP_BUILDX_OUTPUT=$OUTPUT (registry|docker|oci)" >&2
    exit 2
    ;;
esac

secret_args=()
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  secret_args+=(--secret id=github_token,env=GITHUB_TOKEN)
fi

ensure_builder() {
  if docker buildx inspect "$BUILDER" >/dev/null 2>&1; then
    docker buildx use "$BUILDER" >/dev/null
  else
    docker buildx create --name "$BUILDER" --use >/dev/null
  fi
  docker buildx inspect --bootstrap >/dev/null
}

# 첫 인자는 **이미지 하나 이상**을 공백으로 구분한 목록이다. 같은 Dockerfile을 여러
# 이름으로 배포해야 할 때 build를 두 번 돌리지 않고 태그만 더한다 — 두 번 돌리면 두
# 이미지가 같다는 보장이 없고(캐시 미스·비결정적 레이어), 하필 그 "같다"가 dagster와
# dagster-daemon에서는 요구사항이다. daemon은 자기 이미지 안의 패키지를 in-process로
# 로드하므로 code server와 코드가 어긋나면 그대로 사고다(2026-08-13).
build_one() {
  local -a images
  read -r -a images <<<"$1"
  local dockerfile="$2"
  shift 2
  local -a tag_args=()
  local -a build_output_args=("${output_args[@]}")
  local image
  for image in "${images[@]}"; do
    tag_args+=(-t "$image:$IMAGE_TAG")
    if [[ "${KOR_TRAVEL_MAP_IMAGE_TAG_LATEST:-false}" == "true" ]]; then
      tag_args+=(-t "$image:latest")
    fi
  done
  if [[ ${#tag_args[@]} -eq 0 ]]; then
    echo "build_one: 이미지 목록이 비었다 (dockerfile=$dockerfile)" >&2
    exit 2
  fi
  if [[ "$OUTPUT" == "oci" ]]; then
    local archive_name="${dockerfile##*/}"
    archive_name="${archive_name%.Dockerfile}"
    build_output_args=(
      --output "type=oci,dest=${OCI_OUTPUT_DIR}/${archive_name}-${IMAGE_TAG}.oci"
    )
  fi

  echo "Building ${images[*]} :$IMAGE_TAG for $PLATFORMS"
  docker buildx build \
    --platform "$PLATFORMS" \
    -f "$dockerfile" \
    "${tag_args[@]}" \
    "${build_output_args[@]}" \
    "$@" \
    --build-arg "KOR_TRAVEL_MAP_GIT_COMMIT=${GIT_REVISION}" \
    --label "org.opencontainers.image.revision=${GIT_REVISION}" \
    - <"$BUILD_CONTEXT_ARCHIVE"
}

ensure_builder

build_one "$API_IMAGE" docker/api.Dockerfile
build_one "$FRONTEND_IMAGE" docker/frontend.Dockerfile \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_MAP_API=${NEXT_PUBLIC_KOR_TRAVEL_MAP_API}" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL=${NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL}" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL=${NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL:-http://127.0.0.1:12501}" \
  --build-arg "NEXT_PUBLIC_VWORLD_API_KEY=${NEXT_PUBLIC_VWORLD_API_KEY:-}"
build_one "$DAGSTER_IMAGE $DAGSTER_DAEMON_IMAGE" docker/dagster.Dockerfile "${secret_args[@]}"

echo "Built tag: $IMAGE_TAG"
