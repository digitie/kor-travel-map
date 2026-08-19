import { NextRequest } from "next/server";

import { adminUsernameFromEnv, requestHasValidSession } from "@/lib/auth";
import {
  appendManualFeatureCreateHeaders,
  buildProxyRequestInit,
  buildProxyTarget,
  forwardedProxyHeaders,
  ProxyTargetError,
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

function problemJson(
  status: number,
  code: string,
  detail: string,
  title = detail,
): Response {
  const requestId = crypto.randomUUID();
  return Response.json(
    {
      type: `https://kor-travel-map/errors/${code.toLowerCase().replaceAll("_", "-")}`,
      title,
      status,
      detail,
      code,
      errors: [],
      request_id: requestId,
    },
    {
      status,
      headers: {
        "Content-Type": "application/problem+json",
        "X-Request-ID": requestId,
      },
    },
  );
}

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
  let target: URL;
  try {
    target = buildProxyTarget(params.path, request.nextUrl.search, INTERNAL_BASE);
  } catch (error) {
    if (error instanceof ProxyTargetError) {
      return problemJson(error.status, error.code, error.message);
    }
    throw error;
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
        return problemJson(
          503,
          "MANUAL_FEATURE_CREATE_BFF_NOT_READY",
          "Manual feature create BFF credential is not configured.",
          "Manual feature create BFF not ready",
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
      redirect: "manual",
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
