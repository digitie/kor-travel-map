import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  clearDomainCreateCommandSlot,
  deleteJson,
  domainCommandSlot,
  domainCreateCommandSlot,
  fileIdempotencyFingerprint,
  getJson,
  patchJson,
  pathWithQuery,
  postFormData,
  postJson,
  withDomainIdempotencyFingerprint,
  withDomainIdempotencySubmission,
} from "./client";
import type { components } from "./types";

type QuarantineSchemas = components["schemas"];

export type CurationQuarantineTheme =
  QuarantineSchemas["CurationQuarantineThemeView"];
export type CurationQuarantineSource =
  QuarantineSchemas["CurationQuarantineSourceView"];
export type CurationQuarantineOriginalCollection =
  QuarantineSchemas["CurationQuarantineOriginalCollectionView"];
export type CurationQuarantineCollection =
  QuarantineSchemas["AdminCurationQuarantineCollectionView"];
export type CurationQuarantineItem =
  QuarantineSchemas["AdminCurationQuarantineItemView"];
export type CurationQuarantineConflictKind =
  CurationQuarantineItem["conflict_kind"];
export type CurationQuarantineReclassifyRequest =
  QuarantineSchemas["AdminCurationQuarantineReclassifyRequest"];

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
  | "review_required"
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
  row_revision: string;
  command_etag: string;
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
  row_revision: string;
  command_etag: string;
}

export interface CurationCollectionCreateRequest {
  collection_key: string;
  theme_id: string;
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
    import_plan_id: string;
    plan_etag: string;
    expires_at: string;
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

export interface CurationQuarantineCollectionsResponse {
  data: { items: CurationQuarantineCollection[] };
  meta: ApiMeta;
}

export interface CurationQuarantineItemsResponse {
  data: QuarantineSchemas["AdminCurationQuarantineItemsData"];
  meta: ApiMeta;
}

export interface CurationQuarantineReclassifyResponse {
  data: QuarantineSchemas["AdminCurationQuarantineReclassifyData"];
  meta: ApiMeta;
}

const COLLECTIONS_QUERY_KEY = ["curation-collections"] as const;
const QUARANTINE_COLLECTIONS_QUERY_KEY = ["curation-quarantine"] as const;
const QUARANTINE_ITEMS_QUERY_KEY = ["curation-quarantine-items"] as const;

function invalidateCurations(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: COLLECTIONS_QUERY_KEY });
  void queryClient.invalidateQueries({ queryKey: ["curation-collection"] });
  void queryClient.invalidateQueries({
    queryKey: QUARANTINE_COLLECTIONS_QUERY_KEY,
  });
  void queryClient.invalidateQueries({ queryKey: QUARANTINE_ITEMS_QUERY_KEY });
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

export function useAdminCurationQuarantineCollections() {
  return useQuery<CurationQuarantineCollectionsResponse, Error>({
    queryKey: QUARANTINE_COLLECTIONS_QUERY_KEY,
    queryFn: ({ signal }) => fetchAllAdminCurationQuarantineCollections(signal),
    staleTime: 30_000,
  });
}

async function fetchAllAdminCurationQuarantineCollections(
  signal?: AbortSignal,
): Promise<CurationQuarantineCollectionsResponse> {
  const items: CurationQuarantineCollection[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  let lastResponse: CurationQuarantineCollectionsResponse | null = null;
  for (;;) {
    const response: CurationQuarantineCollectionsResponse =
      await getJson<CurationQuarantineCollectionsResponse>(
        pathWithQuery("/v1/admin/curations/quarantine", {
          page_size: 200,
          cursor,
        }),
        { signal },
      );
    items.push(...response.data.items);
    lastResponse = response;
    const nextCursor = response.meta.page?.next_cursor ?? null;
    if (nextCursor === null) break;
    if (seenCursors.has(nextCursor)) {
      throw new Error("격리 큐레이션 collection API가 같은 cursor를 반복했습니다.");
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

export function useAdminCurationQuarantineItems(
  collectionId: string | null,
  targetCollectionId: string | null,
) {
  return useQuery<CurationQuarantineItemsResponse, Error>({
    queryKey: [
      ...QUARANTINE_ITEMS_QUERY_KEY,
      collectionId,
      targetCollectionId,
    ] as const,
    queryFn: ({ signal }) =>
      fetchAllAdminCurationQuarantineItems(
        collectionId as string,
        targetCollectionId,
        signal,
      ),
    enabled: collectionId !== null && collectionId.length > 0,
    staleTime: 30_000,
  });
}

async function fetchAllAdminCurationQuarantineItems(
  collectionId: string,
  targetCollectionId: string | null,
  signal?: AbortSignal,
): Promise<CurationQuarantineItemsResponse> {
  const items: CurationQuarantineItem[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  let lastResponse: CurationQuarantineItemsResponse | null = null;
  for (;;) {
    const response: CurationQuarantineItemsResponse =
      await getJson<CurationQuarantineItemsResponse>(
        pathWithQuery(
          `/v1/admin/curations/quarantine/${encodeURIComponent(
            collectionId,
          )}/items`,
          {
            target_collection_id: targetCollectionId,
            page_size: 200,
            cursor,
          },
        ),
        { signal },
      );
    items.push(...response.data.items);
    lastResponse = response;
    const nextCursor = response.meta.page?.next_cursor ?? null;
    if (nextCursor === null) break;
    if (seenCursors.has(nextCursor)) {
      throw new Error("격리 큐레이션 item API가 같은 cursor를 반복했습니다.");
    }
    seenCursors.add(nextCursor);
    cursor = nextCursor;
  }
  if (lastResponse === null) {
    throw new Error("격리 큐레이션 item API 응답이 없습니다.");
  }
  return {
    data: { ...lastResponse.data, items },
    meta: {
      ...lastResponse.meta,
      page: lastResponse.meta.page
        ? { ...lastResponse.meta.page, next_cursor: null }
        : lastResponse.meta.page,
    },
  };
}

export function useReclassifyCurationQuarantineMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CurationQuarantineReclassifyResponse,
    Error,
    {
      collectionId: string;
      commandEtag: string;
      body: CurationQuarantineReclassifyRequest;
    }
  >({
    mutationFn: ({ collectionId, commandEtag, body }) =>
      withDomainIdempotencySubmission(
        domainCommandSlot("admin.curation-quarantine.reclassify", collectionId),
        { collectionId, commandEtag, body },
        (submission, idempotencyKey) =>
          postJson<CurationQuarantineReclassifyResponse>(
            `/v1/admin/curations/quarantine/${encodeURIComponent(
              submission.collectionId,
            )}/reclassify`,
            submission.body,
            {
              headers: {
                "Idempotency-Key": idempotencyKey,
                "If-Match": submission.commandEtag,
              },
            },
          ),
      ),
    onSuccess: () => invalidateCurations(queryClient),
  });
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
    mutationFn: (body) => {
      const operation = "admin.curation-collection.create";
      return withDomainIdempotencySubmission(
        domainCreateCommandSlot(operation),
        body,
        (submission, idempotencyKey) =>
          postJson<CurationCollectionResponse>("/v1/admin/curations", submission, {
            headers: { "Idempotency-Key": idempotencyKey },
          }),
        { onRelease: () => clearDomainCreateCommandSlot(operation) },
      );
    },
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
    mutationFn: ({ collectionId, body }) => {
      const operation = domainCommandSlot(
        "admin.curation-item.create",
        collectionId,
      );
      return withDomainIdempotencySubmission(
        domainCreateCommandSlot(operation),
        { collectionId, body },
        (submission, idempotencyKey) =>
          postJson<CurationItemResponse>(
            `/v1/admin/curations/${encodeURIComponent(
              submission.collectionId,
            )}/items`,
            submission.body,
            { headers: { "Idempotency-Key": idempotencyKey } },
          ),
        { onRelease: () => clearDomainCreateCommandSlot(operation) },
      );
    },
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
      commandEtag: string;
      body: CurationItemPatchRequest;
    }
  >({
    mutationFn: ({ collectionId, curationItemId, commandEtag, body }) =>
      withDomainIdempotencySubmission(
        domainCommandSlot(
          "admin.curation-item.patch",
          collectionId,
          curationItemId,
        ),
        { collectionId, curationItemId, commandEtag, body },
        (submission, idempotencyKey) =>
          patchJson<CurationItemResponse>(
            `/v1/admin/curations/${encodeURIComponent(
              submission.collectionId,
            )}/items/${encodeURIComponent(submission.curationItemId)}`,
            submission.body,
            {
              headers: {
                "Idempotency-Key": idempotencyKey,
                "If-Match": submission.commandEtag,
              },
            },
          ),
      ),
    onSuccess: () => invalidateCurations(queryClient),
  });
}

export function useArchiveCurationItemMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CurationItemResponse,
    Error,
    { collectionId: string; curationItemId: string; commandEtag: string }
  >({
    mutationFn: ({ collectionId, curationItemId, commandEtag }) =>
      withDomainIdempotencySubmission(
        domainCommandSlot(
          "admin.curation-item.archive",
          collectionId,
          curationItemId,
        ),
        { collectionId, curationItemId, commandEtag },
        (submission, idempotencyKey) =>
          deleteJson<CurationItemResponse>(
            `/v1/admin/curations/${encodeURIComponent(
              submission.collectionId,
            )}/items/${encodeURIComponent(submission.curationItemId)}`,
            undefined,
            {
              headers: {
                "Idempotency-Key": idempotencyKey,
                "If-Match": submission.commandEtag,
              },
            },
          ),
      ),
    onSuccess: () => invalidateCurations(queryClient),
  });
}

export function usePreviewCurationCsvMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CurationImportResponse,
    Error,
    { file: File }
  >({
    mutationFn: async ({ file }) => {
      const body = new FormData();
      body.append("file", file);
      const fileIdentity = await fileIdempotencyFingerprint(file);
      const operation = "admin.curation-import.preview";
      return withDomainIdempotencyFingerprint(
        domainCreateCommandSlot(operation),
        {
          content_sha256: fileIdentity.contentSha256,
        },
        (idempotencyKey) =>
          postFormData<CurationImportResponse>(
            "/v1/admin/curations/imports/preview",
            body,
            { headers: { "Idempotency-Key": idempotencyKey } },
          ),
        { onRelease: () => clearDomainCreateCommandSlot(operation) },
      );
    },
    onSuccess: () => invalidateCurations(queryClient),
  });
}

export function useCommitCurationImportPlanMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CurationImportResponse,
    Error,
    { importPlanId: string; planEtag: string }
  >({
    mutationFn: ({ importPlanId, planEtag }) =>
      withDomainIdempotencySubmission(
        domainCommandSlot("admin.curation.import", importPlanId),
        { importPlanId, planEtag },
        (submission, idempotencyKey) =>
          postJson<CurationImportResponse>(
            `/v1/admin/curations/import-plans/${encodeURIComponent(
              submission.importPlanId,
            )}/commit`,
            undefined,
            {
              headers: {
                "Idempotency-Key": idempotencyKey,
                "If-Match": submission.planEtag,
              },
            },
          ),
      ),
    onSuccess: () => invalidateCurations(queryClient),
  });
}

export const CURATION_IMPORT_TEMPLATE_URL =
  "/api/proxy/v1/admin/curations/import-template.csv";
