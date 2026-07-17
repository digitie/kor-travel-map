// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import { publishAdminLogout, subscribeAdminLogout } from "./admin-auth-events";

describe("admin auth browser events", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("logout을 현재 탭의 live subscriber에 즉시 알리고 해제 뒤에는 호출하지 않는다", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeAdminLogout(listener);

    publishAdminLogout();
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    publishAdminLogout();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("BroadcastChannel 생성이 실패해도 현재 탭 event를 유지한다", () => {
    vi.stubGlobal(
      "BroadcastChannel",
      class {
        constructor() {
          throw new Error("channel unavailable");
        }
      },
    );
    const listener = vi.fn();
    const unsubscribe = subscribeAdminLogout(listener);

    expect(() => publishAdminLogout()).not.toThrow();
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
  });

  it("BroadcastChannel postMessage 실패가 logout 전파를 막지 않는다", () => {
    const close = vi.fn();
    vi.stubGlobal(
      "BroadcastChannel",
      class {
        close = close;

        postMessage(): void {
          throw new Error("post failed");
        }
      },
    );
    const listener = vi.fn();
    const unsubscribe = subscribeAdminLogout(listener);

    expect(() => publishAdminLogout()).not.toThrow();
    expect(listener).toHaveBeenCalledTimes(1);
    expect(close).toHaveBeenCalled();

    unsubscribe();
  });

  it("BroadcastChannel listener 등록이 실패해도 local subscriber를 유지한다", () => {
    const close = vi.fn();
    vi.stubGlobal(
      "BroadcastChannel",
      class {
        close = close;

        addEventListener(): void {
          throw new Error("listener failed");
        }
      },
    );
    const listener = vi.fn();
    const unsubscribe = subscribeAdminLogout(listener);

    publishAdminLogout();
    expect(listener).toHaveBeenCalledTimes(1);
    expect(close).toHaveBeenCalled();

    unsubscribe();
  });
});
