#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

cd "$ROOT_DIR"

IMAGE_REGISTRY="${KOR_TRAVEL_MAP_IMAGE_REGISTRY:-ghcr.io/digitie}"
IMAGE_NAMESPACE="${KOR_TRAVEL_MAP_IMAGE_NAMESPACE:-kor-travel-map}"
IMAGE_TAG="${KOR_TRAVEL_MAP_IMAGE_TAG:-$(git rev-parse --short=12 HEAD)}"
PLATFORMS="${KOR_TRAVEL_MAP_DOCKER_PLATFORMS:-linux/amd64,linux/arm64}"
BUILDER="${KOR_TRAVEL_MAP_BUILDX_BUILDER:-kor-travel-map-builder}"
OUTPUT="${KOR_TRAVEL_MAP_BUILDX_OUTPUT:-registry}"

API_IMAGE="${KOR_TRAVEL_MAP_API_IMAGE:-$IMAGE_REGISTRY/$IMAGE_NAMESPACE-api}"
FRONTEND_IMAGE="${KOR_TRAVEL_MAP_FRONTEND_IMAGE:-$IMAGE_REGISTRY/$IMAGE_NAMESPACE-admin}"
DAGSTER_IMAGE="${KOR_TRAVEL_MAP_DAGSTER_IMAGE:-$IMAGE_REGISTRY/$IMAGE_NAMESPACE-dagster}"

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

build_one() {
  local image="$1"
  local dockerfile="$2"
  shift 2
  local image_latest_args=()
  if [[ "${KOR_TRAVEL_MAP_IMAGE_TAG_LATEST:-false}" == "true" ]]; then
    image_latest_args=(-t "$image:latest")
  fi

  echo "Building $image:$IMAGE_TAG for $PLATFORMS"
  docker buildx build \
    --platform "$PLATFORMS" \
    -f "$dockerfile" \
    -t "$image:$IMAGE_TAG" \
    "${image_latest_args[@]}" \
    "${output_args[@]}" \
    "$@" \
    .
}

ensure_builder

build_one "$API_IMAGE" docker/api.Dockerfile
build_one "$FRONTEND_IMAGE" docker/frontend.Dockerfile \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_MAP_API=${NEXT_PUBLIC_KOR_TRAVEL_MAP_API}" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL=${NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL}" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL=${NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL:-http://127.0.0.1:12501}" \
  --build-arg "NEXT_PUBLIC_VWORLD_API_KEY=${NEXT_PUBLIC_VWORLD_API_KEY:-}"
build_one "$DAGSTER_IMAGE" docker/dagster.Dockerfile "${secret_args[@]}"

echo "Built tag: $IMAGE_TAG"
