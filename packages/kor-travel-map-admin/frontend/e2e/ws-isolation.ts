import type { Page } from "@playwright/test";

/**
 * mocked e2e용 ops-live WebSocket 격리 헬퍼 (#503).
 *
 * 문제: mocked depth spec은 REST만 가로채고(`page.route`), `useOpsLiveInvalidation`
 * (`src/api/live.ts`)이 여는 ops-live WS(`ws(s)://<BASE_URL host>/v1/ops/live`)는
 * 그대로 라이브 백엔드(:12701)로 나간다. 라이브 백엔드가 떠 있으면 snapshot/update
 * 메시지가 들어와 `invalidateLiveTopic`이 추가 mock GET 버스트를 유발 → "정확히 N회"
 * 같은 타이밍 민감 단언을 flaky하게 만든다. 라이브 백엔드가 없으면 connect 실패 →
 * 재연결 타이머 소음.
 *
 * `page.routeWebSocket`은 WS가 12705(페이지 origin)가 아닌 12701(BASE_URL)로 나가
 * cross-origin glob이 필요하고 Windows 호스트 런에서만 실증 가능했다(기존 spec NOTE).
 * 대신 **origin-agnostic**하게, page document보다 먼저 도는 `addInitScript`로
 * `window.WebSocket`을 no-op 스텁으로 갈아끼운다 — 실제 소켓을 절대 열지 않고
 * snapshot/update를 절대 emit하지 않으므로 라이브 invalidation 경로가 완전히 inert다.
 *
 * 스텁은 `WebSocket` 인터페이스(상수·이벤트 핸들러·EventTarget 메서드·close)를
 * 형태만 맞춰 흉내내 `useOpsLiveInvalidation`의 `new WebSocket(...)` / `socket.close(1000)`
 * 호출이 throw하지 않게 한다. open/message를 절대 발사하지 않으므로 hook은
 * "connecting"에 머문다(테스트는 WS 배지 상태를 단언하지 않는다).
 *
 * 사용: live-invalidation 화면을 mount하는 **모든** mocked spec의 `test.beforeEach`에서
 * `await installInertOpsLiveWebSocket(page)`를 `page.goto` 전에 호출한다.
 */
export async function installInertOpsLiveWebSocket(page: Page): Promise<void> {
  await page.addInitScript(() => {
    // 이미 스텁이 깔렸으면(재진입) 재정의하지 않는다.
    if ((window as unknown as { __opsLiveWsStubbed?: boolean }).__opsLiveWsStubbed) {
      return;
    }
    (window as unknown as { __opsLiveWsStubbed?: boolean }).__opsLiveWsStubbed = true;

    const NativeWebSocket = window.WebSocket;

    class InertWebSocket extends EventTarget implements WebSocket {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSING = 2;
      static readonly CLOSED = 3;

      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSING = 2;
      readonly CLOSED = 3;

      readonly url: string;
      // 절대 open되지 않는다 — 영원히 CONNECTING에 머물러 snapshot/update를 emit하지 않음.
      readyState = 0;
      bufferedAmount = 0;
      extensions = "";
      protocol = "";
      binaryType: BinaryType = "blob";

      onopen: ((this: WebSocket, ev: Event) => unknown) | null = null;
      onmessage: ((this: WebSocket, ev: MessageEvent) => unknown) | null = null;
      onerror: ((this: WebSocket, ev: Event) => unknown) | null = null;
      onclose: ((this: WebSocket, ev: CloseEvent) => unknown) | null = null;

      constructor(url: string | URL, _protocols?: string | string[]) {
        super();
        this.url = String(url);
        // 실 소켓을 열지 않는다. open/message 이벤트를 절대 발사하지 않으므로
        // ops-live invalidation은 트리거되지 않는다.
      }

      send(): void {
        // no-op — inert 스텁은 아무것도 보내지 않는다.
      }

      close(): void {
        this.readyState = 3;
        // onclose를 동기 발사하지 않는다 — hook의 close 핸들러가 재연결을
        // 스케줄(setState("reconnecting"))하지 않게 해 cleanup을 조용하게 둔다.
      }
    }

    // 원래 생성자 참조를 보존해 다른 코드가 필요 시 접근할 수 있게 둔다(미사용 대비).
    (
      window as unknown as { __nativeWebSocket?: typeof WebSocket }
    ).__nativeWebSocket = NativeWebSocket;
    window.WebSocket = InertWebSocket as unknown as typeof WebSocket;
  });
}
