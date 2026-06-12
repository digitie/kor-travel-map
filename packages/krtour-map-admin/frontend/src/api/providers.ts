/**
 * `/v1/ops/providers*` provider 운영 상세 hooks.
 */

import { useQuery } from "@tanstack/react-query";

import { getJson } from "./client";
import type { components } from "./types";

type ProviderSchemas = components["schemas"];

export type ProviderSyncStateSummary =
  ProviderSchemas["ProviderSyncStateSummary"];
export type ProvidersFreshnessResponse =
  ProviderSchemas["ProvidersFreshnessResponse"];
export type OpsProviderDatasetSummary =
  ProviderSchemas["OpsProviderDatasetSummary"];
export type OpsProviderDatasetDetail =
  ProviderSchemas["OpsProviderDatasetDetail"];
export type OpsProviderDetailResponse =
  ProviderSchemas["OpsProviderDetailResponse"];
export type OpsProvidersResponse = ProviderSchemas["OpsProvidersResponse"];

function fetchOpsProviders(): Promise<OpsProvidersResponse> {
  return getJson<OpsProvidersResponse>("/v1/ops/providers");
}

function fetchOpsProvider(provider: string): Promise<OpsProviderDetailResponse> {
  return getJson<OpsProviderDetailResponse>(
    `/v1/ops/providers/${encodeURIComponent(provider)}`,
  );
}

export function useOpsProviders() {
  return useQuery<OpsProvidersResponse, Error>({
    queryKey: ["ops-providers"],
    queryFn: fetchOpsProviders,
    staleTime: 15_000,
  });
}

export function useOpsProvider(provider: string | null) {
  return useQuery<OpsProviderDetailResponse, Error>({
    queryKey: ["ops-provider", provider],
    queryFn: () => fetchOpsProvider(provider as string),
    enabled: Boolean(provider),
    staleTime: 10_000,
  });
}
