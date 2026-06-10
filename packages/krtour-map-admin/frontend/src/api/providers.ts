/**
 * `/v1/providers` provider 데이터 신선도 hooks (T-217g, D-07).
 */

import { useQuery } from "@tanstack/react-query";

import { getJson } from "./client";
import type { components } from "./types";

type ProviderSchemas = components["schemas"];

export type ProviderSyncStateSummary =
  ProviderSchemas["ProviderSyncStateSummary"];
export type ProvidersFreshnessResponse =
  ProviderSchemas["ProvidersFreshnessResponse"];

function fetchProvidersFreshness(): Promise<ProvidersFreshnessResponse> {
  return getJson<ProvidersFreshnessResponse>("/v1/providers");
}

export function useProvidersFreshness() {
  return useQuery<ProvidersFreshnessResponse, Error>({
    queryKey: ["providers", "freshness"],
    queryFn: fetchProvidersFreshness,
    staleTime: 30_000,
  });
}
