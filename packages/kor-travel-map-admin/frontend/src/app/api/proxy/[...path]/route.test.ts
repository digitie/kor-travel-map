import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET, POST } from "./route";

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

  it("manual feature create POST에 server-only raw token만 주입하고 생성 응답 header를 전달한다", async () => {
    const manualCreateToken = "manual-feature-create-token-route-test-0001";
    vi.stubEnv(
      "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
      "manual-feature-admin-proxy-secret",
    );
    vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN", manualCreateToken);
    const featureId = "0198d9f1-7a31-7e52-8ea8-cb2548d3a891";
    const entityTag = `"${featureId}:1"`;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return Promise.resolve(
        new Response(
          JSON.stringify({
            data: {
              applied_field_count: 1,
              command_id: 7,
              creation_origin: "manual_admin",
              feature_id: featureId,
              row_revision: 1,
            },
            meta: { duration_ms: 1, request_id: "manual-create-request" },
          }),
          {
            status: 201,
            headers: {
              "Content-Type": "application/json",
              ETag: entityTag,
              "Idempotency-Replayed": "true",
              Location: `/v1/admin/features/${featureId}`,
              "X-Request-ID": "manual-create-request",
              "X-Upstream-Internal": "must-not-leak",
            },
          },
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest(
      "http://127.0.0.1:12705/api/proxy/v1/admin/features",
      {
        body: JSON.stringify({
          category: "01070300",
          coord: { lon: 126.978, lat: 37.5665 },
          kind: "place",
          marker_color: "P-01",
          marker_icon: "marker",
          name: "새 장소",
          reason: "수동 생성",
        }),
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          "X-Kor-Travel-Map-Admin-Feature-Create-Token":
            "browser-token-must-not-win",
          "X-Kor-Travel-Map-Admin-Proxy-Secret":
            "browser-proxy-secret-must-not-win",
        },
        method: "POST",
      },
    );

    const response = await POST(request, {
      params: Promise.resolve({ path: ["v1", "admin", "features"] }),
    });

    expect(response.status).toBe(201);
    expect(response.headers.get("etag")).toBe(entityTag);
    expect(response.headers.get("idempotency-replayed")).toBe("true");
    expect(response.headers.get("location")).toBe(
      `/v1/admin/features/${featureId}`,
    );
    expect(response.headers.get("x-request-id")).toBe("manual-create-request");
    expect(response.headers.get("x-upstream-internal")).toBeNull();
    const forwarded = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(forwarded.get("x-kor-travel-map-admin-feature-create-token")).toBe(
      manualCreateToken,
    );
    expect(forwarded.get("x-kor-travel-map-admin-proxy-secret")).toBe(
      "manual-feature-admin-proxy-secret",
    );
    expect(forwarded.get("idempotency-key")).toBe(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    expect(forwarded.get("x-kor-travel-map-actor")).toBe("proxy-test-admin");
  });

  it("manual feature create redirect는 follow하지 않고 응답 자체만 전달한다", async () => {
    vi.stubEnv(
      "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
      "manual-feature-admin-proxy-secret",
    );
    vi.stubEnv(
      "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN",
      "manual-feature-create-token-route-test-0001",
    );
    const redirectLocation = "https://example.invalid/redirected";
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return Promise.resolve(
        new Response(null, {
          status: 303,
          headers: { Location: redirectLocation },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest(
      "http://127.0.0.1:12705/api/proxy/v1/admin/features",
      {
        body: JSON.stringify({}),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      },
    );

    const response = await POST(request, {
      params: Promise.resolve({ path: ["v1", "admin", "features"] }),
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[1]?.redirect).toBe("manual");
    const forwarded = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(forwarded.get("x-kor-travel-map-admin-feature-create-token")).toBe(
      "manual-feature-create-token-route-test-0001",
    );
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(redirectLocation);
  });

  it.each([
    ["encoded double slash", "%2F%2Fevil.example", "//evil.example"],
    ["encoded backslash", "%5C%5Cevil.example", "\\\\evil.example"],
  ])(
    "%s proxy target은 credential 조립/fetch 전에 400으로 거부한다",
    async (_label, encodedSegment, decodedSegment) => {
      const proxySecret = "manual-feature-admin-proxy-secret";
      const manualCreateToken = "manual-feature-create-token-route-test-0001";
      vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", proxySecret);
      vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN", manualCreateToken);
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);
      const request = new NextRequest(
        `http://127.0.0.1:12705/api/proxy/${encodedSegment}/v1/admin/features`,
        {
          body: JSON.stringify({}),
          headers: {
            "Content-Type": "application/json",
            "X-Kor-Travel-Map-Admin-Feature-Create-Token":
              "browser-token-must-not-leak",
            "X-Kor-Travel-Map-Admin-Proxy-Secret":
              "browser-proxy-secret-must-not-leak",
          },
          method: "POST",
        },
      );

      const response = await POST(request, {
        params: Promise.resolve({
          path: [decodedSegment, "v1", "admin", "features"],
        }),
      });

      expect(response.status).toBe(400);
      expect(response.headers.get("content-type")).toContain(
        "application/problem+json",
      );
      const problemText = JSON.stringify(await response.json());
      expect(problemText).toContain("ADMIN_PROXY_TARGET_REJECTED");
      expect(problemText).not.toContain(proxySecret);
      expect(problemText).not.toContain(manualCreateToken);
      expect(problemText).not.toContain("browser-token-must-not-leak");
      expect(problemText).not.toContain("browser-proxy-secret-must-not-leak");
      expect(problemText).not.toContain("evil.example");
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("exact create 경로가 아닌 POST에는 manual create token을 주입하지 않는다", async () => {
    vi.stubEnv(
      "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN",
      "manual-feature-create-token-route-test-0001",
    );
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({ data: { accepted: true } }, { status: 202 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest(
      "http://127.0.0.1:12705/api/proxy/v1/admin/features/some-command",
      {
        body: JSON.stringify({ reason: "not-create" }),
        headers: {
          "Content-Type": "application/json",
          "X-Kor-Travel-Map-Admin-Feature-Create-Token":
            "browser-token-must-be-dropped",
        },
        method: "POST",
      },
    );

    const response = await POST(request, {
      params: Promise.resolve({
        path: ["v1", "admin", "features", "some-command"],
      }),
    });

    expect(response.status).toBe(202);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const forwarded = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(
      forwarded.get("x-kor-travel-map-admin-feature-create-token"),
    ).toBeNull();
  });

  it.each([
    ["missing", undefined],
    ["empty", ""],
    ["too short", "short-token"],
    ["leading/trailing whitespace", " manual-feature-create-token-route-test-0001 "],
    ["internal whitespace", "manual-feature-create-token route-test-0001"],
    ["newline", "manual-feature-create-token-route-test\n0001"],
  ])(
    "manual feature create raw token %s이면 upstream fetch 전에 503으로 닫는다",
    async (_label, token) => {
      if (token === undefined) {
        vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN", "");
        delete process.env.KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN;
      } else {
        vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN", token);
      }
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);
      const request = new NextRequest(
        "http://127.0.0.1:12705/api/proxy/v1/admin/features",
        {
          body: JSON.stringify({}),
          headers: { "Content-Type": "application/json" },
          method: "POST",
        },
      );

      const response = await POST(request, {
        params: Promise.resolve({ path: ["v1", "admin", "features"] }),
      });

      expect(response.status).toBe(503);
      expect(response.headers.get("content-type")).toContain(
        "application/problem+json",
      );
      const problem = await response.json();
      expect(problem).toMatchObject({
        code: "MANUAL_FEATURE_CREATE_BFF_NOT_READY",
        detail: "Manual feature create BFF credential is not configured.",
        errors: [],
        status: 503,
        title: "Manual feature create BFF not ready",
        type: "https://kor-travel-map/errors/manual-feature-create-bff-not-ready",
      });
      expect(problem.request_id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      );
      expect(response.headers.get("x-request-id")).toBe(problem.request_id);
      if (token) {
        expect(JSON.stringify(problem)).not.toContain(token);
      }
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );
});
