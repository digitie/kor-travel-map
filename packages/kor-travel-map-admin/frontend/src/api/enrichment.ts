/**
 * `/v1/admin/features/enrichment-reviews/*` 축제 enrichment 매칭 검토 hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, patchJson, pathWithQuery } from "./client";
import type { components, paths } from "./types";

type EnrichmentSchemas = components["schemas"];
type EnrichmentReviewListQuery = NonNullable<
  paths["/v1/admin/features/enrichment-reviews"]["get"]["parameters"]["query"]
>;

export type EnrichmentStatus = Exclude<
  NonNullable<EnrichmentReviewListQuery["status"]>[number],
  null | undefined
>;
export type EnrichmentDecision =
  EnrichmentSchemas["EnrichmentReviewDecisionRequest"]["decision"];
export type EnrichmentReviewRecord =
  EnrichmentSchemas["EnrichmentReviewRecord"];
export type EnrichmentReviewListResponse =
  EnrichmentSchemas["EnrichmentReviewListResponse"];
export type EnrichmentReviewDetailResponse =
  EnrichmentSchemas["EnrichmentReviewDetailResponse"];
export type EnrichmentReviewListParams = Omit<
  EnrichmentReviewListQuery,
  "provider" | "q" | "status"
> & {
  provider?: string[];
  q?: string;
  status?: EnrichmentStatus[];
};
export type EnrichmentReviewDecisionRequest =
  EnrichmentSchemas["EnrichmentReviewDecisionRequest"];
export type EnrichmentReviewDecisionResponse =
  EnrichmentSchemas["EnrichmentReviewDecisionResponse"];

function fetchEnrichmentReviews(
  params: EnrichmentReviewListParams = {},
  signal?: AbortSignal,
): Promise<EnrichmentReviewListResponse> {
  return getJson<EnrichmentReviewListResponse>(
    pathWithQuery("/v1/admin/features/enrichment-reviews", {
      status: params.status,
      provider: params.provider,
      min_score: params.min_score,
      max_score: params.max_score,
      q: params.q,
      page_size: params.page_size,
      page: params.page,
    }),
    { signal },
  );
}

function decideEnrichmentReview(
  reviewKey: string,
  body: EnrichmentReviewDecisionRequest,
): Promise<EnrichmentReviewDecisionResponse> {
  return patchJson<EnrichmentReviewDecisionResponse>(
    `/v1/admin/features/enrichment-reviews/${encodeURIComponent(reviewKey)}`,
    body,
  );
}

function fetchEnrichmentReviewDetail(
  reviewKey: string,
  signal?: AbortSignal,
): Promise<EnrichmentReviewDetailResponse> {
  return getJson<EnrichmentReviewDetailResponse>(
    `/v1/admin/features/enrichment-reviews/${encodeURIComponent(reviewKey)}`,
    { signal },
  );
}

export function useEnrichmentReviews(params: EnrichmentReviewListParams = {}) {
  return useQuery<EnrichmentReviewListResponse, Error>({
    queryKey: ["enrichment-reviews", params],
    queryFn: ({ signal }) => fetchEnrichmentReviews(params, signal),
    staleTime: 15_000,
  });
}

export function useEnrichmentReviewDetail(reviewKey: string | null) {
  return useQuery<EnrichmentReviewDetailResponse, Error>({
    enabled: reviewKey !== null,
    queryKey: ["enrichment-reviews", "detail", reviewKey],
    queryFn: ({ signal }) => fetchEnrichmentReviewDetail(reviewKey ?? "", signal),
    staleTime: 15_000,
  });
}

export function useEnrichmentDecisionMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    EnrichmentReviewDecisionResponse,
    Error,
    { reviewKey: string; body: EnrichmentReviewDecisionRequest }
  >({
    mutationFn: ({ reviewKey, body }) => decideEnrichmentReview(reviewKey, body),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["enrichment-reviews"] });
      void queryClient.invalidateQueries({
        queryKey: ["enrichment-reviews", "detail"],
      });
      void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      // accept는 1차 feature에 enrichment source를 추가하므로 feature 캐시도 무효화.
      if (data.data.applied) {
        void queryClient.invalidateQueries({ queryKey: ["feature"] });
      }
    },
  });
}
