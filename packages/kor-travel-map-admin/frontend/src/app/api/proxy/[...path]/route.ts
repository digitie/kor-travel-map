import { NextRequest } from "next/server";

import { adminUsernameFromEnv, requestHasValidSession } from "@/lib/auth";
import {
  appendManualFeatureCreateHeaders,
  buildProxyRequestInit,
  buildProxyTarget,
  forwardedProxyHeaders,
} from "@/lib/proxy";
import { ManualFeatureCreateCredentialError } from "@/lib/manual-feature-create";

const INTERNAL_BASE =
  process.env.KOR_TRAVEL_MAP_API_INTERNAL_URL ?? "http://127.0.0.1:12701";
const FORWARDED_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "etag",
  "idempotency-replayed",
  "location",
  "retry-after",
  "x-request-id",
] as const;

function forwardedResponseHeaders(source: Headers): Array<[string, string]> {
  const headers = FORWARDED_RESPONSE_HEADERS.flatMap(
    (name): Array<[string, string]> => {
      const value = source.get(name);
      return value === null ? [] : [[name, value]];
    },
  );
  return source.has("content-type")
    ? headers
    : [...headers, ["content-type", "application/json"]];
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const params = await context.params;
  const target = buildProxyTarget(params.path, request.nextUrl.search, INTERNAL_BASE);
  if (target === null) {
    return new Response("Forbidden", { status: 403 });
  }
  if (!(await requestHasValidSession(request))) {
    return Response.json({ error: "AUTH_REQUIRED" }, { status: 401 });
  }
  try {
    let headers: Headers;
    try {
      headers = appendManualFeatureCreateHeaders(
        forwardedProxyHeaders(request.headers, adminUsernameFromEnv()),
        request.method,
        target.pathname,
      );
    } catch (error) {
      if (error instanceof ManualFeatureCreateCredentialError) {
        return Response.json(
          { error: "MANUAL_FEATURE_CREATE_BFF_NOT_READY" },
          { status: 503 },
        );
      }
      throw error;
    }
    const response = await fetch(target, {
      ...buildProxyRequestInit(
        request.method,
        headers,
        request.body,
        request.signal,
      ),
    });
    return new Response(response.body, {
      status: response.status,
      headers: forwardedResponseHeaders(response.headers),
    });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    throw error;
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
