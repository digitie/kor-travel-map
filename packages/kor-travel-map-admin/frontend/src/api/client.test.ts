import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiClientError,
  getJson,
  idempotencyOperationKey,
  postJson,
  withIdempotencyKey,
} from "./client";

type FetchMock = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

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
  const randomUUID = vi.fn(
    () => keys.shift() ?? "ffffffff-ffff-4fff-8fff-ffffffffffff",
  );
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

  it("idempotency operation key는 canonical body digest만 노출한다", async () => {
    const first = await idempotencyOperationKey("request:create", {
      reason: "민감한 운영 사유",
      scope: { type: "feature_ids", feature_ids: ["feature-1"] },
    });
    const reordered = await idempotencyOperationKey("request:create", {
      scope: { feature_ids: ["feature-1"], type: "feature_ids" },
      reason: "민감한 운영 사유",
    });
    const changed = await idempotencyOperationKey("request:create", {
      reason: "다른 사유",
      scope: { type: "feature_ids", feature_ids: ["feature-1"] },
    });

    expect(first).toBe(reordered);
    expect(first).toMatch(/^request:create:[0-9a-f]{64}$/);
    expect(first).not.toContain("민감한 운영 사유");
    expect(changed).not.toBe(first);
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

    expect(assign).toHaveBeenCalledWith(
      "/login?next=%2Fadmin%2Fsettings%3Ftab%3Dkeys",
    );
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

    const error = await postJson(
      "/v1/ops/pipeline/executions/import_job/1/cancel",
      {
        reason: "test",
      },
    ).catch((caught: unknown) => caught);

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

  it("확정·기록된 semantic 502 뒤에는 새 idempotency key를 발급한다", async () => {
    const randomUUID = stubIdempotencyBrowser([
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    ]);
    const seen: string[] = [];
    const confirmedFailure = new ApiClientError(
      "known Dagster failure",
      502,
      "/v1/ops/pipeline/schedules/x/commands",
      {
        code: "DAGSTER_SCHEDULE_COMMAND_FAILED",
        detail: "known Dagster failure",
        details: {
          outcome_certainty: "confirmed",
          audit_status: "recorded",
        },
        errors: [],
        request_id: "request-confirmed",
        status: 502,
        title: "known Dagster failure",
        type: "https://kor-travel-map/errors/dagster-schedule-command-failed",
      },
    );

    await expect(
      withIdempotencyKey("schedule:confirmed", async (key) => {
        seen.push(key);
        throw confirmedFailure;
      }),
    ).rejects.toBe(confirmedFailure);
    await withIdempotencyKey("schedule:confirmed", async (key) => {
      seen.push(key);
      return "ok";
    });

    expect(seen).toEqual([
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    ]);
    expect(randomUUID).toHaveBeenCalledTimes(2);
  });

  it("명시적 mutation 전 storage failure 뒤에는 새 idempotency key를 발급한다", async () => {
    const randomUUID = stubIdempotencyBrowser([
      "33333333-3333-4333-8333-333333333333",
      "44444444-4444-4444-8444-444444444444",
    ]);
    const seen: string[] = [];
    const storageFailure = new ApiClientError(
      "audit storage unavailable",
      503,
      "/v1/ops/pipeline/schedules/x/commands",
      {
        code: "DAGSTER_SCHEDULE_STORAGE_UNAVAILABLE",
        detail: "audit storage unavailable",
        details: null,
        errors: [],
        request_id: "request-storage",
        status: 503,
        title: "audit storage unavailable",
        type: "https://kor-travel-map/errors/dagster-schedule-storage-unavailable",
      },
    );

    await expect(
      withIdempotencyKey("schedule:storage", async (key) => {
        seen.push(key);
        throw storageFailure;
      }),
    ).rejects.toBe(storageFailure);
    await withIdempotencyKey("schedule:storage", async (key) => {
      seen.push(key);
      return "ok";
    });

    expect(seen).toEqual([
      "33333333-3333-4333-8333-333333333333",
      "44444444-4444-4444-8444-444444444444",
    ]);
    expect(randomUUID).toHaveBeenCalledTimes(2);
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
