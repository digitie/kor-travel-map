import { afterEach, describe, expect, it, vi } from "vitest";

import { getJson, postJson } from "./client";

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
});
