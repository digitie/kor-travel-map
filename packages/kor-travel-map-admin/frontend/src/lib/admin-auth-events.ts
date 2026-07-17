const ADMIN_LOGOUT_EVENT = "ktm:admin-logout";
const ADMIN_AUTH_CHANNEL = "ktm-admin-auth";

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
