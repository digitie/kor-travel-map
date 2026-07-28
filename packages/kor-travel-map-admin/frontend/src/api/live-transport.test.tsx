// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { publishAdminLogout } from "@/lib/admin-auth-events";

import {
  useOpsLiveInvalidation,
  type OpsLiveInvalidationAdapter,
  type OpsLiveTopic,
} from "./live";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readonly close = vi.fn();
  readonly send = vi.fn();
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: ((event: Event) => void) | null = null;

  constructor(
    readonly url: string,
    readonly protocol: string,
  ) {
    FakeWebSocket.instances.push(this);
  }

  serverClose(code: number): void {
    this.onclose?.({ code } as CloseEvent);
  }

  serverMessage(message: object): void {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
  }
}

function ticketResponse(): Response {
  return new Response(
    JSON.stringify({
      expires_at: "2026-07-17T12:01:00.000Z",
      subprotocol: "ktm.ops-live.v1.payload.signature",
    }),
    {
      status: 200,
      headers: { "Content-Type": "application/json" },
    },
  );
}

function serverFrame(sequence: number, message: object): object {
  return {
    version: 1,
    sequence,
    sent_at: "2026-07-17T12:00:00.000Z",
    ...message,
  };
}

function snapshotFrame(sequence: number, topic: OpsLiveTopic): object {
  return serverFrame(sequence, {
    type: "snapshot",
    topic,
    revision: `${topic}:${sequence}`,
    data: {},
  });
}

function Harness({
  adapter,
  topics,
}: {
  adapter?: OpsLiveInvalidationAdapter;
  topics: readonly OpsLiveTopic[];
}) {
  const live = useOpsLiveInvalidation({
    topics,
    invalidationAdapter: adapter,
  });
  return (
    <>
      <output data-testid="state">{live.state}</output>
      <output data-testid="mode">{live.mode}</output>
      <output data-testid="error">{live.lastError}</output>
    </>
  );
}

function renderHarness({
  adapter,
  topics = ["import_jobs"],
}: {
  adapter?: OpsLiveInvalidationAdapter;
  topics?: readonly OpsLiveTopic[];
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <Harness adapter={adapter} topics={topics} />
    </QueryClientProvider>,
  );
  return {
    ...view,
    queryClient,
    rerenderTopics: (nextTopics: readonly OpsLiveTopic[]) =>
      view.rerender(
        <QueryClientProvider client={queryClient}>
          <Harness adapter={adapter} topics={nextTopics} />
        </QueryClientProvider>,
      ),
  };
}

async function flushMicrotasks(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("ops live transport", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-17T12:00:00.000Z"));
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("ticket BFF 401이면 unauthorized에서 멈추고 재시도하지 않는다", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    renderHarness();
    await flushMicrotasks();

    expect(screen.getByTestId("state").textContent).toBe("unauthorized");
    expect(screen.getByTestId("mode").textContent).toBe("disabled");
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("WebSocket 4401이면 unauthorized에서 멈추고 재시도하지 않는다", async () => {
    const fetchMock = vi.fn(async () => ticketResponse());
    vi.stubGlobal("fetch", fetchMock);

    renderHarness();
    await flushMicrotasks();
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => FakeWebSocket.instances[0].serverClose(4401));

    expect(screen.getByTestId("state").textContent).toBe("unauthorized");
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("안정 frame 전 4408은 연속 실패 backoff에 포함한다", async () => {
    const fetchMock = vi.fn(async () => ticketResponse());
    vi.stubGlobal("fetch", fetchMock);

    renderHarness();
    await flushMicrotasks();
    act(() => FakeWebSocket.instances[0].serverClose(4408));
    expect(screen.getByTestId("state").textContent).toBe("reconnecting");
    await act(async () => vi.advanceTimersByTimeAsync(999));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    await flushMicrotasks();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("안정 snapshot 후 4408은 정상 lease rotation으로 즉시 재연결한다", async () => {
    const fetchMock = vi.fn(async () => ticketResponse());
    vi.stubGlobal("fetch", fetchMock);

    renderHarness();
    await flushMicrotasks();
    act(() =>
      FakeWebSocket.instances[0].serverMessage(
        serverFrame(1, {
          type: "subscribed",
          topics: ["import_jobs"],
        }),
      ),
    );
    act(() =>
      FakeWebSocket.instances[0].serverMessage(
        snapshotFrame(2, "import_jobs"),
      ),
    );
    expect(screen.getByTestId("state").textContent).toBe("live");

    act(() => FakeWebSocket.instances[0].serverClose(4408));
    await act(async () => vi.advanceTimersByTimeAsync(0));
    await flushMicrotasks();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("hello만 받아도 실패 횟수를 초기화하지 않고 3회에 polling이 된다", async () => {
    const fetchMock = vi.fn(async () => ticketResponse());
    vi.stubGlobal("fetch", fetchMock);

    renderHarness();
    await flushMicrotasks();
    act(() =>
      FakeWebSocket.instances[0].serverMessage(
        serverFrame(1, { type: "hello" }),
      ),
    );
    act(() => FakeWebSocket.instances[0].serverClose(1013));
    expect(screen.getByTestId("state").textContent).toBe("reconnecting");

    await act(async () => vi.advanceTimersByTimeAsync(999));
    expect(FakeWebSocket.instances).toHaveLength(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    await flushMicrotasks();
    expect(FakeWebSocket.instances).toHaveLength(2);

    act(() =>
      FakeWebSocket.instances[1].serverMessage(
        serverFrame(1, { type: "hello" }),
      ),
    );
    act(() => FakeWebSocket.instances[1].serverClose(1013));
    await act(async () => vi.advanceTimersByTimeAsync(2_000));
    await flushMicrotasks();
    expect(FakeWebSocket.instances).toHaveLength(3);

    act(() =>
      FakeWebSocket.instances[2].serverMessage(
        serverFrame(1, { type: "hello" }),
      ),
    );
    act(() => FakeWebSocket.instances[2].serverClose(1013));
    expect(screen.getByTestId("state").textContent).toBe("polling");
    expect(screen.getByTestId("mode").textContent).toBe("polling");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("hello 뒤 comma 포함 opaque topic도 replace JSON 배열로 보낸다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ticketResponse()));
    renderHarness({ topics: ["dagster_run:run,with,comma"] });
    await flushMicrotasks();

    // subscribe(replace)는 open이 아니라 서버 hello 수신 후에 보낸다.
    act(() =>
      FakeWebSocket.instances[0].serverMessage(
        serverFrame(1, { type: "hello" }),
      ),
    );

    expect(FakeWebSocket.instances[0].send).toHaveBeenCalledWith(
      JSON.stringify({
        type: "replace",
        topics: ["dagster_run:run,with,comma"],
      }),
    );
  });

  it("다른 tab/process의 dataset projection snapshot을 대상 query에 반영한다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ticketResponse()));
    const invalidateProviderDataset = vi.fn((queryClient: QueryClient) => {
      void queryClient.invalidateQueries({ queryKey: ["adapter-target"] });
    });
    const view = renderHarness({
      adapter: { invalidateProviderDataset },
      topics: ["dataset_projection"],
    });
    view.queryClient.setQueryData(["adapter-target"], { ok: true });
    await flushMicrotasks();

    act(() =>
      FakeWebSocket.instances[0].serverMessage(
        serverFrame(1, {
          type: "subscribed",
          topics: ["dataset_projection"],
        }),
      ),
    );
    act(() =>
      FakeWebSocket.instances[0].serverMessage(
        snapshotFrame(2, "dataset_projection"),
      ),
    );

    expect(invalidateProviderDataset).toHaveBeenCalledTimes(1);
    expect(
      view.queryClient.getQueryState(["adapter-target"])?.isInvalidated,
    ).toBe(true);
    expect(screen.getByTestId("state").textContent).toBe("live");
    expect(screen.getByTestId("mode").textContent).toBe("live");
  });

  it("ticket 요청이 응답 없이 멈추면 abort하고 backoff 재시도한다", async () => {
    const fetchMock = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderHarness();
    await flushMicrotasks();
    await act(async () => vi.advanceTimersByTimeAsync(10_000));

    expect(screen.getByTestId("state").textContent).toBe("reconnecting");
    expect(screen.getByTestId("mode").textContent).toBe("standby");
    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("WebSocket handshake가 열리지 않으면 socket을 분리하고 직접 재연결한다", async () => {
    const fetchMock = vi.fn(async () => ticketResponse());
    vi.stubGlobal("fetch", fetchMock);

    renderHarness();
    await flushMicrotasks();
    const stalled = FakeWebSocket.instances[0];
    await act(async () => vi.advanceTimersByTimeAsync(15_000));

    expect(stalled.close).toHaveBeenCalledWith(
      4000,
      "ops live handshake가 제한 시간 안에 완료되지 않았습니다.",
    );
    expect(screen.getByTestId("state").textContent).toBe("reconnecting");
    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    await flushMicrotasks();
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("정상 연결 뒤 heartbeat가 끊기면 standby로 전환하고 재연결한다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ticketResponse()));
    renderHarness();
    await flushMicrotasks();
    const stalled = FakeWebSocket.instances[0];
    act(() => {
      stalled.serverMessage(
        serverFrame(1, { type: "subscribed", topics: ["import_jobs"] }),
      );
      stalled.serverMessage(snapshotFrame(2, "import_jobs"));
    });
    expect(screen.getByTestId("state").textContent).toBe("live");

    await act(async () => vi.advanceTimersByTimeAsync(40_000));

    expect(stalled.close).toHaveBeenCalledWith(
      4000,
      "ops live heartbeat가 중단되었습니다.",
    );
    expect(screen.getByTestId("state").textContent).toBe("reconnecting");
    expect(screen.getByTestId("mode").textContent).toBe("standby");
    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    await flushMicrotasks();
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("긴 server error도 짧은 close reason으로 오염 socket을 폐기한다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ticketResponse()));
    renderHarness();
    await flushMicrotasks();
    const socket = FakeWebSocket.instances[0];

    act(() =>
      socket.serverMessage(
        serverFrame(1, {
          type: "error",
          message: "x".repeat(200),
        }),
      ),
    );

    expect(socket.close).toHaveBeenCalledWith(
      4000,
      "ops live protocol violation",
    );
    expect(screen.getByTestId("state").textContent).toBe("reconnecting");
    expect(screen.getByTestId("mode").textContent).toBe("standby");
    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    await flushMicrotasks();
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("불완전 snapshot은 live 전이와 pre-healthy watchdog 갱신을 하지 않는다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ticketResponse()));
    renderHarness();
    await flushMicrotasks();
    const socket = FakeWebSocket.instances[0];
    act(() =>
      socket.serverMessage(
        serverFrame(1, { type: "subscribed", topics: ["import_jobs"] }),
      ),
    );
    await act(async () => vi.advanceTimersByTimeAsync(10_000));

    act(() =>
      socket.serverMessage(
        serverFrame(2, {
          type: "snapshot",
          topic: "import_jobs",
          data: {},
        }),
      ),
    );

    expect(screen.getByTestId("state").textContent).toBe("reconnecting");
    expect(screen.getByTestId("mode").textContent).toBe("standby");
    expect(screen.getByTestId("error").textContent).toContain(
      "data frame 형식",
    );
    expect(socket.close).toHaveBeenCalledWith(
      4000,
      "ops live protocol violation",
    );
    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    await flushMicrotasks();
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("protocol 위반 뒤 새 socket에서 exact replace와 snapshot으로 복구한다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ticketResponse()));
    renderHarness();
    await flushMicrotasks();
    const failedSocket = FakeWebSocket.instances[0];

    act(() => {
      // hello 수신 후 client가 replace를 보낸다(seq: hello=1, subscribed=2, snapshot=3).
      failedSocket.serverMessage(serverFrame(1, { type: "hello" }));
      failedSocket.serverMessage(
        serverFrame(2, { type: "subscribed", topics: ["import_jobs"] }),
      );
      failedSocket.serverMessage(snapshotFrame(3, "import_jobs"));
      // 비증가 sequence(=snapshot과 동일한 3)로 protocol 위반을 유발한다.
      failedSocket.serverMessage(
        serverFrame(3, { type: "heartbeat", topics: ["import_jobs"] }),
      );
    });

    expect(failedSocket.send).toHaveBeenCalledTimes(1);
    expect(failedSocket.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "replace", topics: ["import_jobs"] }),
    );
    expect(failedSocket.close).toHaveBeenCalledWith(
      4000,
      "ops live protocol violation",
    );
    expect(screen.getByTestId("state").textContent).toBe("reconnecting");
    expect(screen.getByTestId("mode").textContent).toBe("standby");

    await act(async () => vi.advanceTimersByTimeAsync(1_000));
    await flushMicrotasks();
    const replacementSocket = FakeWebSocket.instances[1];
    act(() =>
      replacementSocket.serverMessage(serverFrame(1, { type: "hello" })),
    );
    expect(replacementSocket.send).toHaveBeenCalledTimes(1);
    expect(replacementSocket.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "replace", topics: ["import_jobs"] }),
    );

    act(() => {
      replacementSocket.serverMessage(
        serverFrame(2, { type: "subscribed", topics: ["import_jobs"] }),
      );
      replacementSocket.serverMessage(snapshotFrame(3, "import_jobs"));
    });
    expect(screen.getByTestId("state").textContent).toBe("live");
    expect(screen.getByTestId("mode").textContent).toBe("live");
  });

  it("topic prop이 바뀌면 기존 socket을 닫고 새 canonical 배열로 연결한다", async () => {
    const fetchMock = vi.fn(async () => ticketResponse());
    vi.stubGlobal("fetch", fetchMock);
    const view = renderHarness({ topics: ["import_jobs"] });
    await flushMicrotasks();
    const first = FakeWebSocket.instances[0];

    view.rerenderTopics(["dagster_run:run,2", "provider_sync"]);
    await flushMicrotasks();
    const second = FakeWebSocket.instances[1];
    act(() => second.serverMessage(serverFrame(1, { type: "hello" })));

    expect(first.close).toHaveBeenCalledWith(1000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(second.send).toHaveBeenCalledWith(
      JSON.stringify({
        type: "replace",
        topics: ["dagster_run:run,2", "provider_sync"],
      }),
    );
  });

  it("logout local event가 활성 socket과 재연결을 즉시 종료한다", async () => {
    const fetchMock = vi.fn(async () => ticketResponse());
    vi.stubGlobal("fetch", fetchMock);
    renderHarness();
    await flushMicrotasks();
    const socket = FakeWebSocket.instances[0];

    act(() => publishAdminLogout());

    expect(socket.close).toHaveBeenCalledWith(1000, "admin logout");
    expect(screen.getByTestId("state").textContent).toBe("unauthorized");
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("ticket 요청 중 logout하면 응답 후 socket을 만들지 않는다", async () => {
    let resolveTicket: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveTicket = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderHarness();
    await flushMicrotasks();

    act(() => publishAdminLogout());
    resolveTicket?.(ticketResponse());
    await flushMicrotasks();

    expect(screen.getByTestId("state").textContent).toBe("unauthorized");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("unmount하면 활성 socket을 닫는다", async () => {
    const fetchMock = vi.fn(async () => ticketResponse());
    vi.stubGlobal("fetch", fetchMock);

    const view = renderHarness();
    await flushMicrotasks();
    const socket = FakeWebSocket.instances[0];

    view.unmount();

    expect(socket.close).toHaveBeenCalledWith(1000);
  });

  it("unmount하면 진행 중인 ticket 요청을 abort한다", async () => {
    const ticketRequest: { signal: AbortSignal | null } = { signal: null };
    const fetchMock = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          ticketRequest.signal = init?.signal ?? null;
          ticketRequest.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const view = renderHarness();
    await flushMicrotasks();
    expect(ticketRequest.signal?.aborted).toBe(false);

    view.unmount();

    expect(ticketRequest.signal?.aborted).toBe(true);
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("unmount하면 예약된 backoff timer를 정리한다", async () => {
    const fetchMock = vi.fn(async () => ticketResponse());
    vi.stubGlobal("fetch", fetchMock);

    const view = renderHarness();
    await flushMicrotasks();
    const socket = FakeWebSocket.instances[0];
    act(() => socket.serverClose(1013));
    expect(screen.getByTestId("state").textContent).toBe("reconnecting");

    view.unmount();
    await act(async () => vi.advanceTimersByTimeAsync(60_000));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
