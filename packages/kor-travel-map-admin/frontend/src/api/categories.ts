import { useQuery } from "@tanstack/react-query";

import { getJson, pathWithQuery } from "./client";
import type { components, paths } from "./types";

type CategorySchemas = components["schemas"];

export type CategorySummary = CategorySchemas["CategorySummary"];
export type CategoriesResponse = CategorySchemas["CategoriesResponse"];

type CategoriesQuery = NonNullable<
  paths["/v1/categories"]["get"]["parameters"]["query"]
>;

// T-VN-04(ADR-067): counts는 항상 공개 projection 기준 — active_only 파라미터 제거됨.
export type CategoriesParams = Pick<CategoriesQuery, "include_counts">;

function fetchCategories(
  params: CategoriesParams = {},
  signal?: AbortSignal,
): Promise<CategoriesResponse> {
  return getJson<CategoriesResponse>(
    pathWithQuery("/v1/categories", {
      include_counts: params.include_counts,
    }),
    { signal },
  );
}

export function useCategories(params: CategoriesParams = {}) {
  return useQuery<CategoriesResponse, Error>({
    queryKey: ["categories", params] as const,
    queryFn: ({ signal }) => fetchCategories(params, signal),
    staleTime: 10 * 60_000,
  });
}
