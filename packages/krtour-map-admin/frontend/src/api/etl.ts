/**
 * ETL preview API hooks — `/debug/etl/*` (PR#44).
 *
 * 변환 결과(FeatureBundle / WeatherValue / PriceValue dict)를 generic하게
 * 다룬다 — TypeScript에서는 `unknown` 또는 dict로 받고 UI에서 JSON 그대로
 * 표시.
 */

import { useMutation, useQuery } from "@tanstack/react-query";

import { getJson, postJson } from "./client";
import type { components } from "./types";

type EtlSchemas = components["schemas"];

export type DatasetEntry = EtlSchemas["_DatasetEntry"];
export type ProviderEntry = EtlSchemas["_ProviderEntry"];
export type ProvidersResponse = EtlSchemas["ProvidersResponse"];
export type EtlPreviewResponse = EtlSchemas["EtlPreviewResponse"];

export function useProviders() {
  return useQuery<ProvidersResponse, Error>({
    queryKey: ["debug", "etl", "providers"],
    queryFn: () => getJson<ProvidersResponse>("/debug/etl/providers"),
    staleTime: 60_000,
  });
}

export function useEtlPreviewMutation() {
  return useMutation<
    EtlPreviewResponse,
    Error,
    { provider: string; dataset: string; source?: "fixture" | "live" }
  >({
    mutationFn: ({ provider, dataset, source = "fixture" }) => {
      const path =
        `/debug/etl/${encodeURIComponent(provider)}/` +
        `${encodeURIComponent(dataset)}/preview?source=${source}`;
      return postJson<EtlPreviewResponse>(path);
    },
  });
}
