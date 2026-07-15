import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, getJson, postJson } from "./client";

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

function jsonResponse(): Response {
  return new Response("{}", {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch() {
  const fetchMock = vi.fn<FetchMock>(() => Promise.resolve(jsonResponse()));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function stubFetchStatus(status: number) {
  const fetchMock = vi.fn<FetchMock>(() =>
    Promise.resolve(new Response("{}", { status })),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("api client AbortSignal forwarding (concierge #111 class fix)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("getJson가 signal을 fetch로 전달한다", async () => {
    const fetchMock = stubFetch();
    const controller = new AbortController();

    await getJson("/v1/x", { signal: controller.signal });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
  });

  it("postJson가 signal을 fetch로 전달한다", async () => {
    const fetchMock = stubFetch();
    const controller = new AbortController();

    await postJson("/v1/x", { a: 1 }, { signal: controller.signal });

    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
  });

  it("signal 미지정 시에도 동작한다(undefined)", async () => {
    const fetchMock = stubFetch();

    await getJson("/v1/x");

    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBeUndefined();
  });

  it("401 응답은 로그인 화면으로 리다이렉트한다", async () => {
    const assign = vi.fn();
    vi.stubGlobal("window", {
      location: {
        assign,
        pathname: "/admin/settings",
        search: "?tab=keys",
      },
    });
    stubFetchStatus(401);

    await expect(getJson("/v1/admin/auth-events")).rejects.toMatchObject({
      status: 401,
    });

    expect(assign).toHaveBeenCalledWith("/login?next=%2Fadmin%2Fsettings%3Ftab%3Dkeys");
  });

  it("RFC7807 본문과 Retry-After를 typed 오류로 보존한다", async () => {
    const problem = {
      code: "PIPELINE_CANCELLATION_IN_PROGRESS",
      detail: "다른 취소 시도가 진행 중입니다.",
      request_id: "request-1",
      status: 409,
      title: "다른 취소 시도가 진행 중입니다.",
      type: "https://kor-travel-map/errors/pipeline-cancellation-in-progress",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<FetchMock>(() =>
        Promise.resolve(
          new Response(JSON.stringify(problem), {
            status: 409,
            headers: {
              "Content-Type": "application/problem+json",
              "Retry-After": "15",
            },
          }),
        ),
      ),
    );

    const error = await postJson("/v1/ops/pipeline/executions/import_job/1/cancel", {
      reason: "test",
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiClientError);
    expect(error).toMatchObject({
      status: 409,
      problem,
      retryAfterSeconds: 15,
    });
    expect((error as ApiClientError).message).toContain("재시도: 15초 후");
  });
});
