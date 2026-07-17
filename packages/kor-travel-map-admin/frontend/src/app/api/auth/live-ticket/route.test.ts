import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OPS_LIVE_PROTOCOL_PREFIX } from "@/lib/ops-live-contract";

import { POST } from "./route";

const authState = vi.hoisted(() => ({
  actor: "ticket-test-admin",
  sameOrigin: true,
  validSession: true,
}));

vi.mock("@/lib/auth", () => ({
  adminUsernameFromEnv: () => authState.actor,
  requestHasSameOrigin: () => authState.sameOrigin,
  requestHasValidSession: () => Promise.resolve(authState.validSession),
}));

function request(headers?: Record<string, string>) {
  return new NextRequest("http://127.0.0.1:12705/api/auth/live-ticket", {
    method: "POST",
    headers: {
      Origin: "http://127.0.0.1:12705",
      "Sec-Fetch-Site": "same-origin",
      ...headers,
    },
  });
}

describe("ops live ticket BFF", () => {
  afterEach(() => {
    authState.actor = "ticket-test-admin";
    authState.sameOrigin = true;
    authState.validSession = true;
    vi.unstubAllEnvs();
  });

  it("로그아웃 session에는 ticket을 발급하지 않는다", async () => {
    authState.validSession = false;
    vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", "x".repeat(32));

    const response = await POST(request());

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "AUTH_REQUIRED" });
    expect(response.headers.get("cache-control")).toContain("no-store");
  });

  it("cross-origin 발급 요청을 session 검증 전에 거절한다", async () => {
    authState.sameOrigin = false;
    vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", "x".repeat(32));

    const response = await POST(request());

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ error: "INVALID_ORIGIN" });
  });

  it.each([
    ["Origin", { Origin: "" }],
    ["Sec-Fetch-Site", { "Sec-Fetch-Site": "" }],
    ["cross-site Fetch Metadata", { "Sec-Fetch-Site": "cross-site" }],
  ])("%s가 없거나 허용되지 않으면 fail-closed한다", async (_label, headers) => {
    vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", "x".repeat(32));

    const response = await POST(request(headers));

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ error: "INVALID_ORIGIN" });
  });

  it("server-only secret이 없거나 짧으면 fail-closed한다", async () => {
    vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", "short");

    const response = await POST(request());

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: "LIVE_AUTH_MISCONFIGURED",
    });
  });

  it("actor 설정이 auth audit 계약보다 길면 fail-closed한다", async () => {
    authState.actor = "a".repeat(81);
    vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", "x".repeat(32));

    const response = await POST(request());

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: "LIVE_AUTH_MISCONFIGURED",
    });
  });

  it("로그인 session에 actor-bound subprotocol ticket만 발급한다", async () => {
    const secret = "server-only-live-ticket-secret-32+";
    vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", secret);

    const response = await POST(request());
    const body = (await response.json()) as {
      expires_at: string;
      subprotocol: string;
    };

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(body.subprotocol).toMatch(
      new RegExp(`^${OPS_LIVE_PROTOCOL_PREFIX.replaceAll(".", "\\.")}`),
    );
    expect(body.subprotocol).not.toContain(secret);
    expect(new URL(request().url).search).toBe("");
    expect(Number.isNaN(Date.parse(body.expires_at))).toBe(false);
  });
});
