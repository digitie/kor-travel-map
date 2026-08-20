import {
  ADMIN_FEATURE_CREATE_PATH,
  ADMIN_FEATURE_CREATE_TOKEN_HEADER,
  manualFeatureCreateToken,
} from "@/lib/manual-feature-create";

const ALLOWED_FORWARD_HEADERS = new Set([
  "accept",
  "content-type",
  "idempotency-key",
  "if-match",
  "user-agent",
]);
const ADMIN_PROXY_SECRET_ENV = "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET";
const ALLOWED_PROXY_BASE_PROTOCOLS = new Set(["http:", "https:"]);

export type ProxyRequestInit = RequestInit & { duplex?: "half" };

export class ProxyTargetError extends Error {
  constructor(
    public status: 400 | 502,
    public code:
      | "ADMIN_PROXY_INTERNAL_BASE_INVALID"
      | "ADMIN_PROXY_TARGET_REJECTED",
    message: string,
  ) {
    super(message);
    this.name = "ProxyTargetError";
  }
}

function safeDecodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    throw new ProxyTargetError(
      400,
      "ADMIN_PROXY_TARGET_REJECTED",
      "proxy target path is invalid",
    );
  }
}

function parseInternalBase(internalBase: string): URL {
  let base: URL;
  try {
    base = new URL(internalBase);
  } catch {
    throw new ProxyTargetError(
      502,
      "ADMIN_PROXY_INTERNAL_BASE_INVALID",
      "proxy internal base is invalid",
    );
  }
  if (
    !ALLOWED_PROXY_BASE_PROTOCOLS.has(base.protocol) ||
    base.username.length > 0 ||
    base.password.length > 0
  ) {
    throw new ProxyTargetError(
      502,
      "ADMIN_PROXY_INTERNAL_BASE_INVALID",
      "proxy internal base is invalid",
    );
  }
  return base;
}

function safeProxyPath(pathSegments: string[]): string {
  const encodedSegments = pathSegments.map((segment) => {
    const decoded = safeDecodeSegment(segment);
    if (decoded.includes("/") || decoded.includes("\\")) {
      throw new ProxyTargetError(
        400,
        "ADMIN_PROXY_TARGET_REJECTED",
        "proxy target path is invalid",
      );
    }
    try {
      return encodeURIComponent(decoded);
    } catch {
      throw new ProxyTargetError(
        400,
        "ADMIN_PROXY_TARGET_REJECTED",
        "proxy target path is invalid",
      );
    }
  });
  return `/${encodedSegments.join("/")}`;
}

export function buildProxyTarget(
  pathSegments: string[],
  search: string,
  internalBase: string,
): URL {
  const base = parseInternalBase(internalBase);
  let target: URL;
  try {
    target = new URL(safeProxyPath(pathSegments), base);
  } catch (error) {
    if (error instanceof ProxyTargetError) {
      throw error;
    }
    throw new ProxyTargetError(
      400,
      "ADMIN_PROXY_TARGET_REJECTED",
      "proxy target path is invalid",
    );
  }
  target.search = search;
  if (target.protocol !== base.protocol || target.origin !== base.origin) {
    throw new ProxyTargetError(
      400,
      "ADMIN_PROXY_TARGET_REJECTED",
      "proxy target path is invalid",
    );
  }
  if (
    target.pathname === "/health" ||
    target.pathname === "/version" ||
    target.pathname.startsWith("/v1/")
  ) {
    return target;
  }
  throw new ProxyTargetError(
    400,
    "ADMIN_PROXY_TARGET_REJECTED",
    "proxy target path is invalid",
  );
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

export function appendManualFeatureCreateHeaders(
  headers: Headers,
  method: string,
  pathname: string,
  env: Record<string, string | undefined> = process.env,
): Headers {
  if (method.toUpperCase() !== "POST" || pathname !== ADMIN_FEATURE_CREATE_PATH) {
    return headers;
  }
  const token = manualFeatureCreateToken(env);
  headers.set(ADMIN_FEATURE_CREATE_TOKEN_HEADER, token);
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
