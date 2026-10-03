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

  it("감사 API가 응답하지 않아도 짧은 timeout 뒤 로그인 흐름으로 돌아온다", async () => {
    // 로그인은 감사 기록 저장에 의존하지 않는다 — 걸린 fetch가 로그인 응답을 붙잡으면 안 된다.
    const controller = new AbortController();
    const timeoutSpy = vi
      .spyOn(AbortSignal, "timeout")
      .mockReturnValue(controller.signal);
    const fetchMock = vi.fn(
      (_target: unknown, options: RequestInit) =>
        new Promise((_resolve, reject) => {
          options.signal?.addEventListener("abort", () =>
            reject(new DOMException("timed out", "TimeoutError")),
          );
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = { headers: new Headers() } as unknown as NextRequest;

    const pending = recordAuthAuditEvent(request, {
      eventType: "login",
      outcome: "failed",
      reason: "invalid_credentials",
    });
    expect(timeoutSpy).toHaveBeenCalledTimes(1);
    const [timeoutMs] = timeoutSpy.mock.calls[0] as [number];
    expect(timeoutMs).toBeGreaterThan(0);
    expect(timeoutMs).toBeLessThanOrEqual(5_000);
    const [, options] = fetchMock.mock.calls[0] as [unknown, RequestInit];
    expect(options.signal).toBe(controller.signal);

    controller.abort();
    await expect(pending).resolves.toBeUndefined();
    timeoutSpy.mockRestore();
  });
});
