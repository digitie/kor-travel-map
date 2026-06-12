/**
 * `/v1/admin/provider-refresh-policies/*` hooks.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { putJson } from "./client";
import type { components } from "./types";

type PolicySchemas = components["schemas"];

export type ProviderRefreshPolicyRecord =
  PolicySchemas["ProviderRefreshPolicyRecord"];
export type ProviderRefreshPolicyResponse =
  PolicySchemas["ProviderRefreshPolicyResponse"];
export type ProviderRefreshPolicyUpsertRequest =
  PolicySchemas["ProviderRefreshPolicyUpsertRequest"];

function upsertProviderRefreshPolicy({
  provider,
  datasetKey,
  body,
}: {
  provider: string;
  datasetKey: string;
  body: ProviderRefreshPolicyUpsertRequest;
}): Promise<ProviderRefreshPolicyResponse> {
  return putJson<ProviderRefreshPolicyResponse>(
    `/v1/admin/provider-refresh-policies/${encodeURIComponent(provider)}/${encodeURIComponent(datasetKey)}`,
    body,
  );
}

export function useUpsertProviderRefreshPolicyMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    ProviderRefreshPolicyResponse,
    Error,
    {
      provider: string;
      datasetKey: string;
      body: ProviderRefreshPolicyUpsertRequest;
    }
  >({
    mutationFn: upsertProviderRefreshPolicy,
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: ["provider-refresh-policies"],
      });
      void queryClient.invalidateQueries({
        queryKey: [
          "provider-refresh-policy",
          variables.provider,
          variables.datasetKey,
        ],
      });
      void queryClient.invalidateQueries({ queryKey: ["ops-providers"] });
      void queryClient.invalidateQueries({
        queryKey: ["ops-provider", variables.provider],
      });
      void queryClient.invalidateQueries({ queryKey: ["providers"] });
    },
  });
}
