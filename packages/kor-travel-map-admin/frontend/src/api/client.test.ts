import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiClientError,
  getJson,
  postJson,
  withIdempotencyKey,
} from "./client";

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

function stubIdempotencyBrowser(keys: string[]) {
  const values = new Map<string, string>();
  const randomUUID = vi.fn(() => keys.shift() ?? "ffffffff-ffff-4fff-8fff-ffffffffffff");
  vi.stubGlobal("crypto", { randomUUID });
  vi.stubGlobal("window", {
    sessionStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      removeItem: (key: string) => values.delete(key),
      setItem: (key: string, value: string) => values.set(key, value),
    },
  });
  return randomUUID;
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

  it("network 결과가 불명확하면 같은 idempotency key를 재사용하고 성공 후 폐기한다", async () => {
    const randomUUID = stubIdempotencyBrowser([
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    ]);
    const seen: string[] = [];

    await expect(
      withIdempotencyKey("schedule:network", async (key) => {
        seen.push(key);
        throw new TypeError("network interrupted");
      }),
    ).rejects.toThrow("network interrupted");
    await withIdempotencyKey("schedule:network", async (key) => {
      seen.push(key);
      return "ok";
    });
    await withIdempotencyKey("schedule:network", async (key) => {
      seen.push(key);
      return "ok";
    });

    expect(seen).toEqual([
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    ]);
    expect(randomUUID).toHaveBeenCalledTimes(2);
  });

  it("idempotency conflict도 결과 확인 전까지 같은 key를 유지한다", async () => {
    const randomUUID = stubIdempotencyBrowser([
      "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    ]);
    const seen: string[] = [];
    const conflict = new ApiClientError(
      "command result uncertain",
      409,
      "/v1/ops/pipeline/schedules/x/commands",
      {
        code: "DAGSTER_SCHEDULE_IDEMPOTENCY_CONFLICT",
        detail: "command result uncertain",
        errors: [],
        request_id: "request-1",
        status: 409,
        title: "command result uncertain",
        type: "https://kor-travel-map/errors/dagster-schedule-idempotency-conflict",
      },
    );

    await expect(
      withIdempotencyKey("schedule:conflict", async (key) => {
        seen.push(key);
        throw conflict;
      }),
    ).rejects.toBe(conflict);
    await withIdempotencyKey("schedule:conflict", async (key) => {
      seen.push(key);
      return "ok";
    });

    expect(seen).toEqual([
      "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    ]);
    expect(randomUUID).toHaveBeenCalledTimes(1);
  });

  it("terminal audit 결과가 불명확한 성공 응답도 같은 key를 유지한다", async () => {
    const randomUUID = stubIdempotencyBrowser([
      "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    ]);
    const seen: string[] = [];
    const operation = async (key: string) => {
      seen.push(key);
      return { audit_status: "terminal_record_failed" as const };
    };

    await withIdempotencyKey("schedule:audit", operation, {
      retainOnSuccess: (result) =>
        result.audit_status === "terminal_record_failed",
    });
    await withIdempotencyKey("schedule:audit", operation, {
      retainOnSuccess: (result) =>
        result.audit_status === "terminal_record_failed",
    });

    expect(seen).toEqual([
      "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    ]);
    expect(randomUUID).toHaveBeenCalledTimes(1);
  });

  it.each([408, 425, 429, 499, 500, 502, 503])(
    "HTTP %s 불확실 응답은 같은 idempotency key를 유지한다",
    async (status) => {
      const randomUUID = stubIdempotencyBrowser([
        "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      ]);
      const seen: string[] = [];
      const error = new ApiClientError(
        "uncertain transport",
        status,
        "/v1/ops/pipeline/schedules/x/commands",
      );

      await expect(
        withIdempotencyKey(`schedule:http:${status}`, async (key) => {
          seen.push(key);
          throw error;
        }),
      ).rejects.toBe(error);
      await withIdempotencyKey(`schedule:http:${status}`, async (key) => {
        seen.push(key);
        return "ok";
      });

      expect(seen).toEqual([
        "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      ]);
      expect(randomUUID).toHaveBeenCalledTimes(1);
    },
  );
});
