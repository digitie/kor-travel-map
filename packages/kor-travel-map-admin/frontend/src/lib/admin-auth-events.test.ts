// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  beginAdminLogout,
  cancelPendingAdminLogout,
  isAdminLogoutPending,
  publishAdminLogout,
  subscribeAdminLogout,
} from "./admin-auth-events";

describe("admin auth browser events", () => {
  afterEach(() => {
    cancelPendingAdminLogout();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("명시적 로그아웃은 한 탭에서 한 번만 시작하고 이동 전까지 유지한다", () => {
    expect(isAdminLogoutPending()).toBe(false);
    expect(beginAdminLogout()).toBe(true);
    expect(isAdminLogoutPending()).toBe(true);
    expect(beginAdminLogout()).toBe(false);
    publishAdminLogout();
    expect(isAdminLogoutPending()).toBe(true);
  });

  it("이동이 비동기로 중단돼도 15초 경계에서 로그아웃을 다시 시작할 수 있다", () => {
    const now = vi.spyOn(performance, "now").mockReturnValue(100);
    expect(beginAdminLogout()).toBe(true);
    publishAdminLogout();
    now.mockReturnValue(15_099);
    expect(isAdminLogoutPending()).toBe(true);
    expect(beginAdminLogout()).toBe(false);
    now.mockReturnValue(15_100);
    expect(isAdminLogoutPending()).toBe(false);
    expect(beginAdminLogout()).toBe(true);
  });

  it("단조 시각이 비정상이면 이전 대기 상태를 영구 유지하지 않는다", () => {
    const now = vi.spyOn(performance, "now").mockReturnValue(100);
    expect(beginAdminLogout()).toBe(true);
    now.mockReturnValue(99);
    expect(isAdminLogoutPending()).toBe(false);
    now.mockReturnValue(Number.NaN);
    expect(beginAdminLogout()).toBe(true);
    expect(isAdminLogoutPending()).toBe(false);
    now.mockReturnValue(200);
    expect(beginAdminLogout()).toBe(true);
    now.mockReturnValue(Number.POSITIVE_INFINITY);
    expect(isAdminLogoutPending()).toBe(false);
  });

  it("단조 시각 조회가 실패해도 로그아웃 시작과 일반 401 경계를 막지 않는다", () => {
    const now = vi.spyOn(performance, "now").mockReturnValue(100);
    expect(beginAdminLogout()).toBe(true);
    now.mockImplementation(() => { throw new Error("clock unavailable"); });
    expect(isAdminLogoutPending()).toBe(false);
    expect(beginAdminLogout()).toBe(true);
    expect(isAdminLogoutPending()).toBe(false);
  });

  it("실패 뒤 해제하면 다음 로그아웃과 일반 401 경계를 다시 사용할 수 있다", () => {
    expect(beginAdminLogout()).toBe(true);
    cancelPendingAdminLogout();
    expect(isAdminLogoutPending()).toBe(false);
    expect(beginAdminLogout()).toBe(true);
  });

  it("서버에서는 탭의 로그아웃 상태를 시작하지 않는다", () => {
    vi.stubGlobal("window", undefined);
    expect(beginAdminLogout()).toBe(false);
    expect(isAdminLogoutPending()).toBe(false);
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
