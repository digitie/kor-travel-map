/**
 * `/admin/enrichment-review/*` 축제 enrichment 매칭 검토 hooks (T-RV-52c).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, patchJson, pathWithQuery } from "./client";
import type { components, paths } from "./types";

type EnrichmentSchemas = components["schemas"];
type EnrichmentReviewListQuery = NonNullable<
  paths["/admin/enrichment-review"]["get"]["parameters"]["query"]
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
export type EnrichmentReviewListParams = Omit<
  EnrichmentReviewListQuery,
  "cursor" | "provider" | "q" | "status"
> & {
  cursor?: string;
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
): Promise<EnrichmentReviewListResponse> {
  return getJson<EnrichmentReviewListResponse>(
    pathWithQuery("/admin/enrichment-review", {
      status: params.status,
      provider: params.provider,
      min_score: params.min_score,
      max_score: params.max_score,
      q: params.q,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

function decideEnrichmentReview(
  reviewKey: string,
  body: EnrichmentReviewDecisionRequest,
): Promise<EnrichmentReviewDecisionResponse> {
  return patchJson<EnrichmentReviewDecisionResponse>(
    `/admin/enrichment-review/${encodeURIComponent(reviewKey)}`,
    body,
  );
}

export function useEnrichmentReviews(params: EnrichmentReviewListParams = {}) {
  return useQuery<EnrichmentReviewListResponse, Error>({
    queryKey: ["enrichment-review", params],
    queryFn: () => fetchEnrichmentReviews(params),
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
      void queryClient.invalidateQueries({ queryKey: ["enrichment-review"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      // accept는 1차 feature에 enrichment source를 추가하므로 feature 캐시도 무효화.
      if (data.data.applied) {
        void queryClient.invalidateQueries({ queryKey: ["feature"] });
      }
    },
  });
}
