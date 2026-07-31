// @vitest-environment jsdom

import { webcrypto } from "node:crypto";

import { publishAdminLogout } from "@/lib/admin-auth-events";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearDomainIdempotencyKeys,
  domainCommandSlot,
  withDomainIdempotencySubmission,
} from "./client";

function stubRandomUUID(keys: string[]) {
  const randomUUID = vi.fn(
    () => keys.shift() ?? "ffffffff-ffff-4fff-8fff-ffffffffffff",
  );
  vi.stubGlobal("crypto", {
    randomUUID,
    subtle: globalThis.crypto?.subtle ?? webcrypto.subtle,
  });
  return randomUUID;
}

describe("domain idempotency auth boundary", () => {
  afterEach(() => {
    clearDomainIdempotencyKeys();
    window.sessionStorage.clear();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("logout 후 같은 탭의 다음 admin actor는 이전 uncertain key를 재사용하지 않는다", async () => {
    const randomUUID = stubRandomUUID([
      "10101010-1010-4010-8010-101010101010",
      "20202020-2020-4020-8020-202020202020",
    ]);
    const seen: string[] = [];
    const payload = {
      body: { reason: "response-loss retry" },
      featureId: "feature-1",
    };
    const slot = domainCommandSlot("admin.feature.patch", payload.featureId);

    await expect(
      withDomainIdempotencySubmission(
        slot,
        payload,
        async (_submission, key) => {
          seen.push(key);
          throw new TypeError("response lost");
        },
      ),
    ).rejects.toThrow("response lost");

    publishAdminLogout();

    await withDomainIdempotencySubmission(
      slot,
      payload,
      async (_submission, key) => {
        seen.push(key);
        return "ok";
      },
    );

    expect(seen).toEqual([
      "10101010-1010-4010-8010-101010101010",
      "20202020-2020-4020-8020-202020202020",
    ]);
    expect(randomUUID).toHaveBeenCalledTimes(2);
  });
});
