import { NextRequest } from "next/server";

import { adminUsernameFromEnv, requestHasValidSession } from "@/lib/auth";
import {
  buildProxyRequestInit,
  buildProxyTarget,
  forwardedProxyHeaders,
} from "@/lib/proxy";

const INTERNAL_BASE =
  process.env.KOR_TRAVEL_MAP_API_INTERNAL_URL ?? "http://127.0.0.1:12701";
const FORWARDED_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "etag",
  "retry-after",
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
    const response = await fetch(target, {
      ...buildProxyRequestInit(
        request.method,
        forwardedProxyHeaders(request.headers, adminUsernameFromEnv()),
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
