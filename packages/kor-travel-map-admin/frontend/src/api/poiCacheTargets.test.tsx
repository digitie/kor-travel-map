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
          meta: { duration_ms: 1, request_id: "test" },
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
  return { invalidateQueries, wrapper };
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
      });
    });

    expectCanonicalInvalidation(context.invalidateQueries);
  });
});
