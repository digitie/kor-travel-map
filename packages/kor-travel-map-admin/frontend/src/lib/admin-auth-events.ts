const ADMIN_LOGOUT_EVENT = "ktm:admin-logout";
const ADMIN_AUTH_CHANNEL = "ktm-admin-auth";
const ADMIN_LOGOUT_PENDING_MS = 15_000;
let adminLogoutStartedAt: number | null = null;

function logoutMonotonicTime(): number | null {
  try {
    const now = performance.now();
    return Number.isFinite(now) ? now : null;
  } catch {
    return null;
  }
}

/** 명시적 로그아웃의 document 이동 권위를 한 탭에서 짧게 고정한다. */
export function beginAdminLogout(): boolean {
  if (typeof window === "undefined" || isAdminLogoutPending()) return false;
  // 시각을 읽지 못해도 실제 로그아웃을 막거나 영구 대기 상태를 만들지 않는다.
  adminLogoutStartedAt = logoutMonotonicTime();
  return true;
}

/** 실패한 로그아웃은 일반 401 로그인 이동을 다시 허용한다. */
export function cancelPendingAdminLogout(): void {
  adminLogoutStartedAt = null;
}

export function isAdminLogoutPending(): boolean {
  if (typeof window === "undefined" || adminLogoutStartedAt === null) return false;
  const now = logoutMonotonicTime();
  if (
    now === null ||
    now < adminLogoutStartedAt ||
    now - adminLogoutStartedAt >= ADMIN_LOGOUT_PENDING_MS
  ) {
    adminLogoutStartedAt = null;
    return false;
  }
  return true;
}

export function publishAdminLogout(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.dispatchEvent(new Event(ADMIN_LOGOUT_EVENT));
  } catch {
    // logout 요청·redirect를 local listener 오류가 막지 않게 한다.
  }
  if ("BroadcastChannel" in window) {
    let channel: BroadcastChannel | null = null;
    try {
      channel = new BroadcastChannel(ADMIN_AUTH_CHANNEL);
      channel.postMessage({ type: "logout" });
    } catch {
      // 다른 탭 알림은 best effort다. 현재 탭 event는 위에서 이미 전달했다.
    } finally {
      try {
        channel?.close();
      } catch {
        // close 실패도 logout 흐름을 막지 않는다.
      }
    }
  }
}

export function subscribeAdminLogout(listener: () => void): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  window.addEventListener(ADMIN_LOGOUT_EVENT, listener);
  let channel: BroadcastChannel | null = null;
  if ("BroadcastChannel" in window) {
    try {
      channel = new BroadcastChannel(ADMIN_AUTH_CHANNEL);
    } catch {
      // 현재 탭 window event 구독은 유지한다.
    }
  }
  const onMessage = (event: MessageEvent<unknown>) => {
    if (
      event.data &&
      typeof event.data === "object" &&
      "type" in event.data &&
      event.data.type === "logout"
    ) {
      listener();
    }
  };
  try {
    channel?.addEventListener("message", onMessage);
  } catch {
    try {
      channel?.close();
    } catch {
      // best effort cleanup
    }
    channel = null;
  }
  return () => {
    window.removeEventListener(ADMIN_LOGOUT_EVENT, listener);
    try {
      channel?.removeEventListener("message", onMessage);
      channel?.close();
    } catch {
      // effect cleanup은 idempotent best effort다.
    }
  };
}
