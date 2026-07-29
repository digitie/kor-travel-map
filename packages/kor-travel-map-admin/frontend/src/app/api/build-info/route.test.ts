import { describe, expect, it } from "vitest";

import { buildInfoResponse } from "./route";

describe("frontend build info", () => {
  it.each([
    [undefined, "a".repeat(64)],
    ["development", "a".repeat(64)],
    ["a".repeat(39), "a".repeat(64)],
    ["G".repeat(40), "a".repeat(64)],
    ["a".repeat(40), "development"],
    ["a".repeat(40), "a".repeat(63)],
  ])(
    "exact Git SHA와 source digest가 아니면 fail-closed한다: %s / %s",
    async (revision, sourceDigest) => {
      const response = buildInfoResponse(revision, sourceDigest);

      expect(response.status).toBe(503);
      expect(response.headers.get("cache-control")).toContain("no-store");
      await expect(response.json()).resolves.toEqual({
        error: "BUILD_REVISION_UNAVAILABLE",
      });
    },
  );

  it("빌드에 박힌 exact Git SHA를 no-store로 반환한다", async () => {
    const revision = "a".repeat(40);
    const sourceDigest = "b".repeat(64);

    const response = buildInfoResponse(revision, sourceDigest);

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    await expect(response.json()).resolves.toEqual({
      revision,
      source_digest: sourceDigest,
    });
  });
});
