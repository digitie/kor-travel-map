import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

describe("frontend build info", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each([undefined, "development", "a".repeat(39), "G".repeat(40)])(
    "exact Git SHA가 아니면 fail-closed한다: %s",
    async (revision) => {
      vi.stubEnv("NEXT_PUBLIC_KOR_TRAVEL_MAP_GIT_COMMIT", revision);

      const response = GET();

      expect(response.status).toBe(503);
      expect(response.headers.get("cache-control")).toContain("no-store");
      await expect(response.json()).resolves.toEqual({
        error: "BUILD_REVISION_UNAVAILABLE",
      });
    },
  );

  it("빌드에 박힌 exact Git SHA를 no-store로 반환한다", async () => {
    const revision = "a".repeat(40);
    vi.stubEnv("NEXT_PUBLIC_KOR_TRAVEL_MAP_GIT_COMMIT", revision);

    const response = GET();

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    await expect(response.json()).resolves.toEqual({ revision });
  });
});
