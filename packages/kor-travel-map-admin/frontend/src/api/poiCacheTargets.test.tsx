// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  useDeletePoiCacheTargetMutation,
  useUpsertPoiCacheTargetMutation,
  type PoiCacheTargetUpsertRequest,
} from "./poiCacheTargets";

type FetchMock = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function hookContext() {
  const fetchMock = vi.fn<FetchMock>(() =>
    Promise.resolve(
      new Response(
        JSON.stringify({
          data: { nearby_url: null },
          meta: {
            dataset_projection_revision: 41,
            duration_ms: 1,
            request_id: "test",
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);

  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { fetchMock, invalidateQueries, wrapper };
}

function expectCanonicalInvalidation(
  invalidateQueries: ReturnType<typeof hookContext>["invalidateQueries"],
) {
  const keys = invalidateQueries.mock.calls.map(([filters]) => filters?.queryKey);
  expect(keys).toEqual(
    expect.arrayContaining([
      ["pipeline", "executions"],
      ["pipeline", "overview"],
      ["ops-datasets"],
      ["ops-dataset"],
    ]),
  );
  expect(keys).not.toContainEqual(["feature-update-requests"]);
}

describe("POI cache target canonical query invalidation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("upsert 성공은 pipeline과 ops dataset 표면을 무효화한다", async () => {
    const context = hookContext();
    const { result } = renderHook(() => useUpsertPoiCacheTargetMutation(), {
      wrapper: context.wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync({
        externalSystem: "concierge",
        targetKey: "poi-1",
        body: {} as PoiCacheTargetUpsertRequest,
      });
    });

    expectCanonicalInvalidation(context.invalidateQueries);
  });

  it("delete 성공은 pipeline과 ops dataset 표면을 무효화한다", async () => {
    const context = hookContext();
    const { result } = renderHook(() => useDeletePoiCacheTargetMutation(), {
      wrapper: context.wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync({
        externalSystem: "concierge",
        targetKey: "poi-1",
        entityTag: '"11111111-1111-4111-8111-111111111111:7"',
      });
    });

    expectCanonicalInvalidation(context.invalidateQueries);
    const request = context.fetchMock.mock.calls[0];
    expect(request?.[0]).toBe(
      "/api/proxy/v1/admin/poi-cache-targets/concierge/poi-1",
    );
    expect(new Headers(request?.[1]?.headers).get("if-match")).toBe(
      '"11111111-1111-4111-8111-111111111111:7"',
    );
  });

  it("delete 412도 list/nearby/dataset/pipeline projection을 refetch한다", async () => {
    const context = hookContext();
    context.fetchMock.mockImplementationOnce(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            code: "PRECONDITION_FAILED",
            detail: "stale entity tag",
            errors: [],
            request_id: "test",
            status: 412,
            title: "stale entity tag",
            type: "https://kor-travel-map/errors/precondition-failed",
          }),
          {
            status: 412,
            headers: { "Content-Type": "application/problem+json" },
          },
        ),
      ),
    );
    const { result } = renderHook(() => useDeletePoiCacheTargetMutation(), {
      wrapper: context.wrapper,
    });

    await act(async () => {
      await expect(
        result.current.mutateAsync({
          externalSystem: "concierge",
          targetKey: "poi-1",
          entityTag: '"11111111-1111-4111-8111-111111111111:7"',
        }),
      ).rejects.toThrow();
    });

    const keys = context.invalidateQueries.mock.calls.map(
      ([filters]) => filters?.queryKey,
    );
    expect(keys).toContainEqual(["poi-cache-targets"]);
    expect(keys).toContainEqual(["poi-cache-target", "concierge", "poi-1"]);
    expect(keys).toContainEqual(["nearby-features-by-target"]);
    expectCanonicalInvalidation(context.invalidateQueries);
  });
});
