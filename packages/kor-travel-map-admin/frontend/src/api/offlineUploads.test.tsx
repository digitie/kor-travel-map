// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  useLaunchOfflineUploadLoadMutation,
  useValidateOfflineUploadMutation,
  type OfflineUploadColumnMapping,
} from "./offlineUploads";

type FetchMock = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function hookContext(response: unknown) {
  const fetchMock = vi.fn<FetchMock>(() =>
    Promise.resolve(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
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

function invalidatedKeys(
  invalidateQueries: ReturnType<typeof hookContext>["invalidateQueries"],
) {
  return invalidateQueries.mock.calls.map(([filters]) => filters?.queryKey);
}

describe("offline upload canonical query invalidation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("validation 성공은 pipeline 실행/overview와 ops dataset grid/detail을 무효화한다", async () => {
    const context = hookContext({
      data: {},
      meta: { duration_ms: 1, job_id: "validation-job", request_id: "test" },
    });
    const { result } = renderHook(() => useValidateOfflineUploadMutation(), {
      wrapper: context.wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync({
        uploadId: "upload-1",
        columnMapping: {} as OfflineUploadColumnMapping,
      });
    });

    const keys = invalidatedKeys(context.invalidateQueries);
    expect(keys).toEqual(
      expect.arrayContaining([
        ["pipeline", "executions"],
        ["pipeline", "overview"],
        ["pipeline", "execution", "import_job", "validation-job"],
        ["ops-datasets"],
        ["ops-dataset"],
      ]),
    );
    expect(keys).not.toContainEqual(["import-jobs"]);
  });

  it("load 성공은 pipeline 실행/overview/Dagster와 ops dataset grid/detail을 무효화한다", async () => {
    const context = hookContext({
      data: { load_job_id: "load-job" },
      meta: { duration_ms: 1, request_id: "test" },
    });
    const { result } = renderHook(() => useLaunchOfflineUploadLoadMutation(), {
      wrapper: context.wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync("upload-1");
    });

    const keys = invalidatedKeys(context.invalidateQueries);
    expect(keys).toEqual(
      expect.arrayContaining([
        ["pipeline", "executions"],
        ["pipeline", "overview"],
        ["pipeline", "dagster-runs"],
        ["pipeline", "execution", "import_job", "load-job"],
        ["ops-datasets"],
        ["ops-dataset"],
      ]),
    );
    expect(keys).not.toContainEqual(["import-jobs"]);
    expect(keys).not.toContainEqual(["ops", "dagster"]);
  });
});
