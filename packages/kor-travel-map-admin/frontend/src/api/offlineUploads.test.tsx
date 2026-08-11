// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  useCreateOfflineUploadMutation,
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
  return { fetchMock, invalidateQueries, wrapper };
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

  it("생성은 natural key 없이 provider_dataset_id만 multipart와 멱등 입력에 넣는다", async () => {
    const context = hookContext({
      data: { upload_id: "upload-1" },
      meta: { duration_ms: 1, request_id: "test" },
    });
    const { result } = renderHook(() => useCreateOfflineUploadMutation(), {
      wrapper: context.wrapper,
    });
    const file = new File(["name,lon,lat\nSeoul,126.978,37.566\n"], "offline.csv", {
      type: "text/csv",
    });

    await act(async () => {
      await result.current.mutateAsync({
        file,
        providerDatasetId: 401,
        syncScope: "external_system:test",
      });
    });

    const [, init] = context.fetchMock.mock.calls[0];
    expect(init?.body).toBeInstanceOf(FormData);
    const form = init?.body as FormData;
    expect(form.get("provider_dataset_id")).toBe("401");
    expect(form.get("sync_scope")).toBe("external_system:test");
    expect(form.get("provider")).toBeNull();
    expect(form.get("dataset_key")).toBeNull();
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
