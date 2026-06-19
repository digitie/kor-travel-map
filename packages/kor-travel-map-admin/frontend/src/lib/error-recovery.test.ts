import { describe, expect, it } from "vitest";

import {
  errorRecoveryMessage,
  errorReloadStorageKey,
  isLikelyRecoverableNextRuntimeError,
} from "@/lib/error-recovery";

describe("error recovery helpers", () => {
  it("Next chunk/RSC 계열 런타임 오류를 자동 reload 후보로 분류한다", () => {
    expect(
      isLikelyRecoverableNextRuntimeError(
        new Error("ChunkLoadError: Loading chunk 351 failed"),
      ),
    ).toBe(true);
    expect(
      isLikelyRecoverableNextRuntimeError(new Error("Importing a module script failed.")),
    ).toBe(true);
    expect(
      isLikelyRecoverableNextRuntimeError(new Error("Failed to fetch RSC payload")),
    ).toBe(true);
  });

  it("일반 화면 코드 오류는 자동 reload 후보로 보지 않는다", () => {
    expect(
      isLikelyRecoverableNextRuntimeError(
        new Error("Cannot read properties of undefined"),
      ),
    ).toBe(false);
  });

  it("digest와 pathname을 복구 UI에 필요한 형태로 보존한다", () => {
    const error = Object.assign(new Error("boom"), { digest: "abc123" });
    expect(errorRecoveryMessage(error)).toContain("abc123");
    expect(errorReloadStorageKey("/ops/consistency")).toBe(
      "kortravelmap.admin.error-reload:/ops/consistency",
    );
  });
});
