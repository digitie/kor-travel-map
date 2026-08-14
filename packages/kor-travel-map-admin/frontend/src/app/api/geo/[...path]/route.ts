import { NextRequest } from "next/server";

const GEO_BASE =
  process.env.KOR_TRAVEL_GEO_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL ??
  "http://127.0.0.1:12501";
// VWorld 키로 떨어지지 않는다 — 그건 kor-travel-geo가 상류로 나갈 때 쓰는 키이고,
// geo는 그 값을 401(E0401)로 거절한다. 비어 있으면 비어 있는 채로 둔다(T-VN-H46B).
const GEO_API_KEY =
  process.env.KOR_TRAVEL_GEO_API_KEY?.trim() ||
  process.env.NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY?.trim() ||
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
  // 키가 없으면 여기서 끊는다. 그대로 보내면 geo가 400 `E0100 field=key`를 돌려주고
  // 이 프록시가 그것을 그대로 흘려보내는데, 화면에는 "invalid request data"로 보여
  // **자격증명 누락이 아니라 요청 형식 오류처럼 읽힌다.** 백엔드 쪽은 같은 응답을
  // `GeoAuthNotConfiguredError`로 옮기지만(`geocoding.py:_is_public_key_rejection`)
  // 이 프록시에는 그 대응물이 없었다.
  if (GEO_API_KEY === "") {
    return new Response(
      JSON.stringify({
        code: "GEO_API_KEY_NOT_CONFIGURED",
        message:
          "kor-travel-geo 소비자 키가 설정되지 않았다 (KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY). VWorld 키는 이 자리에 쓸 수 없다.",
      }),
      { status: 503, headers: { "content-type": "application/json" } },
    );
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
