import { afterEach, describe, expect, it } from "vitest";

import {
  checkLoginRateLimit,
  clearLoginFailures,
  hashAdminPasswordForEnv,
  recordLoginFailure,
  requestHasSameOrigin,
  verifyAdminLogin,
} from "./auth";

type AuthRequest = Parameters<typeof checkLoginRateLimit>[0];

const TRUST_PROXY_HEADERS_ENV = "KOR_TRAVEL_MAP_UI_TRUST_PROXY_HEADERS";

function requestWithHeaders(headers: Record<string, string>): AuthRequest {
  const normalized = new Map(
    Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]),
  );
  return {
    headers: {
      get(name: string) {
        return normalized.get(name.toLowerCase()) ?? null;
      },
    },
  };
}

describe("admin auth helpers", () => {
  afterEach(() => {
    clearLoginFailures(requestWithHeaders({ "x-forwarded-for": "198.51.100.10" }));
    clearLoginFailures(requestWithHeaders({ "x-forwarded-for": "spoof, 10.0.0.9" }));
    delete process.env[TRUST_PROXY_HEADERS_ENV];
    clearLoginFailures(requestWithHeaders({}));
  });

  it("X-Forwarded-For는 기본값에서 로그인 rate-limit 우회에 쓰이지 않는다", () => {
    const now = 1_800_000_000_000;
    for (let index = 0; index < 5; index += 1) {
      recordLoginFailure(
        requestWithHeaders({ "x-forwarded-for": `198.51.100.${index}` }),
        now + index,
      );
    }

    const result = checkLoginRateLimit(
      requestWithHeaders({ "x-forwarded-for": "203.0.113.55" }),
      now + 5,
    );

    expect(result.allowed).toBe(false);
  });

  it("신뢰 proxy header opt-in 시 X-Forwarded-For 오른쪽 엔트리로 rate-limit을 묶는다", () => {
    process.env[TRUST_PROXY_HEADERS_ENV] = "true";
    const now = 1_800_000_000_000;
    for (let index = 0; index < 5; index += 1) {
      recordLoginFailure(
        requestWithHeaders({ "x-forwarded-for": `spoof-${index}, 10.0.0.9` }),
        now + index,
      );
    }

    const result = checkLoginRateLimit(
      requestWithHeaders({ "x-forwarded-for": "another-spoof, 10.0.0.9" }),
      now + 5,
    );

    expect(result.allowed).toBe(false);
  });

  it("username이 달라도 비밀번호 검증 결과를 합쳐 invalid로 처리한다", async () => {
    const env = {
      KOR_TRAVEL_MAP_UI_ADMIN_USERNAME: "admin",
      KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH: await hashAdminPasswordForEnv("ad.min"),
      KOR_TRAVEL_MAP_UI_SESSION_SECRET: "x".repeat(32),
    };

    await expect(
      verifyAdminLogin({ username: "not-admin", password: "ad.min" }, env),
    ).resolves.toBe("invalid");
  });
});

describe("requestHasSameOrigin (CSRF origin check)", () => {
  // 프록시가 X-Forwarded-Proto를 안 보내 내부적으로 http로 보이는 요청을 모사.
  function req(origin: string | null): AuthRequest {
    const all: Record<string, string | null> = { origin };
    return {
      headers: { get: (n: string) => all[n.toLowerCase()] ?? null },
      nextUrl: { host: "internal:12705", protocol: "http:" },
    } as AuthRequest;
  }
  const env = {
    KOR_TRAVEL_MAP_UI_PUBLIC_ORIGINS:
      "https://map.example.org, https://www.map.example.org",
  };

  it("Origin 헤더가 없으면 통과", () => {
    expect(requestHasSameOrigin(req(null), env)).toBe(true);
  });
  it("재구성된 same-origin이면 통과(화이트리스트 불필요)", () => {
    expect(requestHasSameOrigin(req("http://internal:12705"), env)).toBe(true);
  });
  it("프록시가 proto를 빼먹어도, 신뢰 공개 origin이면 통과", () => {
    expect(requestHasSameOrigin(req("https://map.example.org"), env)).toBe(true);
  });
  it("화이트리스트에 없는 외부 origin은 거부(CSRF 방어 유지)", () => {
    expect(requestHasSameOrigin(req("https://evil.example"), env)).toBe(false);
  });
  it("화이트리스트 미설정이면 헤더 기반 검사만(불일치 origin 거부)", () => {
    expect(requestHasSameOrigin(req("https://map.example.org"), {})).toBe(false);
  });
});
