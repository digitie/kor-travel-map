import { describe, expect, it } from "vitest";

import { buildProxyTarget, ProxyTargetError } from "./proxy";

function expectProxyTargetError(
  action: () => unknown,
  status: 400 | 502,
  code: ProxyTargetError["code"],
) {
  expect(action).toThrow(ProxyTargetError);
  try {
    action();
  } catch (error) {
    expect(error).toMatchObject({ code, status });
  }
}

describe("buildProxyTarget", () => {
  it("valid internal http base에 대해 internal origin target만 만든다", () => {
    const target = buildProxyTarget(
      ["v1", "admin", "features"],
      "?page_size=20",
      "http://127.0.0.1:12701/internal-base-ignored",
    );

    expect(target.origin).toBe("http://127.0.0.1:12701");
    expect(target.pathname).toBe("/v1/admin/features");
    expect(target.search).toBe("?page_size=20");
  });

  it("non-http internal base는 502로 거부한다", () => {
    expectProxyTargetError(
      () => buildProxyTarget(["v1", "admin", "features"], "", "file:///tmp/api"),
      502,
      "ADMIN_PROXY_INTERNAL_BASE_INVALID",
    );
  });

  it("credential-bearing internal base는 502로 거부한다", () => {
    expectProxyTargetError(
      () =>
        buildProxyTarget(
          ["v1", "admin", "features"],
          "",
          "http://user:password@127.0.0.1:12701",
        ),
      502,
      "ADMIN_PROXY_INTERNAL_BASE_INVALID",
    );
  });

  it("authority-changing empty first segment는 400으로 거부한다", () => {
    expectProxyTargetError(
      () =>
        buildProxyTarget(
          ["", "evil.example", "v1", "admin", "features"],
          "",
          "http://127.0.0.1:12701",
        ),
      400,
      "ADMIN_PROXY_TARGET_REJECTED",
    );
  });

  it("malformed Unicode segment는 500 대신 400으로 정규화한다", () => {
    expectProxyTargetError(
      () =>
        buildProxyTarget(
          ["v1", "admin", "\uD800"],
          "",
          "http://127.0.0.1:12701",
        ),
      400,
      "ADMIN_PROXY_TARGET_REJECTED",
    );
  });

  it("host-looking first segment도 internal allowlist path가 아니면 400으로 거부한다", () => {
    expectProxyTargetError(
      () =>
        buildProxyTarget(
          ["evil.example", "v1", "admin", "features"],
          "",
          "http://127.0.0.1:12701",
        ),
      400,
      "ADMIN_PROXY_TARGET_REJECTED",
    );
  });
});
