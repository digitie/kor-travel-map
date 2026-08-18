import { NextRequest } from "next/server";

const GEO_BASE =
  process.env.KOR_TRAVEL_GEO_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL ??
  "http://127.0.0.1:12501";
type GeoProxyRequestInit = RequestInit & { duplex?: "half" };
const GEO_API_KEY_ENV = "KOR_TRAVEL_GEO_API_KEY";
const GEO_API_KEY_HEADER = "X-KTG-API-Key";
const GEO_API_KEY_PATTERN = /^[A-Za-z0-9]{32}$/;

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const params = await context.params;
  const apiKey = process.env[GEO_API_KEY_ENV] ?? "";
  if (!GEO_API_KEY_PATTERN.test(apiKey)) {
    return Response.json(
      {
        detail: "kor-travel-geo 공개 API 키 설정이 유효하지 않습니다.",
        code: "GEO_API_KEY_NOT_CONFIGURED",
      },
      { status: 503 },
    );
  }
  const target = buildGeoTarget(params.path, request.nextUrl.search);
  if (target === null) {
    return new Response("Forbidden", { status: 403 });
  }
  const init: GeoProxyRequestInit = {
    method: request.method,
    headers: forwardedHeaders(request.headers, apiKey),
    cache: "no-store",
    signal: request.signal,
  };
  if (request.method !== "GET" && request.method !== "HEAD" && request.body !== null) {
    init.body = request.body;
    init.duplex = "half";
  }
  const response = await fetch(target, init);
  if (await isGeoCredentialRejection(response)) {
    return Response.json(
      {
        detail: "kor-travel-geo가 Map UI 공개 API 키를 거부했습니다.",
        code: "GEO_API_KEY_REJECTED",
      },
      { status: 503 },
    );
  }
  return new Response(response.body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}

function buildGeoTarget(
  path: readonly string[],
  search: string,
): URL | null {
  if (
    path.length === 0 ||
    path.some(
      (segment) => segment.length === 0 || segment === "." || segment === "..",
    )
  ) {
    return null;
  }
  const base = GEO_BASE.endsWith("/") ? GEO_BASE : `${GEO_BASE}/`;
  const target = new URL(path.map(encodeURIComponent).join("/"), base);
  const params = new URLSearchParams(search);
  for (const [key, value] of params) {
    if (key === "key") continue;
    target.searchParams.append(key, value);
  }
  return target;
}

function forwardedHeaders(headers: Headers, apiKey: string): Headers {
  const result = new Headers();
  const accept = headers.get("accept");
  const contentType = headers.get("content-type");
  if (accept) result.set("accept", accept);
  if (contentType) result.set("content-type", contentType);
  result.set(GEO_API_KEY_HEADER, apiKey);
  return result;
}

async function isGeoCredentialRejection(response: Response): Promise<boolean> {
  if (response.status === 401) return true;
  if (response.status !== 400) return false;

  let payload: unknown;
  try {
    payload = await response.clone().json();
  } catch {
    return false;
  }
  if (!isRecord(payload) || !isRecord(payload.error)) return false;
  return payload.error.code === "E0100" && payload.error.field === "key";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export const GET = proxy;
export const POST = proxy;
