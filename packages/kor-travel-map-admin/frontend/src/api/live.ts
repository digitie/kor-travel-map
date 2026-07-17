"use client";

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { subscribeAdminLogout } from "@/lib/admin-auth-events";
import {
  OPS_LIVE_EXPIRED_CLOSE_CODE,
  OPS_LIVE_PROTOCOL_PREFIX,
  OPS_LIVE_UNAUTHORIZED_CLOSE_CODE,
} from "@/lib/ops-live-contract";

import { invalidateOpsDatasetQueries } from "./datasets";
import { publicUrlEnv } from "./env";

export type OpsLiveConnectionState =
  | "disabled"
  | "connecting"
  | "live"
  | "reconnecting"
  | "polling"
  | "unauthorized"
  | "unavailable";

export type OpsLiveMode = "disabled" | "live" | "polling";

const OPS_LIVE_STATE_LABELS: Record<OpsLiveConnectionState, string> = {
  disabled: "자동 갱신 꺼짐",
  connecting: "연결 중",
  live: "실시간",
  reconnecting: "재연결 중",
  polling: "REST 폴링",
  unauthorized: "로그인 필요",
  unavailable: "WebSocket 미지원",
};

export function opsLiveConnectionLabel(state: OpsLiveConnectionState): string {
  return OPS_LIVE_STATE_LABELS[state];
}

export type OpsLiveTopic =
  | "import_jobs"
  | "feature_update_requests"
  | "offline_uploads"
  | "dagster_runs"
  | "provider_sync"
  | "dataset_projection"
  | "dagster_schedules"
  | `import_job:${string}`
  | `import_job_events:${string}`
  | `feature_update_request:${string}`
  | `offline_upload:${string}`
  | `dagster_run:${string}`;

export type OpsLiveDomainEventKind =
  | "operation"
  | "provider_dataset"
  | "dagster_run"
  | "schedule";

export type OpsLiveDomainEvent = {
  kind: OpsLiveDomainEventKind;
  topic: string;
};

export type OpsLiveInvalidationAdapter = {
  invalidateDagsterRun?: (
    queryClient: QueryClient,
    event: OpsLiveDomainEvent,
  ) => void;
  invalidateOperation?: (
    queryClient: QueryClient,
    event: OpsLiveDomainEvent,
  ) => void;
  invalidateProviderDataset?: (
    queryClient: QueryClient,
    event: OpsLiveDomainEvent,
  ) => void;
  invalidateSchedule?: (
    queryClient: QueryClient,
    event: OpsLiveDomainEvent,
  ) => void;
};

type OpsLiveMessage = {
  type?: unknown;
  version?: unknown;
  sequence?: unknown;
  sent_at?: unknown;
  topic?: unknown;
  topics?: unknown;
  revision?: unknown;
  data?: unknown;
  message?: unknown;
};

type OpsLiveTicket = {
  expires_at: string;
  subprotocol: string;
};

const reconnectDelaysMs = [1_000, 2_000, 5_000, 10_000, 30_000] as const;
const POLLING_FALLBACK_FAILURE_COUNT = 3;
const TICKET_FETCH_TIMEOUT_MS = 10_000;
const PRE_HEALTHY_TIMEOUT_MS = 15_000;
const LIVE_INACTIVITY_TIMEOUT_MS = 40_000;
const CLIENT_STALE_CLOSE_CODE = 4000;
const LIVE_BASE_URL = publicUrlEnv(
  process.env.NEXT_PUBLIC_KOR_TRAVEL_MAP_API,
  "NEXT_PUBLIC_KOR_TRAVEL_MAP_API",
  "http://127.0.0.1:12701",
);

/**
 * ops-live WebSocket 전역 kill-switch (#503).
 *
 * mocked e2e는 `e2e/ws-isolation.ts`를 1차 방어선으로 쓰고 이 값은 빌드 타임
 * 보조 수단으로만 쓴다. production 기본은 enabled다.
 */
const OPS_LIVE_DISABLED = process.env.NEXT_PUBLIC_DISABLE_OPS_LIVE === "1";

class OpsLiveTicketRequestError extends Error {
  constructor(
    message: string,
    readonly unauthorized: boolean,
  ) {
    super(message);
    this.name = "OpsLiveTicketRequestError";
  }
}

function buildOpsLiveUrl(pollIntervalMs = 2_000): string {
  const url = new URL(LIVE_BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const basePath = url.pathname.replace(/\/+$/, "");
  url.pathname = `${basePath}/v1/ops/live`;
  url.search = "";
  url.searchParams.set("poll_interval_ms", String(pollIntervalMs));
  return url.toString();
}

async function fetchOpsLiveTicket(signal: AbortSignal): Promise<OpsLiveTicket> {
  const response = await fetch("/api/auth/live-ticket", {
    method: "POST",
    headers: { Accept: "application/json" },
    cache: "no-store",
    credentials: "same-origin",
    signal,
  });
  if (response.status === 401) {
    throw new OpsLiveTicketRequestError(
      "ops live 로그인이 필요합니다.",
      true,
    );
  }
  if (response.status === 403) {
    throw new OpsLiveTicketRequestError(
      "ops live ticket 요청 origin이 거부되었습니다.",
      false,
    );
  }
  if (!response.ok) {
    throw new OpsLiveTicketRequestError(
      `ops live ticket 발급 실패 (${response.status})`,
      false,
    );
  }
  const value = (await response.json()) as Partial<OpsLiveTicket>;
  if (
    typeof value.subprotocol !== "string" ||
    !value.subprotocol.startsWith(OPS_LIVE_PROTOCOL_PREFIX) ||
    typeof value.expires_at !== "string" ||
    Number.isNaN(Date.parse(value.expires_at))
  ) {
    throw new OpsLiveTicketRequestError(
      "ops live ticket 응답 형식이 올바르지 않습니다.",
      false,
    );
  }
  return value as OpsLiveTicket;
}

function reconnectDelayMs(attempt: number): number {
  return reconnectDelaysMs[Math.min(attempt, reconnectDelaysMs.length - 1)];
}

function connectionStateForFailureCount(
  failureCount: number,
): OpsLiveConnectionState {
  return failureCount >= POLLING_FALLBACK_FAILURE_COUNT
    ? "polling"
    : "reconnecting";
}

function canonicalTopicDependency(topics: readonly OpsLiveTopic[]): string {
  return JSON.stringify(Array.from(new Set(topics)).sort());
}

function topicsFromDependency(dependency: string): OpsLiveTopic[] {
  return JSON.parse(dependency) as OpsLiveTopic[];
}

function messageTopicsMatch(
  topics: unknown,
  requestedTopics: readonly string[],
): topics is string[] {
  if (
    !Array.isArray(topics) ||
    topics.length !== requestedTopics.length ||
    topics.some((topic) => typeof topic !== "string")
  ) {
    return false;
  }
  const receivedTopics = new Set(topics as string[]);
  return (
    receivedTopics.size === topics.length &&
    requestedTopics.every((topic) => receivedTopics.has(topic))
  );
}

function serverFrameSequence(
  message: OpsLiveMessage,
  previousSequence: number,
): number | null {
  if (
    message.version !== 1 ||
    typeof message.sequence !== "number" ||
    !Number.isSafeInteger(message.sequence) ||
    message.sequence <= previousSequence ||
    typeof message.sent_at !== "string" ||
    Number.isNaN(Date.parse(message.sent_at))
  ) {
    return null;
  }
  return message.sequence;
}

function isLiveDataFrame(
  message: OpsLiveMessage,
  requestedTopics: readonly string[],
): message is OpsLiveMessage & {
  topic: string;
  revision: string;
  data: Record<string, unknown>;
} {
  return (
    typeof message.topic === "string" &&
    requestedTopics.includes(message.topic) &&
    typeof message.revision === "string" &&
    message.revision.trim().length > 0 &&
    typeof message.data === "object" &&
    message.data !== null &&
    !Array.isArray(message.data)
  );
}

function topicId(topic: string, prefix: string) {
  return topic.slice(prefix.length);
}

function invalidateFeatureSurfaces(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: ["features"] });
  void queryClient.invalidateQueries({ queryKey: ["feature"] });
  void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
}

function invalidatePipelineLivePage(
  queryClient: QueryClient,
  surface: "executions" | "events",
) {
  void queryClient.invalidateQueries({
    predicate: (query) => {
      const key = query.queryKey;
      return (
        key[0] === "pipeline" && key[1] === surface && key[2] === "live"
      );
    },
  });
}

function invalidatePipelineExecutionDetails(queryClient: QueryClient) {
  void queryClient.invalidateQueries({
    queryKey: ["pipeline", "execution"],
  });
}

function invalidatePipelineSurfaces(queryClient: QueryClient) {
  invalidatePipelineLivePage(queryClient, "executions");
  void queryClient.invalidateQueries({ queryKey: ["pipeline", "overview"] });
  invalidatePipelineLivePage(queryClient, "events");
}

function domainEventsForTopic(topic: string): OpsLiveDomainEvent[] {
  const events: OpsLiveDomainEvent[] = [];
  if (
    topic === "import_jobs" ||
    topic.startsWith("import_job:") ||
    topic.startsWith("import_job_events:") ||
    topic === "feature_update_requests" ||
    topic.startsWith("feature_update_request:") ||
    topic === "offline_uploads" ||
    topic.startsWith("offline_upload:")
  ) {
    events.push({ kind: "operation", topic });
  }
  if (
    topic === "provider_sync" ||
    topic === "dataset_projection" ||
    topic === "feature_update_requests" ||
    topic.startsWith("feature_update_request:")
  ) {
    events.push({ kind: "provider_dataset", topic });
  }
  if (topic === "dagster_runs" || topic.startsWith("dagster_run:")) {
    events.push({ kind: "dagster_run", topic });
    events.push({ kind: "operation", topic });
  }
  if (topic === "dagster_schedules") {
    events.push({ kind: "schedule", topic });
  }
  return events;
}

function routeDomainInvalidation(
  queryClient: QueryClient,
  topic: string,
  adapter: OpsLiveInvalidationAdapter | undefined,
) {
  if (!adapter) {
    return;
  }
  for (const event of domainEventsForTopic(topic)) {
    if (event.kind === "operation") {
      adapter.invalidateOperation?.(queryClient, event);
    } else if (event.kind === "provider_dataset") {
      adapter.invalidateProviderDataset?.(queryClient, event);
    } else if (event.kind === "dagster_run") {
      adapter.invalidateDagsterRun?.(queryClient, event);
    } else {
      adapter.invalidateSchedule?.(queryClient, event);
    }
  }
}

function invalidateLiveTopic(
  queryClient: QueryClient,
  topic: string,
  adapter?: OpsLiveInvalidationAdapter,
) {
  routeDomainInvalidation(queryClient, topic, adapter);
  if (topic === "import_jobs") {
    invalidatePipelineExecutionDetails(queryClient);
    invalidatePipelineSurfaces(queryClient);
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
  if (topic.startsWith("import_job_events:")) {
    const jobId = topicId(topic, "import_job_events:");
    void queryClient.invalidateQueries({
      queryKey: ["pipeline", "execution", "import_job", jobId],
    });
    invalidatePipelineLivePage(queryClient, "events");
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
  if (topic.startsWith("import_job:")) {
    const jobId = topicId(topic, "import_job:");
    void queryClient.invalidateQueries({
      queryKey: ["pipeline", "execution", "import_job", jobId],
    });
    invalidatePipelineSurfaces(queryClient);
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
  if (topic === "feature_update_requests") {
    invalidateFeatureSurfaces(queryClient);
    invalidatePipelineExecutionDetails(queryClient);
    invalidatePipelineSurfaces(queryClient);
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
  if (topic.startsWith("feature_update_request:")) {
    const requestId = topicId(topic, "feature_update_request:");
    void queryClient.invalidateQueries({
      queryKey: ["pipeline", "execution", "update_request", requestId],
    });
    invalidateFeatureSurfaces(queryClient);
    invalidatePipelineSurfaces(queryClient);
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
  if (topic === "offline_uploads") {
    void queryClient.invalidateQueries({ queryKey: ["offline-uploads"] });
    invalidatePipelineSurfaces(queryClient);
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
  if (topic.startsWith("offline_upload:")) {
    void queryClient.invalidateQueries({
      queryKey: ["offline-upload", topicId(topic, "offline_upload:")],
    });
    void queryClient.invalidateQueries({ queryKey: ["offline-uploads"] });
    invalidatePipelineSurfaces(queryClient);
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
  if (topic === "provider_sync" || topic === "dataset_projection") {
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
  if (topic === "dagster_runs") {
    void queryClient.invalidateQueries({
      queryKey: ["pipeline", "dagster-runs"],
    });
    void queryClient.invalidateQueries({
      queryKey: ["pipeline", "dagster-run"],
    });
    void queryClient.invalidateQueries({ queryKey: ["pipeline", "overview"] });
    void queryClient.invalidateQueries({ queryKey: ["pipeline", "schedules"] });
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
  if (topic.startsWith("dagster_run:")) {
    const runId = topicId(topic, "dagster_run:");
    void queryClient.invalidateQueries({
      queryKey: ["pipeline", "dagster-run", runId],
    });
    void queryClient.invalidateQueries({
      queryKey: ["pipeline", "dagster-runs"],
    });
    void queryClient.invalidateQueries({ queryKey: ["pipeline", "overview"] });
    void queryClient.invalidateQueries({ queryKey: ["pipeline", "schedules"] });
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
  if (topic === "dagster_schedules") {
    void queryClient.invalidateQueries({ queryKey: ["pipeline", "schedules"] });
    void queryClient.invalidateQueries({ queryKey: ["pipeline", "overview"] });
    invalidateOpsDatasetQueries(queryClient);
    return;
  }
}

function parseLiveMessage(raw: string): OpsLiveMessage | null {
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? (parsed as OpsLiveMessage) : null;
  } catch {
    return null;
  }
}

export const __testing = {
  buildOpsLiveUrl,
  canonicalTopicDependency,
  connectionStateForFailureCount,
  domainEventsForTopic,
  fetchOpsLiveTicket,
  invalidateLiveTopic,
  reconnectDelayMs,
  messageTopicsMatch,
  serverFrameSequence,
  topicsFromDependency,
};

export function useOpsLiveInvalidation({
  topics,
  enabled = true,
  pollIntervalMs = 2_000,
  invalidationAdapter,
}: {
  topics: readonly OpsLiveTopic[];
  enabled?: boolean;
  pollIntervalMs?: number;
  invalidationAdapter?: OpsLiveInvalidationAdapter;
}) {
  const queryClient = useQueryClient();
  const effectiveEnabled = enabled && !OPS_LIVE_DISABLED;
  const topicDependency = canonicalTopicDependency(topics);
  const stableTopics = useMemo(
    () => topicsFromDependency(topicDependency),
    [topicDependency],
  );
  const adapterRef = useRef(invalidationAdapter);
  const [state, setState] = useState<OpsLiveConnectionState>("connecting");
  const [lastError, setLastError] = useState<string | null>(null);

  useEffect(() => {
    adapterRef.current = invalidationAdapter;
  }, [invalidationAdapter]);

  useEffect(() => {
    if (!effectiveEnabled || stableTopics.length === 0) {
      return undefined;
    }
    if (typeof window === "undefined" || !("WebSocket" in window)) {
      return undefined;
    }

    let closed = false;
    let reconnectAttempt = 0;
    let reconnectTimer: number | null = null;
    let ticketTimeoutTimer: number | null = null;
    let liveWatchdogTimer: number | null = null;
    let ticketAbortController: AbortController | null = null;
    let socket: WebSocket | null = null;

    function clearReconnectTimer() {
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    }

    function clearTicketRequest() {
      if (ticketTimeoutTimer !== null) {
        window.clearTimeout(ticketTimeoutTimer);
        ticketTimeoutTimer = null;
      }
      ticketAbortController?.abort();
      ticketAbortController = null;
    }

    function clearLiveWatchdog() {
      if (liveWatchdogTimer !== null) {
        window.clearTimeout(liveWatchdogTimer);
        liveWatchdogTimer = null;
      }
    }

    function scheduleReconnect() {
      if (closed) {
        return;
      }
      clearReconnectTimer();
      clearLiveWatchdog();
      reconnectAttempt += 1;
      setState(connectionStateForFailureCount(reconnectAttempt));
      const delay = reconnectDelayMs(reconnectAttempt - 1);
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    }

    async function connect() {
      if (closed) {
        return;
      }
      setState(
        reconnectAttempt === 0
          ? "connecting"
          : connectionStateForFailureCount(reconnectAttempt),
      );
      let ticket: OpsLiveTicket;
      const ticketController = new AbortController();
      ticketAbortController = ticketController;
      ticketTimeoutTimer = window.setTimeout(() => {
        ticketTimeoutTimer = null;
        ticketController.abort();
      }, TICKET_FETCH_TIMEOUT_MS);
      try {
        ticket = await fetchOpsLiveTicket(ticketController.signal);
      } catch (error) {
        if (closed) {
          return;
        }
        const ticketError =
          error instanceof OpsLiveTicketRequestError ? error : null;
        setLastError(error instanceof Error ? error.message : String(error));
        if (ticketError?.unauthorized) {
          setState("unauthorized");
          return;
        }
        scheduleReconnect();
        return;
      } finally {
        if (ticketAbortController === ticketController) {
          ticketAbortController = null;
        }
        if (ticketTimeoutTimer !== null) {
          window.clearTimeout(ticketTimeoutTimer);
          ticketTimeoutTimer = null;
        }
      }
      if (closed) {
        return;
      }
      let connectedSocket: WebSocket;
      try {
        connectedSocket = new WebSocket(
          buildOpsLiveUrl(pollIntervalMs),
          ticket.subprotocol,
        );
        socket = connectedSocket;
      } catch (error) {
        setLastError(error instanceof Error ? error.message : String(error));
        scheduleReconnect();
        return;
      }
      let connectionHealthy = false;
      let subscriptionReady = false;
      let protocolFailed = false;
      let lastServerSequence = 0;

      function armLiveWatchdog(timeoutMs: number, message: string) {
        clearLiveWatchdog();
        liveWatchdogTimer = window.setTimeout(() => {
          liveWatchdogTimer = null;
          if (closed || socket !== connectedSocket) {
            return;
          }
          socket = null;
          connectedSocket.onopen = null;
          connectedSocket.onmessage = null;
          connectedSocket.onerror = null;
          connectedSocket.onclose = null;
          setLastError(message);
          try {
            connectedSocket.close(CLIENT_STALE_CLOSE_CODE, message);
          } catch {
            // stale socket close는 best effort이며 직접 reconnect는 계속한다.
          }
          scheduleReconnect();
        }, timeoutMs);
      }

      function markConnectionHealthy() {
        connectionHealthy = true;
        reconnectAttempt = 0;
        setLastError(null);
        setState("live");
        armLiveWatchdog(
          LIVE_INACTIVITY_TIMEOUT_MS,
          "ops live heartbeat가 중단되었습니다.",
        );
      }

      function markInvalidLiveFrame(message: string) {
        if (protocolFailed || closed || socket !== connectedSocket) {
          return;
        }
        // wire 계약을 한 번이라도 위반한 socket은 다시 신뢰하지 않는다. handler를
        // 먼저 분리해 close event와 중복 reconnect를 막고 새 ticket/socket에서 exact
        // replace를 다시 보낸다.
        protocolFailed = true;
        connectionHealthy = false;
        subscriptionReady = false;
        setLastError(message);
        clearLiveWatchdog();
        socket = null;
        connectedSocket.onopen = null;
        connectedSocket.onmessage = null;
        connectedSocket.onerror = null;
        connectedSocket.onclose = null;
        try {
          connectedSocket.close(CLIENT_STALE_CLOSE_CODE, message);
        } catch {
          // protocol-failed socket close는 best effort이며 reconnect는 계속한다.
        }
        scheduleReconnect();
      }

      const remainingTicketMs = Date.parse(ticket.expires_at) - Date.now();
      armLiveWatchdog(
        Math.max(0, Math.min(PRE_HEALTHY_TIMEOUT_MS, remainingTicketMs)),
        "ops live handshake가 제한 시간 안에 완료되지 않았습니다.",
      );

      connectedSocket.onopen = () => {
        if (closed || socket !== connectedSocket) {
          return;
        }
        connectedSocket.send(
          JSON.stringify({ type: "replace", topics: stableTopics }),
        );
      };
      connectedSocket.onmessage = (event) => {
        if (closed || socket !== connectedSocket) {
          return;
        }
        if (typeof event.data !== "string") {
          markInvalidLiveFrame("ops live frame은 JSON 문자열이어야 합니다.");
          return;
        }
        const message = parseLiveMessage(event.data);
        if (!message) {
          markInvalidLiveFrame("ops live frame JSON 형식이 올바르지 않습니다.");
          return;
        }
        const sequence = serverFrameSequence(message, lastServerSequence);
        if (sequence === null) {
          markInvalidLiveFrame("ops live frame envelope가 올바르지 않습니다.");
          return;
        }
        lastServerSequence = sequence;
        if (message.type === "hello") {
          return;
        }
        if (message.type === "subscribed") {
          subscriptionReady = messageTopicsMatch(message.topics, stableTopics);
          if (!subscriptionReady) {
            markInvalidLiveFrame("ops live 구독 topic 확인에 실패했습니다.");
          }
          return;
        }
        if (message.type === "heartbeat") {
          if (
            !subscriptionReady ||
            !messageTopicsMatch(message.topics, stableTopics)
          ) {
            markInvalidLiveFrame("ops live heartbeat topic 확인에 실패했습니다.");
          } else {
            markConnectionHealthy();
          }
          return;
        }
        if (message.type === "error") {
          subscriptionReady = false;
          markInvalidLiveFrame(
            typeof message.message === "string"
              ? message.message
              : "ops live error",
          );
          return;
        }
        if (message.type === "snapshot" || message.type === "update") {
          if (!subscriptionReady || !isLiveDataFrame(message, stableTopics)) {
            markInvalidLiveFrame("ops live data frame 형식이 올바르지 않습니다.");
            return;
          }
          markConnectionHealthy();
          invalidateLiveTopic(
            queryClient,
            message.topic,
            adapterRef.current,
          );
          return;
        }
        markInvalidLiveFrame("지원하지 않는 ops live frame입니다.");
      };
      connectedSocket.onerror = () => {
        if (closed || socket !== connectedSocket) {
          return;
        }
        setLastError("ops live websocket error");
      };
      connectedSocket.onclose = (event) => {
        clearLiveWatchdog();
        if (socket === connectedSocket) {
          socket = null;
        }
        if (closed) {
          return;
        }
        if (event.code === OPS_LIVE_UNAUTHORIZED_CLOSE_CODE) {
          setLastError("ops live 로그인이 필요합니다.");
          setState("unauthorized");
          return;
        }
        if (event.code === OPS_LIVE_EXPIRED_CLOSE_CODE) {
          if (!connectionHealthy) {
            setLastError("ops live lease가 안정 frame 전에 종료되었습니다.");
            scheduleReconnect();
            return;
          }
          reconnectAttempt = 0;
          setState("connecting");
          clearReconnectTimer();
          reconnectTimer = window.setTimeout(() => {
            reconnectTimer = null;
            void connect();
          }, 0);
          return;
        }
        scheduleReconnect();
      };
    }

    const unsubscribeLogout = subscribeAdminLogout(() => {
      closed = true;
      clearReconnectTimer();
      clearTicketRequest();
      clearLiveWatchdog();
      socket?.close(1000, "admin logout");
      socket = null;
      setLastError("로그아웃되어 ops live 연결을 종료했습니다.");
      setState("unauthorized");
    });
    void connect();
    return () => {
      closed = true;
      clearReconnectTimer();
      clearTicketRequest();
      clearLiveWatchdog();
      unsubscribeLogout();
      socket?.close(1000);
    };
  }, [effectiveEnabled, pollIntervalMs, queryClient, stableTopics]);

  const browserSupportsWebSocket =
    typeof window === "undefined" || "WebSocket" in window;
  const effectiveState: OpsLiveConnectionState =
    !effectiveEnabled || stableTopics.length === 0
      ? "disabled"
      : browserSupportsWebSocket
        ? state
        : "unavailable";
  const mode: OpsLiveMode =
    effectiveState === "disabled" || effectiveState === "unauthorized"
      ? "disabled"
      : effectiveState === "live"
        ? "live"
        : "polling";

  return {
    state: effectiveState,
    mode,
    lastError,
    topics: stableTopics,
  };
}
