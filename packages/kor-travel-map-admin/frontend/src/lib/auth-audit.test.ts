// @vitest-environment node

import type { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { recordAuthAuditEvent } from "./auth-audit";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("admin 인증 감사", () => {
  it("각 기록 요청을 UUID idempotency key와 함께 전송한다", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET", "a".repeat(32));
    const request = {
      headers: new Headers({ "x-request-id": "e2e-auth-audit" }),
    } as unknown as NextRequest;

    await recordAuthAuditEvent(request, {
      attemptedUsername: "admin",
      eventType: "login",
      outcome: "succeeded",
      reason: "authenticated",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [target, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(target).pathname).toBe("/v1/admin/auth-events");
    expect(new Headers(options.headers).get("idempotency-key")).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
    expect(JSON.parse(String(options.body))).toMatchObject({
      request_id: "e2e-auth-audit",
    });
  });
});
