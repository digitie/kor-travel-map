import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET } from "./route";

vi.mock("@/lib/auth", () => ({
  adminUsernameFromEnv: () => "proxy-test-admin",
  requestHasValidSession: () => Promise.resolve(true),
}));

describe("admin API proxy response headers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("ops 관측 read를 same-origin BFF principal로 전달한다", async () => {
    vi.stubEnv(
      "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
      "ops-observability-proxy-secret",
    );
    const fetchMock = vi.fn(
      (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return Promise.resolve(
          Response.json({ data: { items: [] }, meta: { duration_ms: 0 } }),
        );
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest(
      "http://127.0.0.1:12705/api/proxy/v1/ops/consistency/reports",
    );

    const response = await GET(request, {
      params: Promise.resolve({
        path: ["v1", "ops", "consistency", "reports"],
      }),
    });

    expect(response.status).toBe(200);
    const forwarded = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(forwarded.get("x-kor-travel-map-actor")).toBe("proxy-test-admin");
    expect(forwarded.get("x-kor-travel-map-admin-proxy-secret")).toBe(
      "ops-observability-proxy-secret",
    );
    expect(forwarded.get("x-kor-travel-map-ops-token")).toBeNull();
  });

  it("응답 allowlist만 브라우저에 전달한다", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return Promise.resolve(
        new Response(JSON.stringify({ detail: "retry later" }), {
          status: 503,
          headers: {
            "Content-Type": "application/problem+json",
            "Retry-After": "17",
            "X-Upstream-Internal": "must-not-leak",
          },
        }),
      );
    });
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

  it("If-Match를 upstream에 보내고 ETag를 브라우저에 돌려준다", async () => {
    const targetId = "11111111-1111-4111-8111-111111111111";
    const entityTag = `"${targetId}:7"`;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return Promise.resolve(
        new Response(JSON.stringify({ data: { target_id: targetId } }), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            ETag: entityTag,
          },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest(
      "http://127.0.0.1:12705/api/proxy/v1/admin/poi-cache-targets/external-app/poi-1",
      {
        method: "DELETE",
        headers: { "If-Match": entityTag },
      },
    );

    const response = await DELETE(request, {
      params: Promise.resolve({
        path: [
          "v1",
          "admin",
          "poi-cache-targets",
          "external-app",
          "poi-1",
        ],
      }),
    });

    expect(response.status).toBe(200);
    expect(response.headers.get("etag")).toBe(entityTag);
    const forwarded = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(forwarded.get("if-match")).toBe(entityTag);
  });
});
