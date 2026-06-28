/**
 * `/v1/admin/dedup-reviews/*` 중복 후보 검토 hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, patchJson, pathWithQuery } from "./client";
import type { components, paths } from "./types";

type DedupSchemas = components["schemas"];
type DedupReviewListQuery = NonNullable<
  paths["/v1/admin/dedup-reviews"]["get"]["parameters"]["query"]
>;

export type DedupStatus = Exclude<
  NonNullable<DedupReviewListQuery["status"]>[number],
  null | undefined
>;
export type DedupDecision =
  DedupSchemas["DedupReviewDecisionRequest"]["decision"];
export type DedupFeatureRecord = DedupSchemas["DedupFeatureRecord"];
export type DedupReviewRecord = DedupSchemas["DedupReviewRecord"];
export type DedupReviewListResponse =
  DedupSchemas["DedupReviewListResponse"];
export type DedupReviewDetailResponse =
  DedupSchemas["DedupReviewDetailResponse"];
export type DedupReviewListParams = Omit<
  DedupReviewListQuery,
  | "category"
  | "dataset_key"
  | "kind"
  | "provider"
  | "q"
  | "status"
> & {
  category?: string[];
  dataset_key?: string[];
  kind?: string[];
  provider?: string[];
  q?: string;
  status?: DedupStatus[];
};
export type DedupReviewDecisionRequest =
  DedupSchemas["DedupReviewDecisionRequest"];
export type DedupReviewDecisionResponse =
  DedupSchemas["DedupReviewDecisionResponse"];

function fetchDedupReviews(
  params: DedupReviewListParams = {},
  signal?: AbortSignal,
): Promise<DedupReviewListResponse> {
  return getJson<DedupReviewListResponse>(
    pathWithQuery("/v1/admin/dedup-reviews", {
      status: params.status,
      provider: params.provider,
      dataset_key: params.dataset_key,
      kind: params.kind,
      category: params.category,
      min_score: params.min_score,
      max_score: params.max_score,
      q: params.q,
      page_size: params.page_size,
      page: params.page,
    }),
    { signal },
  );
}

function decideDedupReview(
  reviewKey: string,
  body: DedupReviewDecisionRequest,
): Promise<DedupReviewDecisionResponse> {
  return patchJson<DedupReviewDecisionResponse>(
    `/v1/admin/dedup-reviews/${encodeURIComponent(reviewKey)}`,
    body,
  );
}

function fetchDedupReviewDetail(
  reviewKey: string,
  signal?: AbortSignal,
): Promise<DedupReviewDetailResponse> {
  return getJson<DedupReviewDetailResponse>(
    `/v1/admin/dedup-reviews/${encodeURIComponent(reviewKey)}`,
    { signal },
  );
}

export function useDedupReviews(params: DedupReviewListParams = {}) {
  return useQuery<DedupReviewListResponse, Error>({
    queryKey: ["dedup-reviews", params],
    queryFn: ({ signal }) => fetchDedupReviews(params, signal),
    staleTime: 15_000,
  });
}

export function useDedupReviewDetail(reviewKey: string | null) {
  return useQuery<DedupReviewDetailResponse, Error>({
    enabled: reviewKey !== null,
    queryKey: ["dedup-reviews", "detail", reviewKey],
    queryFn: ({ signal }) => fetchDedupReviewDetail(reviewKey ?? "", signal),
    staleTime: 15_000,
  });
}

export function useDedupDecisionMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    DedupReviewDecisionResponse,
    Error,
    { reviewKey: string; body: DedupReviewDecisionRequest }
  >({
    mutationFn: ({ reviewKey, body }) => decideDedupReview(reviewKey, body),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["dedup-reviews"] });
      void queryClient.invalidateQueries({ queryKey: ["dedup-reviews", "detail"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      if (data.data.master_feature_id) {
        void queryClient.invalidateQueries({
          queryKey: ["feature", data.data.master_feature_id],
        });
      }
      if (data.data.loser_feature_id) {
        void queryClient.invalidateQueries({
          queryKey: ["feature", data.data.loser_feature_id],
        });
      }
    },
  });
}
