import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  domainCommandSlot,
  getJson,
  pathWithQuery,
  postJson,
  withDomainIdempotencySubmission,
} from "./client";
import type { components, paths } from "./types";

type Schemas = components["schemas"];
type CandidateListQuery = NonNullable<
  paths["/v1/admin/theme-feature-candidates"]["get"]["parameters"]["query"]
>;

export type ThemeCandidate = Schemas["AdminThemeCandidateView"];
export type ThemeCandidatePageResponse =
  Schemas["AdminThemeCandidatePageResponse"];
export type ThemeCandidateResponse = Schemas["AdminThemeCandidateResponse"];
export type ThemeCandidateTransition =
  Schemas["AdminThemeCandidateTransitionView"];
export type ThemeCandidateTransitionPageResponse =
  Schemas["AdminThemeCandidateTransitionPageResponse"];
export type ThemeCandidatePromoteRequest =
  Schemas["ThemeCandidatePromoteRequest"];
export type ThemeCandidateRejectRequest = Schemas["ThemeCandidateRejectRequest"];
export type ThemeCandidateCommandResponse =
  Schemas["ThemeCandidateCommandResponse"];
export type ThemeCandidateListParams = CandidateListQuery;

function invalidateCandidates(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["theme-candidates"] });
  void queryClient.invalidateQueries({ queryKey: ["curation-collections"] });
  void queryClient.invalidateQueries({ queryKey: ["curation-collection"] });
  void queryClient.invalidateQueries({ queryKey: ["public-curations"] });
}

function fetchCandidates(
  params: ThemeCandidateListParams,
  signal?: AbortSignal,
): Promise<ThemeCandidatePageResponse> {
  return getJson<ThemeCandidatePageResponse>(
    pathWithQuery("/v1/admin/theme-feature-candidates", {
      rule_id: params.rule_id,
      theme_id: params.theme_id,
      source_id: params.source_id,
      review_state: params.review_state,
      eligibility_present: params.eligibility_present,
      feature_id: params.feature_id,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
    { signal },
  );
}

export function useThemeCandidates(params: ThemeCandidateListParams) {
  return useQuery<ThemeCandidatePageResponse, Error>({
    queryKey: ["theme-candidates", "list", params] as const,
    queryFn: ({ signal }) => fetchCandidates(params, signal),
    staleTime: 15_000,
  });
}

export function useThemeCandidate(candidateId: string | null) {
  return useQuery<ThemeCandidateResponse, Error>({
    queryKey: ["theme-candidates", "detail", candidateId] as const,
    queryFn: ({ signal }) =>
      getJson<ThemeCandidateResponse>(
        `/v1/admin/theme-feature-candidates/${encodeURIComponent(candidateId ?? "")}`,
        { signal },
      ),
    enabled: candidateId !== null,
    staleTime: 15_000,
  });
}

export function useThemeCandidateTransitions(candidateId: string | null) {
  return useQuery<ThemeCandidateTransitionPageResponse, Error>({
    queryKey: ["theme-candidates", "transitions", candidateId] as const,
    queryFn: ({ signal }) =>
      getJson<ThemeCandidateTransitionPageResponse>(
        pathWithQuery(
          `/v1/admin/theme-feature-candidates/${encodeURIComponent(
            candidateId ?? "",
          )}/transitions`,
          { page_size: 100 },
        ),
        { signal },
      ),
    enabled: candidateId !== null,
    staleTime: 15_000,
  });
}

export function useRejectThemeCandidateMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    ThemeCandidateCommandResponse,
    Error,
    {
      candidateId: string;
      candidateEtag: string;
      body: ThemeCandidateRejectRequest;
    }
  >({
    mutationFn: ({ candidateId, candidateEtag, body }) =>
      withDomainIdempotencySubmission(
        domainCommandSlot("admin.theme-feature-candidate.reject", candidateId),
        { candidateId, candidateEtag, body },
        (submission, idempotencyKey) =>
          postJson<ThemeCandidateCommandResponse>(
            `/v1/admin/theme-feature-candidates/${encodeURIComponent(
              submission.candidateId,
            )}/reject`,
            submission.body,
            {
              headers: {
                "Idempotency-Key": idempotencyKey,
                "If-Match": submission.candidateEtag,
              },
            },
          ),
      ),
    onSettled: () => invalidateCandidates(queryClient),
  });
}

export function usePromoteThemeCandidateMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    ThemeCandidateCommandResponse,
    Error,
    {
      candidateId: string;
      candidateEtag: string;
      body: ThemeCandidatePromoteRequest;
    }
  >({
    mutationFn: ({ candidateId, candidateEtag, body }) =>
      withDomainIdempotencySubmission(
        domainCommandSlot("admin.theme-feature-candidate.promote", candidateId),
        { candidateId, candidateEtag, body },
        (submission, idempotencyKey) =>
          postJson<ThemeCandidateCommandResponse>(
            `/v1/admin/theme-feature-candidates/${encodeURIComponent(
              submission.candidateId,
            )}/promote`,
            submission.body,
            {
              headers: {
                "Idempotency-Key": idempotencyKey,
                "If-Match": submission.candidateEtag,
              },
            },
          ),
      ),
    onSettled: () => invalidateCandidates(queryClient),
  });
}
