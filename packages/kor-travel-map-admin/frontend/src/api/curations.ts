import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteJson,
  getJson,
  patchJson,
  pathWithQuery,
  postFormData,
  postJson,
} from "./client";

export type CurationCollectionStatus = "draft" | "published" | "archived";
export type ActiveCurationCollectionStatus = "draft" | "published";
export type CurationCollectionVisibility = "admin_only" | "public";
export type CurationItemStatus =
  | "candidate"
  | "included"
  | "rejected"
  | "archived";
export type ActiveCurationItemStatus = "candidate" | "included" | "rejected";
export type CurationRelation =
  | "primary_stop"
  | "food_stop"
  | "cafe_stop"
  | "bookstore_stop"
  | "nearby_option"
  | "accessibility_support"
  | "pet_support"
  | "family_support"
  | "theme_area_anchor";
export type CurationReusePolicy = "allowed" | "blocked" | "manual_review";
export type CurationImportRowStatus =
  | "valid"
  | "invalid"
  | "unmatched"
  | "ambiguous"
  | "imported";

export interface CurationCollection {
  collection_id: string;
  collection_key: string;
  theme_id: string;
  theme_slug: string;
  theme_name: string;
  theme_group: string;
  source_id: string | null;
  provider: string | null;
  dataset_key: string | null;
  source_name: string | null;
  source_url: string | null;
  title: string;
  edition_key: string;
  description: string | null;
  status: CurationCollectionStatus;
  visibility: CurationCollectionVisibility;
  metadata: Record<string, unknown>;
  item_count: number;
  public_item_count: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  created_by: string | null;
  updated_by: string | null;
}

export interface CurationItem {
  curation_item_id: string;
  collection_id: string;
  collection_key: string;
  title: string;
  edition_key: string;
  theme_slug: string;
  theme_name: string;
  theme_group: string;
  provider: string | null;
  dataset_key: string | null;
  source_name: string | null;
  source_url: string | null;
  feature_id: string | null;
  feature_name: string | null;
  feature_kind: string | null;
  feature_category: string | null;
  lon: number | null;
  lat: number | null;
  address: Record<string, unknown>;
  source_record_key: string | null;
  external_item_id: string;
  external_component_id: string;
  place_name: string;
  address_hint: string | null;
  source_present: boolean;
  status: CurationItemStatus;
  sort_order: number;
  item_title: string | null;
  item_summary: string | null;
  curation_relation: CurationRelation;
  reuse_policy: CurationReusePolicy;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  created_by: string | null;
  updated_by: string | null;
}

export interface CurationCollectionCreateRequest {
  collection_key: string;
  theme_id?: string | null;
  theme_slug?: string | null;
  theme_name?: string | null;
  theme_group?: string | null;
  source_id?: string | null;
  title: string;
  edition_key?: string;
  description?: string | null;
  status?: ActiveCurationCollectionStatus;
  visibility?: CurationCollectionVisibility;
  metadata?: Record<string, unknown>;
}

export interface CurationItemCreateRequest {
  feature_id?: string | null;
  external_item_id: string;
  external_component_id?: string;
  place_name?: string | null;
  address_hint?: string | null;
  source_record_key?: string | null;
  status?: ActiveCurationItemStatus;
  sort_order?: number;
  item_title?: string | null;
  item_summary?: string | null;
  curation_relation?: CurationRelation;
  reuse_policy?: CurationReusePolicy;
  metadata?: Record<string, unknown>;
}

export interface CurationItemPatchRequest {
  feature_id?: string | null;
  external_item_id?: string;
  external_component_id?: string;
  place_name?: string;
  address_hint?: string | null;
  source_record_key?: string | null;
  status?: ActiveCurationItemStatus;
  sort_order?: number;
  item_title?: string | null;
  item_summary?: string | null;
  curation_relation?: CurationRelation;
  reuse_policy?: CurationReusePolicy;
  metadata?: Record<string, unknown>;
}

export interface CurationImportIssue {
  code: string;
  message: string;
  row_number: number | null;
  column: string | null;
}

export interface CurationImportCandidate {
  feature_id: string;
  name: string;
  address: Record<string, unknown>;
  lon: number | null;
  lat: number | null;
}

export interface CurationImportRow {
  row_number: number;
  status: CurationImportRowStatus;
  collection_key: string;
  theme_slug: string;
  title: string;
  edition_key: string;
  place_name: string;
  address_hint: string;
  requested_feature_id: string;
  resolved_feature_id: string | null;
  source_item_key: string;
  source_component_key: string;
  candidates: CurationImportCandidate[];
  issues: CurationImportIssue[];
}

interface ApiMeta {
  page?: { next_cursor?: string | null } | null;
  [key: string]: unknown;
}

export interface CurationCollectionsResponse {
  data: { items: CurationCollection[] };
  meta: ApiMeta;
}

export interface CurationCollectionResponse {
  data: { collection: CurationCollection; items: CurationItem[] };
  meta: ApiMeta;
}

export interface CurationItemResponse {
  data: CurationItem;
  meta: ApiMeta;
}

export interface CurationImportResponse {
  data: {
    dry_run: boolean;
    rows_total: number;
    valid_rows: number;
    invalid_rows: number;
    unresolved_rows: number;
    inserted: number;
    updated: number;
    removed: number;
    collections: number;
    removals: CurationItem[];
    items: CurationImportRow[];
    issues: CurationImportIssue[];
  };
  meta: ApiMeta;
}

export interface AdminCurationCollectionsParams {
  status?: CurationCollectionStatus;
  visibility?: CurationCollectionVisibility;
  theme_slug?: string;
  edition_key?: string;
  provider?: string;
  q?: string;
  include_archived?: boolean;
  page_size?: number;
  cursor?: string;
}

const COLLECTIONS_QUERY_KEY = ["curation-collections"] as const;

function invalidateCurations(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: COLLECTIONS_QUERY_KEY });
  void queryClient.invalidateQueries({ queryKey: ["curation-collection"] });
}

export function useAdminCurationCollections(
  params: AdminCurationCollectionsParams = { page_size: 500 },
) {
  return useQuery<CurationCollectionsResponse, Error>({
    queryKey: [...COLLECTIONS_QUERY_KEY, params] as const,
    queryFn: ({ signal }) => fetchAllAdminCurationCollections(params, signal),
    staleTime: 30_000,
  });
}

async function fetchAllAdminCurationCollections(
  params: AdminCurationCollectionsParams,
  signal?: AbortSignal,
): Promise<CurationCollectionsResponse> {
  const items: CurationCollection[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | null = params.cursor ?? null;
  let lastResponse: CurationCollectionsResponse | null = null;
  for (;;) {
    const response: CurationCollectionsResponse =
      await getJson<CurationCollectionsResponse>(
        pathWithQuery("/v1/admin/curations", {
          status: params.status,
          visibility: params.visibility,
          theme_slug: params.theme_slug,
          edition_key: params.edition_key,
          provider: params.provider,
          q: params.q,
          include_archived: params.include_archived,
          page_size: params.page_size ?? 500,
          cursor,
        }),
        { signal },
      );
    items.push(...response.data.items);
    lastResponse = response;
    const nextCursor = response.meta.page?.next_cursor ?? null;
    if (nextCursor === null) break;
    if (seenCursors.has(nextCursor)) {
      throw new Error("큐레이션 컬렉션 API가 같은 cursor를 반복했습니다.");
    }
    seenCursors.add(nextCursor);
    cursor = nextCursor;
  }
  return {
    data: { items },
    meta: {
      ...(lastResponse?.meta ?? {}),
      page: lastResponse?.meta.page
        ? { ...lastResponse.meta.page, next_cursor: null }
        : lastResponse?.meta.page,
    },
  };
}

export function useAdminCurationCollection(collectionId: string | null) {
  return useQuery<CurationCollectionResponse, Error>({
    queryKey: ["curation-collection", collectionId] as const,
    queryFn: ({ signal }) =>
      getJson<CurationCollectionResponse>(
        `/v1/admin/curations/${encodeURIComponent(collectionId as string)}`,
        { signal },
      ),
    enabled: collectionId !== null && collectionId.length > 0,
    staleTime: 30_000,
  });
}

export function useCreateCurationCollectionMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CurationCollectionResponse,
    Error,
    CurationCollectionCreateRequest
  >({
    mutationFn: (body) =>
      postJson<CurationCollectionResponse>("/v1/admin/curations", body),
    onSuccess: () => invalidateCurations(queryClient),
  });
}

export function useAddCurationItemMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CurationItemResponse,
    Error,
    { collectionId: string; body: CurationItemCreateRequest }
  >({
    mutationFn: ({ collectionId, body }) =>
      postJson<CurationItemResponse>(
        `/v1/admin/curations/${encodeURIComponent(collectionId)}/items`,
        body,
      ),
    onSuccess: () => invalidateCurations(queryClient),
  });
}

export function usePatchCurationItemMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CurationItemResponse,
    Error,
    {
      collectionId: string;
      curationItemId: string;
      body: CurationItemPatchRequest;
    }
  >({
    mutationFn: ({ collectionId, curationItemId, body }) =>
      patchJson<CurationItemResponse>(
        `/v1/admin/curations/${encodeURIComponent(collectionId)}/items/${encodeURIComponent(curationItemId)}`,
        body,
      ),
    onSuccess: () => invalidateCurations(queryClient),
  });
}

export function useArchiveCurationItemMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CurationItemResponse,
    Error,
    { collectionId: string; curationItemId: string }
  >({
    mutationFn: ({ collectionId, curationItemId }) =>
      deleteJson<CurationItemResponse>(
        `/v1/admin/curations/${encodeURIComponent(collectionId)}/items/${encodeURIComponent(curationItemId)}`,
      ),
    onSuccess: () => invalidateCurations(queryClient),
  });
}

export function useImportCurationCsvMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CurationImportResponse,
    Error,
    { file: File; dryRun: boolean }
  >({
    mutationFn: ({ file, dryRun }) => {
      const body = new FormData();
      body.append("file", file);
      return postFormData<CurationImportResponse>(
        pathWithQuery("/v1/admin/curations/import", {
          dry_run: dryRun,
        }),
        body,
      );
    },
    onSuccess: (response) => {
      if (!response.data.dry_run) {
        invalidateCurations(queryClient);
      }
    },
  });
}

export const CURATION_IMPORT_TEMPLATE_URL =
  "/api/proxy/v1/admin/curations/import-template.csv";
