#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

cd "$ROOT_DIR"

IMAGE_REGISTRY="${KOR_TRAVEL_MAP_IMAGE_REGISTRY:-ghcr.io/digitie}"
IMAGE_NAMESPACE="${KOR_TRAVEL_MAP_IMAGE_NAMESPACE:-kor-travel-map}"
GIT_REVISION="$(git rev-parse HEAD)"
if [[ ! "$GIT_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "exact 40-character Git HEAD is required; got $GIT_REVISION" >&2
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
    output_args=(--output "type=oci,dest=${KOR_TRAVEL_MAP_BUILDX_OCI_PATH:-dist/kor-travel-map-images.oci}")
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

  echo "Building ${images[*]} :$IMAGE_TAG for $PLATFORMS"
  docker buildx build \
    --platform "$PLATFORMS" \
    -f "$dockerfile" \
    "${tag_args[@]}" \
    "${output_args[@]}" \
    "$@" \
    .
}

ensure_builder

build_one "$API_IMAGE" docker/api.Dockerfile
# `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`는 VWorld 키로 떨어지지 않는다 — VWorld 키는
# kor-travel-geo가 **상류로 나갈 때** 쓰는 것이고, geo는 그 값을 401(E0401)로 거절한다.
# 사슬로 이어 두면 "설정이 있다"는 착시만 만들고 실패를 첫 요청까지 미룬다(T-VN-H46B).
build_one "$FRONTEND_IMAGE" docker/frontend.Dockerfile \
  --build-arg "KOR_TRAVEL_MAP_GIT_COMMIT=${GIT_REVISION}" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_MAP_API=${NEXT_PUBLIC_KOR_TRAVEL_MAP_API}" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL=${NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL}" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL=${NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL:-http://127.0.0.1:12501}" \
  --build-arg "NEXT_PUBLIC_VWORLD_API_KEY=${NEXT_PUBLIC_VWORLD_API_KEY:-}" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY=${NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY:-}"
build_one "$DAGSTER_IMAGE $DAGSTER_DAEMON_IMAGE" docker/dagster.Dockerfile "${secret_args[@]}"

echo "Built tag: $IMAGE_TAG"
