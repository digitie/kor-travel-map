import { NextRequest } from "next/server";

const GEO_BASE =
  process.env.KOR_TRAVEL_GEO_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL ??
  "http://127.0.0.1:12501";
const GEO_API_KEY =
  process.env.KOR_TRAVEL_GEO_API_KEY?.trim() ||
  process.env.NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY?.trim() ||
  process.env.NEXT_PUBLIC_VWORLD_API_KEY?.trim() ||
  "";

type GeoProxyRequestInit = RequestInit & { duplex?: "half" };

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const params = await context.params;
  const target = buildGeoTarget(params.path, request.nextUrl.search);
  if (target === null) {
    return new Response("Forbidden", { status: 403 });
  }
  const init: GeoProxyRequestInit = {
    method: request.method,
    headers: forwardedHeaders(request.headers),
    cache: "no-store",
    signal: request.signal,
  };
  if (request.method !== "GET" && request.method !== "HEAD" && request.body !== null) {
    init.body = request.body;
    init.duplex = "half";
  }
  const response = await fetch(target, init);
  return new Response(response.body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}

function buildGeoTarget(path: readonly string[], search: string): URL | null {
  if (path.length === 0 || path.some((segment) => segment.length === 0)) {
    return null;
  }
  const base = GEO_BASE.endsWith("/") ? GEO_BASE : `${GEO_BASE}/`;
  const target = new URL(path.map(encodeURIComponent).join("/"), base);
  const params = new URLSearchParams(search);
  for (const [key, value] of params) {
    target.searchParams.append(key, value);
  }
  if (GEO_API_KEY && !target.searchParams.has("key")) {
    target.searchParams.set("key", GEO_API_KEY);
  }
  return target;
}

function forwardedHeaders(headers: Headers): Headers {
  const result = new Headers();
  const accept = headers.get("accept");
  const contentType = headers.get("content-type");
  if (accept) result.set("accept", accept);
  if (contentType) result.set("content-type", contentType);
  return result;
}

export const GET = proxy;
export const POST = proxy;
