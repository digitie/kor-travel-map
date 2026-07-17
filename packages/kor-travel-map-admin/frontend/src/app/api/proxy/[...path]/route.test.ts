import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

vi.mock("@/lib/auth", () => ({
  adminUsernameFromEnv: () => "proxy-test-admin",
  requestHasValidSession: () => Promise.resolve(true),
}));

describe("admin API proxy response headers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("upstream Retry-After만 응답 allowlist를 통해 브라우저에 전달한다", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
        Promise.resolve(
          new Response(JSON.stringify({ detail: "retry later" }), {
            status: 503,
            headers: {
              "Content-Type": "application/problem+json",
              "Retry-After": "17",
              "X-Upstream-Internal": "must-not-leak",
            },
          }),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest(
      "http://127.0.0.1:12705/api/proxy/v1/ops/pipeline/executions",
      {
        headers: {
          "Idempotency-Key": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          "X-Browser-Secret": "must-not-forward",
        },
      },
    );

    const response = await GET(request, {
      params: Promise.resolve({
        path: ["v1", "ops", "pipeline", "executions"],
      }),
    });

    expect(response.status).toBe(503);
    expect(response.headers.get("content-type")).toContain(
      "application/problem+json",
    );
    expect(response.headers.get("retry-after")).toBe("17");
    expect(response.headers.get("x-upstream-internal")).toBeNull();
    const forwarded = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(forwarded.get("idempotency-key")).toBe(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    expect(forwarded.get("x-browser-secret")).toBeNull();
    expect(forwarded.get("x-kor-travel-map-actor")).toBe("proxy-test-admin");
  });
});
