const ALLOWED_FORWARD_HEADERS = new Set(["accept", "content-type", "user-agent"]);
const ADMIN_PROXY_SECRET_ENV = "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET";

export type ProxyRequestInit = RequestInit & { duplex?: "half" };

export function buildProxyTarget(
  pathSegments: string[],
  search: string,
  internalBase: string,
): URL | null {
  const target = new URL(`/${pathSegments.join("/")}`, internalBase);
  target.search = search;
  if (
    target.pathname === "/health" ||
    target.pathname === "/version" ||
    target.pathname.startsWith("/v1/")
  ) {
    return target;
  }
  return null;
}

export function forwardedProxyHeaders(
  source: Headers,
  actor: string,
  env: Record<string, string | undefined> = process.env,
): Headers {
  const headers = new Headers();
  source.forEach((value, key) => {
    if (ALLOWED_FORWARD_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });
  headers.set("X-Kor-Travel-Map-Actor", actor);
  const proxySecret = env[ADMIN_PROXY_SECRET_ENV]?.trim();
  if (proxySecret) {
    headers.set("X-Kor-Travel-Map-Admin-Proxy-Secret", proxySecret);
  }
  return headers;
}

export function buildProxyRequestInit(
  method: string,
  headers: Headers,
  body: ReadableStream<Uint8Array> | null,
  signal?: AbortSignal,
): ProxyRequestInit {
  const init: ProxyRequestInit = {
    method,
    headers,
    cache: "no-store",
    signal,
  };
  if (method !== "GET" && method !== "HEAD" && body !== null) {
    init.body = body;
    init.duplex = "half";
  }
  return init;
}
