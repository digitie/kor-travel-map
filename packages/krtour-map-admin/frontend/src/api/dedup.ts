/**
 * `/admin/dedup-review/*` 중복 후보 검토 hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, patchJson, pathWithQuery } from "./client";

export type DedupStatus = "pending" | "accepted" | "rejected" | "merged" | "ignored";
export type DedupDecision = "accepted" | "rejected" | "merged" | "ignored";

export interface DedupFeatureRecord {
  feature_id: string;
  name: string;
  kind: string;
  category: string;
  lon: number | null;
  lat: number | null;
  provider: string | null;
  dataset_key: string | null;
}

export interface DedupReviewRecord {
  review_key: string;
  status: string;
  total_score: number;
  name_score: number;
  spatial_score: number;
  category_score: number;
  feature_a: DedupFeatureRecord;
  feature_b: DedupFeatureRecord;
  distance_m: number | null;
  decision_reason: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface DedupReviewListResponse {
  data: {
    items: DedupReviewRecord[];
    next_cursor: string | null;
  };
  meta: {
    count: number;
    page_size: number;
    duration_ms: number;
  };
}

export interface DedupReviewListParams {
  status?: DedupStatus[];
  provider?: string[];
  dataset_key?: string[];
  kind?: string[];
  category?: string[];
  min_score?: number;
  max_score?: number;
  q?: string;
  page_size?: number;
  cursor?: string;
}

export interface DedupReviewDecisionRequest {
  decision: DedupDecision;
  master_feature_id?: string | null;
  decision_reason?: string | null;
  reviewed_by?: string | null;
}

export interface DedupReviewDecisionResponse {
  data: {
    review_key: string;
    decision: DedupDecision;
    changed: boolean;
    master_feature_id: string | null;
    loser_feature_id: string | null;
    merge_id: string | null;
    source_links_moved: number | null;
    source_links_dropped: number | null;
  };
  meta: {
    duration_ms: number;
  };
}

function fetchDedupReviews(
  params: DedupReviewListParams = {},
): Promise<DedupReviewListResponse> {
  return getJson<DedupReviewListResponse>(
    pathWithQuery("/admin/dedup-review", {
      status: params.status,
      provider: params.provider,
      dataset_key: params.dataset_key,
      kind: params.kind,
      category: params.category,
      min_score: params.min_score,
      max_score: params.max_score,
      q: params.q,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

function decideDedupReview(
  reviewKey: string,
  body: DedupReviewDecisionRequest,
): Promise<DedupReviewDecisionResponse> {
  return patchJson<DedupReviewDecisionResponse>(
    `/admin/dedup-review/${encodeURIComponent(reviewKey)}`,
    body,
  );
}

export function useDedupReviews(params: DedupReviewListParams = {}) {
  return useQuery<DedupReviewListResponse, Error>({
    queryKey: ["dedup-review", params],
    queryFn: () => fetchDedupReviews(params),
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
      void queryClient.invalidateQueries({ queryKey: ["dedup-review"] });
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
