// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  useAdminFeatureCorrectionBasis,
  usePatchAdminFeatureMutation,
} from "./features";

type FetchMock = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function response(body: unknown, entityTag?: string): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      ...(entityTag ? { ETag: entityTag } : {}),
    },
  });
}

function hookContext(fetchMock: ReturnType<typeof vi.fn<FetchMock>>) {
  vi.stubGlobal("fetch", fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: 1 } },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("admin feature correction hooks", () => {
  it("basis query는 revision과 detail을 한 번 고정하고 window focus로 바꾸지 않는다", async () => {
    const fetchMock = vi
      .fn<FetchMock>()
      .mockResolvedValueOnce(
        response(
          { data: { feature_id: "feature-1", row_revision: 3 } },
          '"3"',
        ),
      )
      .mockResolvedValueOnce(
        response({
          data: { feature: { feature_id: "feature-1", row_revision: 3 } },
          meta: {},
        }),
      );
    const context = hookContext(fetchMock);
    const { result } = renderHook(
      () => useAdminFeatureCorrectionBasis("feature-1"),
      { wrapper: context.wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.entityTag).toBe('"3"');

    act(() => window.dispatchEvent(new Event("focus")));
    await act(async () => Promise.resolve());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("PATCH mutation은 caller의 raw ETag를 쓰고 correction basis를 무효화하지 않는다", async () => {
    const fetchMock = vi.fn<FetchMock>().mockResolvedValue(
      response({
        data: { request: { feature_id: "feature-1" } },
        meta: {},
      }),
    );
    const context = hookContext(fetchMock);
    const invalidateQueries = vi.spyOn(context.queryClient, "invalidateQueries");
    const { result } = renderHook(() => usePatchAdminFeatureMutation(), {
      wrapper: context.wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync({
        featureId: "feature-1",
        entityTag: '"3"',
        body: { name: "수정안", reason: "운영 수정" },
      });
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [input, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(input)).toBe("/api/proxy/v1/admin/features/feature-1");
    expect(init?.method).toBe("PATCH");
    expect(new Headers(init?.headers).get("if-match")).toBe('"3"');
    const invalidatedKeys = invalidateQueries.mock.calls.map(
      ([filters]) => filters?.queryKey,
    );
    expect(
      invalidatedKeys.some(
        (queryKey) => queryKey?.[0] === "admin-feature-correction-basis",
      ),
    ).toBe(false);
  });

  it("전역 query retry가 켜져 있어도 불일치 basis는 세 pair 뒤 한 번만 실패한다", async () => {
    const fetchMock = vi
      .fn<FetchMock>()
      .mockResolvedValueOnce(
        response(
          { data: { feature_id: "feature-1", row_revision: 1 } },
          '"1"',
        ),
      )
      .mockResolvedValueOnce(
        response({
          data: { feature: { feature_id: "feature-1", row_revision: 2 } },
          meta: {},
        }),
      )
      .mockResolvedValueOnce(
        response(
          { data: { feature_id: "feature-1", row_revision: 2 } },
          '"2"',
        ),
      )
      .mockResolvedValueOnce(
        response({
          data: { feature: { feature_id: "feature-1", row_revision: 3 } },
          meta: {},
        }),
      )
      .mockResolvedValueOnce(
        response(
          { data: { feature_id: "feature-1", row_revision: 3 } },
          '"3"',
        ),
      )
      .mockResolvedValueOnce(
        response({
          data: { feature: { feature_id: "feature-1", row_revision: 4 } },
          meta: {},
        }),
      );
    const context = hookContext(fetchMock);
    const { result } = renderHook(
      () => useAdminFeatureCorrectionBasis("feature-1"),
      { wrapper: context.wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });
});
