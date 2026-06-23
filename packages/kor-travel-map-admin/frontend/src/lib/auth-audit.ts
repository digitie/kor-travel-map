import type { NextRequest } from "next/server";

const INTERNAL_BASE =
  process.env.KOR_TRAVEL_MAP_API_INTERNAL_URL ?? "http://127.0.0.1:12701";
const ADMIN_PROXY_SECRET_ENV = "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET";
const TRUST_PROXY_HEADERS_ENV = "KOR_TRAVEL_MAP_UI_TRUST_PROXY_HEADERS";
const AUTH_AUDIT_ACTOR = "ui-auth";

type AuthAuditEvent = {
  attemptedUsername?: string | null;
  eventType: "login" | "logout";
  nextPath?: string | null;
  outcome: "succeeded" | "failed" | "denied";
  reason?: string | null;
};

export async function recordAuthAuditEvent(
  request: NextRequest,
  event: AuthAuditEvent,
): Promise<void> {
  const headers = new Headers({
    "content-type": "application/json",
    "x-kor-travel-map-actor": AUTH_AUDIT_ACTOR,
  });
  const proxySecret = process.env[ADMIN_PROXY_SECRET_ENV]?.trim();
  if (proxySecret) {
    headers.set("x-kor-travel-map-admin-proxy-secret", proxySecret);
  }
  try {
    const target = new URL("/v1/admin/auth-events", INTERNAL_BASE);
    await fetch(target, {
      method: "POST",
      headers,
      cache: "no-store",
      body: JSON.stringify({
        attempted_username: event.attemptedUsername?.trim() || null,
        actor: AUTH_AUDIT_ACTOR,
        client_ip: clientIpFromRequest(request),
        event_type: event.eventType,
        next_path: event.nextPath ?? null,
        outcome: event.outcome,
        reason: event.reason ?? null,
        request_id: request.headers.get("x-request-id"),
        user_agent: request.headers.get("user-agent"),
      }),
    });
  } catch {
    // Login/logout availability must not depend on audit persistence.
  }
}

function clientIpFromRequest(request: NextRequest): string | null {
  if (!trustProxyHeaders()) {
    return null;
  }
  return (
    lastForwardedValue(request.headers.get("x-forwarded-for")) ??
    firstForwardedValue(request.headers.get("x-real-ip"))
  );
}

function firstForwardedValue(value: string | null): string | null {
  return value?.split(",")[0]?.trim() || null;
}

function lastForwardedValue(value: string | null): string | null {
  const parts = value?.split(",").map((part) => part.trim()).filter(Boolean) ?? [];
  return parts.length > 0 ? (parts[parts.length - 1] ?? null) : null;
}

function trustProxyHeaders(): boolean {
  const value = process.env[TRUST_PROXY_HEADERS_ENV]?.trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}
