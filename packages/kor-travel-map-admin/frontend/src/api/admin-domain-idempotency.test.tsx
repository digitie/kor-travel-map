// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  usePurgeManagedFileMutation,
  useRescanManagedFilesMutation,
} from "./adminFiles";
import { useRevokePublicApiKeyMutation } from "./adminSettings";
import {
  useCreateBackupMutation,
  type BackupRunRequest,
} from "./backups";
import {
} from "./curated";
import {
  useAddCurationItemMutation,
  useArchiveCurationItemMutation,
  useCommitCurationImportPlanMutation,
  useCreateCurationCollectionMutation,
  usePatchCurationItemMutation,
  usePreviewCurationCsvMutation,
  type CurationItemPatchRequest,
} from "./curations";
import {
  useDedupDecisionMutation,
  type DedupReviewDecisionRequest,
} from "./dedup";
import {
  useEnrichmentDecisionMutation,
  type EnrichmentReviewDecisionRequest,
} from "./enrichment";
import {
  useCreateAdminFeatureMutation,
  useDeleteAdminFeatureMutation,
  usePatchAdminFeatureStateMutation,
  usePatchAdminFeatureMutation,
  type AdminFeatureCreateRequest,
  type AdminFeatureStatePatchRequest,
  type AdminFeatureDeleteRequest,
  type AdminFeaturePatchRequest,
} from "./features";
import {
  useCreateOfflineUploadMutation,
  useDeleteOfflineUploadMutation,
  useLaunchOfflineUploadLoadMutation,
  useValidateOfflineUploadMutation,
  type OfflineUploadColumnMapping,
} from "./offlineUploads";
import {
  useAdminIssueActionMutation,
  type AdminIssuePatchRequest,
} from "./issues";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

type FetchMock = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function genericMutationResponse(): Response {
  return new Response(
    JSON.stringify({
      data: {
        applied: false,
        collection: { collection_id: "collection-1" },
        dry_run: false,
        feature: null,
        items: [],
        load_job_id: "load-job",
        loser_feature_id: null,
        master_feature_id: null,
        public_api_key_id: "key-1",
        feature_id: "feature-1",
        upload_id: "upload-1",
      },
      meta: { job_id: "validation-job", request_id: "request-1" },
    }),
    { headers: { "Content-Type": "application/json" }, status: 200 },
  );
}

function hookContext() {
  const fetchMock = vi.fn<FetchMock>(() =>
    Promise.resolve(genericMutationResponse()),
  );
  vi.stubGlobal("fetch", fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { fetchMock, queryClient, wrapper };
}

type HookContext = ReturnType<typeof hookContext>;

async function runMutation<TVariables>(
  context: HookContext,
  hook: () => { mutateAsync: (variables: TVariables) => Promise<unknown> },
  variables: TVariables,
): Promise<void> {
  const { result, unmount } = renderHook(hook, { wrapper: context.wrapper });
  await act(async () => {
    await result.current.mutateAsync(variables);
  });
  unmount();
}

function csvFile(content: string, name = "items.csv"): File {
  return new File([content], name, { lastModified: 1, type: "text/csv" });
}

describe("admin domain idempotency consumers", () => {
  afterEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("retryable admin write hooks send explicit UUID Idempotency-Key headers", async () => {
    const context = hookContext();
    const cases: Array<{ name: string; run: () => Promise<void> }> = [
      {
        name: "backup create",
        run: () =>
          runMutation(context, useCreateBackupMutation, {} as BackupRunRequest),
      },
      {
        name: "offline create",
        run: () =>
          runMutation(context, useCreateOfflineUploadMutation, {
            file: csvFile("a,b\n1,2\n"),
            providerDatasetId: 401,
          }),
      },
      {
        name: "offline validate",
        run: () =>
          runMutation(context, useValidateOfflineUploadMutation, {
            columnMapping: {} as OfflineUploadColumnMapping,
            uploadId: "upload-1",
          }),
      },
      {
        name: "offline delete",
        run: () =>
          runMutation(context, useDeleteOfflineUploadMutation, "upload-1"),
      },
      {
        name: "offline load",
        run: () =>
          runMutation(context, useLaunchOfflineUploadLoadMutation, "upload-1"),
      },
      {
        name: "feature retire",
        run: () =>
          runMutation(context, usePatchAdminFeatureStateMutation, {
            body: {
              action: "retire",
              reason_code: "admin_ui_retire",
            } as AdminFeatureStatePatchRequest,
            entityTag: '"7"',
            featureId: "feature-1",
          }),
      },
      {
        name: "feature create",
        run: () =>
          runMutation(
            context,
            useCreateAdminFeatureMutation,
            {} as AdminFeatureCreateRequest,
          ),
      },
      {
        name: "feature patch",
        run: () =>
          runMutation(context, usePatchAdminFeatureMutation, {
            body: { reason: "patch" } as AdminFeaturePatchRequest,
            entityTag: '"7"',
            featureId: "feature-1",
          }),
      },
      {
        name: "feature delete",
        run: () =>
          runMutation(context, useDeleteAdminFeatureMutation, {
            body: { reason: "delete" } as AdminFeatureDeleteRequest,
            entityTag: '"7"',
            featureId: "feature-1",
          }),
      },
      {
        name: "curation collection create",
        run: () =>
          runMutation(context, useCreateCurationCollectionMutation, {
            collection_key: "collection-key",
            theme_id: "11111111-1111-4111-8111-111111111111",
            title: "collection title",
          }),
      },
      {
        name: "curation item create",
        run: () =>
          runMutation(context, useAddCurationItemMutation, {
            body: { external_item_id: "external-1" },
            collectionId: "collection-1",
          }),
      },
      {
        name: "curation item patch",
        run: () =>
          runMutation(context, usePatchCurationItemMutation, {
            body: { item_title: "patched" } as CurationItemPatchRequest,
            collectionId: "collection-1",
            commandEtag: '"7"',
            curationItemId: "item-1",
          }),
      },
      {
        name: "curation item archive",
        run: () =>
          runMutation(context, useArchiveCurationItemMutation, {
            collectionId: "collection-1",
            commandEtag: '"7"',
            curationItemId: "item-1",
          }),
      },
      {
        name: "curation import preview",
        run: () =>
          runMutation(context, usePreviewCurationCsvMutation, {
            file: csvFile("title,place_name\nx,y\n"),
          }),
      },
      {
        name: "curation import commit",
        run: () =>
          runMutation(context, useCommitCurationImportPlanMutation, {
            importPlanId: "00000000-0000-4000-8000-000000000001",
            planEtag: '"sha256:import-plan"',
          }),
      },
      {
        name: "dedup review",
        run: () =>
          runMutation(context, useDedupDecisionMutation, {
            body: { decision: "rejected" } as DedupReviewDecisionRequest,
            reviewKey: "review-1",
          }),
      },
      {
        name: "enrichment review",
        run: () =>
          runMutation(context, useEnrichmentDecisionMutation, {
            body: { decision: "rejected" } as EnrichmentReviewDecisionRequest,
            reviewKey: "review-1",
          }),
      },
      {
        name: "managed file rescan",
        run: () =>
          runMutation(context, useRescanManagedFilesMutation, ["/tmp/input"]),
      },
      {
        name: "managed file purge",
        run: () => runMutation(context, usePurgeManagedFileMutation, 7),
      },
      {
        name: "issue patch",
        run: () =>
          runMutation(context, useAdminIssueActionMutation, {
            body: { action: "resolve" } as AdminIssuePatchRequest,
            issueId: "issue-1",
          }),
      },
      {
        name: "public API key revoke",
        run: () =>
          runMutation(context, useRevokePublicApiKeyMutation, "public-key-1"),
      },
    ];

    for (const item of cases) {
      await item.run();
    }

    expect(context.fetchMock).toHaveBeenCalledTimes(cases.length);
    for (const [index, [, init]] of context.fetchMock.mock.calls.entries()) {
      const headers = init?.headers as Record<string, string> | undefined;
      expect(headers?.["Idempotency-Key"], cases[index]?.name).toMatch(UUID_RE);
      if (
        cases[index]?.name === "curation item patch" ||
        cases[index]?.name === "curation item archive"
      ) {
        expect(headers?.["If-Match"], cases[index]?.name).toBe('"7"');
      }
    }
  });
});
