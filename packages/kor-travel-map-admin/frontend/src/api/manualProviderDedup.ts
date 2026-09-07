/**
 * `/v1/admin/manual-provider-dedup-cases/*` — T-VN-M05 수동/provider 중복 판정 hooks.
 *
 * **generic dedup 화면(`api/dedup.ts`)과 공유하지 않는다.** M05는 계약도 실패
 * 양상도 다르다 — 판정이 `merged`/`manual_retired`일 때 **파괴적**이고, 낙관적
 * 동시성을 세 값(`expected_case_fingerprint`·두 `row_revision`)으로 걸며, 그
 * 결과가 외부 consumer에게 전파된다. 화면을 재사용하면 그 차이가 사라진다
 * (인수조건 M05-5, 설계 §paired rollout과 검증 4).
 */

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

type CaseListQuery = NonNullable<
  paths["/v1/admin/manual-provider-dedup-cases"]["get"]["parameters"]["query"]
>;

export type ManualProviderDedupStatus = NonNullable<CaseListQuery["status"]>;
export type ManualProviderDedupDecision =
  Schemas["ManualProviderDedupCaseDecisionInput"]["decision"];
export type ManualProviderDedupCase = Schemas["ManualProviderDedupCaseData"];
export type ManualProviderDedupCaseDetail =
  Schemas["ManualProviderDedupCaseDetailData"];
export type ManualProviderDedupPageResponse =
  Schemas["ManualProviderDedupCasePageResponse"];
export type ManualProviderDedupDetailResponse =
  Schemas["ManualProviderDedupCaseDetailResponse"];
export type ManualProviderDedupDecisionInput =
  Schemas["ManualProviderDedupCaseDecisionInput"];
export type ManualProviderDedupDecisionResponse =
  Schemas["ManualProviderDedupCaseDecisionResponse"];
export type ManualProviderDedupSubscription =
  Schemas["FeatureReferenceReconciliationSubscriptionDeliveryData"];

const CASES_PATH = "/v1/admin/manual-provider-dedup-cases";

/** 파괴적 판정 — 이 둘은 수동 Feature를 되돌릴 수 없게 바꾼다. */
export const DESTRUCTIVE_DECISIONS: readonly ManualProviderDedupDecision[] = [
  "merged",
  "manual_retired",
];

export function isDestructiveDecision(
  decision: ManualProviderDedupDecision,
): boolean {
  return DESTRUCTIVE_DECISIONS.includes(decision);
}

export const manualProviderDedupKeys = {
  all: ["manual-provider-dedup"] as const,
  list: (params: ManualProviderDedupListParams) =>
    [...manualProviderDedupKeys.all, "list", params] as const,
  detail: (caseId: string) =>
    [...manualProviderDedupKeys.all, "detail", caseId] as const,
};

export type ManualProviderDedupListParams = {
  status?: ManualProviderDedupStatus;
  after_created_at?: string | null;
  after_case_id?: string | null;
  limit?: number;
};

export function useManualProviderDedupCases(
  params: ManualProviderDedupListParams = {},
) {
  return useQuery({
    queryKey: manualProviderDedupKeys.list(params),
    queryFn: ({ signal }) =>
      getJson<ManualProviderDedupPageResponse>(
        pathWithQuery(CASES_PATH, {
          status: params.status ?? "pending",
          after_created_at: params.after_created_at ?? undefined,
          after_case_id: params.after_case_id ?? undefined,
          limit: params.limit ?? undefined,
        }),
        { signal },
      ),
  });
}

export function useManualProviderDedupCase(caseId: string | null) {
  return useQuery({
    queryKey: manualProviderDedupKeys.detail(caseId ?? ""),
    enabled: caseId !== null && caseId !== "",
    queryFn: ({ signal }) =>
      getJson<ManualProviderDedupDetailResponse>(
        `${CASES_PATH}/${encodeURIComponent(caseId ?? "")}`,
        { signal },
      ),
  });
}

/**
 * 판정 제출.
 *
 * 멱등 slot을 **case_id로** 고정한다 — 같은 case에 대한 재제출이 새 판정을
 * 만들지 않아야 한다. submission fingerprint가 달라지면
 * `DomainIdempotencySubmissionMismatchError`가 나므로, 사용자가 reason이나
 * decision을 바꾼 뒤 다시 누르면 그것이 **다른 명령**임이 드러난다.
 */
export function useSubmitManualProviderDedupDecision(caseId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (submission: ManualProviderDedupDecisionInput) =>
      withDomainIdempotencySubmission(
        domainCommandSlot("manual-provider-dedup-decision", caseId),
        submission,
        (payload, idempotencyKey) =>
          postJson<ManualProviderDedupDecisionResponse>(
            `${CASES_PATH}/${encodeURIComponent(caseId)}/decisions`,
            payload,
            { headers: { "Idempotency-Key": idempotencyKey } },
          ),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: manualProviderDedupKeys.all,
      });
    },
  });
}

/**
 * principal별 미확인(unacked) 경과 시간.
 *
 * 계약이 그 값을 `oldest_unacked_at`으로 직접 준다 — 여기서 다시 유도하지 않는다.
 * `null`이면 밀린 것이 없다는 뜻이므로 목록에서 뺀다.
 *
 * **정렬은 오래된 순이다.** 가장 오래 밀린 consumer가 위에 와야 판정의 파급을 보고
 * 결정할 수 있고, 그것이 이 값을 화면에 두는 이유다(인수조건 M05-5).
 */
export function unackedAges(
  subscriptions: readonly ManualProviderDedupSubscription[],
  now: number,
): Array<{ principalId: string; ageMs: number; oldestUnackedAt: string }> {
  return subscriptions
    .flatMap((subscription) =>
      subscription.oldest_unacked_at
        ? [
            {
              principalId: subscription.principal_id,
              ageMs: Math.max(0, now - Date.parse(subscription.oldest_unacked_at)),
              oldestUnackedAt: subscription.oldest_unacked_at,
            },
          ]
        : [],
    )
    .sort((left, right) => right.ageMs - left.ageMs);
}

/** `1일 3시간` 꼴. 밀린 시간은 초 단위 정밀도가 필요 없다. */
export function formatUnackedAge(ageMs: number): string {
  const totalMinutes = Math.floor(ageMs / 60_000);
  const days = Math.floor(totalMinutes / 1_440);
  const hours = Math.floor((totalMinutes % 1_440) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) {
    return `${days}일 ${hours}시간`;
  }
  if (hours > 0) {
    return `${hours}시간 ${minutes}분`;
  }
  return `${minutes}분`;
}
