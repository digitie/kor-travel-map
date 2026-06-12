/**
 * `@kor-travel-map/user-client` — kor-travel-map **user-facing** OpenAPI 타입 (T-210e).
 *
 * `packages/kor-travel-map-admin/openapi.user.json`(기계 정본, ADR-048/T-216g)에서
 * `openapi-typescript`로 생성한 `./types.ts`를 named alias와 함께 노출한다.
 * 런타임 코드는 없다 — HTTP client는 소비자 소유다(TripMate는 수기 httpx/fetch,
 * krtour 권고). prose 계약은 `docs/rest-api.md` + `docs/tripmate-rest-api.md`.
 *
 * 소비 방법(downstream, 예: TripMate frontend):
 * 1. **vendoring** — `src/types.ts`(+본 파일)를 복사해 pin. drift는 본 repo CI
 *    (`gen:types:check`)가 spec과 산출물을 고정하므로 commit hash 기준으로 안전.
 * 2. **자체 codegen** — 같은 `openapi.user.json`을 같은 openapi-typescript 버전으로
 *    생성. 본 패키지는 그 결과가 본 파일의 표면 단언과 호환됨을 CI에서 보증한다.
 */

import type { components, paths } from "./types";

export type { components, operations, paths } from "./types";

// ── named alias — 소비자가 components["schemas"][...]를 직접 쓰지 않게 ──

type Schemas = components["schemas"];

export type Meta = Schemas["Meta"];
export type PageMeta = Schemas["PageMeta"];
export type ClusterMeta = Schemas["ClusterMeta"];

export type FeatureSummary = Schemas["FeatureSummary"];
export type FeatureDetail = Schemas["FeatureDetailResponse"];
export type FeatureDetailEnvelope = Schemas["FeatureDetailEnvelopeResponse"];
export type ClusterSummary = Schemas["ClusterSummary"];
export type FeaturesInBoundsResponse = Schemas["FeaturesInBoundsResponse"];
export type FeatureSearchResponse = Schemas["FeatureSearchResponse"];
export type FeaturesNearbyResponse = Schemas["FeaturesNearbyResponse"];
export type FeaturesNearbyByTargetResponse =
  Schemas["FeaturesNearbyByTargetResponse"];
export type NearbyFeatureSummary = Schemas["NearbyFeatureSummary"];
export type FeatureBatchRequest = Schemas["FeatureBatchRequest"];
export type FeatureBatchResponse = Schemas["FeatureBatchResponse"];
export type FeatureWeatherResponse = Schemas["FeatureWeatherResponse"];
export type CategoriesResponse = Schemas["CategoriesResponse"];
export type CategorySummary = Schemas["CategorySummary"];
export type ProviderLastSyncResponse = Schemas["ProviderLastSyncResponse"];
export type ProvidersFreshnessResponse = Schemas["ProvidersFreshnessResponse"];
export type BeachPublicView = Schemas["BeachPublicView"];
export type FestivalPublicView = Schemas["FestivalPublicView"];
export type PublicBeachListResponse = Schemas["PublicBeachListResponse"];
export type PublicFestivalMonthlyResponse =
  Schemas["PublicFestivalMonthlyResponse"];
export type PublicMapMarkerLayerResponse =
  Schemas["PublicMapMarkerLayerResponse"];

// ── 컴파일 타임 표면 단언 (codegen 호환성 게이트) ──
// ADR-048 계약 불변식이 spec 변경으로 깨지면 본 패키지 tsc가 먼저 실패한다.
// (예: batch found→items 회귀, meta.page 제거, lon/lat 중첩화, 경로 rename)

type _Assert<T extends true> = T;
// 비-distributive — union K의 **모든** 멤버가 keyof T여야 true.
// 실패 시 never가 아니라 false를 반환해야 _Assert 제약이 실제로 깨진다
// (never는 bottom type이라 `extends true`를 통과해 단언이 무력화된다).
type _Has<T, K> = [K] extends [keyof T] ? true : false;

// batch: data = { found: id-keyed map, missing: [] } — list `items`와 키 분리(T-216e).
type _BatchHasFound = _Assert<
  _Has<FeatureBatchResponse["data"], "found" | "missing">
>;
// pagination은 meta.page (data.next_cursor 폐기, ADR-048 #2/#12).
type _MetaHasPage = _Assert<_Has<Meta, "page">>;
type _PageHasNextCursor = _Assert<
  _Has<NonNullable<Meta["page"]>, "next_cursor" | "page_size" | "total">
>;
// 좌표는 평면 lon/lat (중첩 coord{} 아님, ADR-048 #10).
type _SummaryHasFlatLonLat = _Assert<_Has<FeatureSummary, "lon" | "lat">>;
// in-bounds payload = clusters/items만, granularity는 meta.cluster(#12).
type _InBoundsPayload = _Assert<
  _Has<FeaturesInBoundsResponse["data"], "clusters" | "items">
>;
type _MetaHasCluster = _Assert<_Has<Meta, "cluster">>;
// /v1 경로 표면 — clean cut(ADR-048 #1). rename 시 컴파일 실패.
type _PathsStable = _Assert<
  _Has<
    paths,
    | "/v1/features/in-bounds"
    | "/v1/features/search"
    | "/v1/features/nearby"
    | "/v1/features/batch"
    | "/v1/features/{feature_id}"
    | "/v1/features/{feature_id}/weather"
    | "/v1/public/beaches"
    | "/v1/public/beaches/map-markers"
    | "/v1/public/beaches/{feature_id}"
    | "/v1/public/festivals/monthly"
    | "/v1/public/festivals/map-markers"
    | "/v1/public/festivals/{feature_id}"
    | "/v1/categories"
    | "/v1/providers"
    | "/v1/providers/{provider}/last-sync"
    | "/health"
    | "/version"
  >
>;

// noUnusedLocals 회피용 도달 불가 참조 (타입 단언만 목적).
export type _SurfaceAssertions = [
  _BatchHasFound,
  _MetaHasPage,
  _PageHasNextCursor,
  _SummaryHasFlatLonLat,
  _InBoundsPayload,
  _MetaHasCluster,
  _PathsStable,
];
