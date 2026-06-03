/**
 * ETL preview API hooks — `/debug/etl/*` (PR#44).
 *
 * 변환 결과(FeatureBundle / WeatherValue / PriceValue dict)를 generic하게
 * 다룬다 — TypeScript에서는 `unknown` 또는 dict로 받고 UI에서 JSON 그대로
 * 표시.
 */

import { useMutation, useQuery } from "@tanstack/react-query";

import { getJson, postJson } from "./client";

export interface DatasetEntry {
  dataset: string;
  variant: "FeatureBundle" | "WeatherValue" | "PriceValue" | string;
  description: string;
}

export interface ProviderEntry {
  provider: string;
  datasets: DatasetEntry[];
}

export interface ProvidersResponse {
  providers: ProviderEntry[];
}

export interface EtlPreviewResponse {
  provider: string;
  dataset: string;
  source: "fixture" | "live";
  variant: string;
  description: string;
  count: number;
  items: Array<Record<string, unknown>>;
}

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
