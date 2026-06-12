"use client";

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { BASE_URL } from "./client";

export type OpsLiveConnectionState =
  | "disabled"
  | "connecting"
  | "live"
  | "reconnecting"
  | "unavailable";

export type OpsLiveTopic =
  | "import_jobs"
  | "feature_update_requests"
  | "offline_uploads"
  | "dagster_runs"
  | `import_job:${string}`
  | `import_job_events:${string}`
  | `feature_update_request:${string}`
  | `offline_upload:${string}`
  | `dagster_run:${string}`;

type OpsLiveMessage = {
  type?: string;
  topic?: string;
  topics?: string[];
  message?: string;
};

const reconnectDelaysMs = [1_000, 2_000, 5_000, 10_000, 30_000];

function buildOpsLiveUrl(
  topics: readonly OpsLiveTopic[],
  pollIntervalMs = 2_000,
): string {
  const url = new URL(BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const basePath = url.pathname.replace(/\/+$/, "");
  url.pathname = `${basePath}/v1/ops/live`;
  url.searchParams.set("topics", topics.join(","));
  url.searchParams.set("poll_interval_ms", String(pollIntervalMs));
  return url.toString();
}

function topicId(topic: string, prefix: string) {
  return topic.slice(prefix.length);
}

function invalidateLiveTopic(queryClient: QueryClient, topic: string) {
  if (topic === "import_jobs") {
    void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
    return;
  }
  if (topic.startsWith("import_job_events:")) {
    void queryClient.invalidateQueries({
      queryKey: ["import-job-events", topicId(topic, "import_job_events:")],
    });
    return;
  }
  if (topic.startsWith("import_job:")) {
    const jobId = topicId(topic, "import_job:");
    void queryClient.invalidateQueries({ queryKey: ["import-job", jobId] });
    void queryClient.invalidateQueries({
      queryKey: ["import-job-events", jobId],
    });
    void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
    return;
  }
  if (topic === "feature_update_requests") {
    void queryClient.invalidateQueries({
      queryKey: ["feature-update-requests"],
    });
    void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
    void queryClient.invalidateQueries({ queryKey: ["providers"] });
    void queryClient.invalidateQueries({ queryKey: ["ops-providers"] });
    return;
  }
  if (topic.startsWith("feature_update_request:")) {
    void queryClient.invalidateQueries({
      queryKey: [
        "feature-update-request",
        topicId(topic, "feature_update_request:"),
      ],
    });
    void queryClient.invalidateQueries({
      queryKey: ["feature-update-requests"],
    });
    void queryClient.invalidateQueries({ queryKey: ["providers"] });
    void queryClient.invalidateQueries({ queryKey: ["ops-providers"] });
    return;
  }
  if (topic === "offline_uploads") {
    void queryClient.invalidateQueries({ queryKey: ["offline-uploads"] });
    void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
    return;
  }
  if (topic.startsWith("offline_upload:")) {
    void queryClient.invalidateQueries({
      queryKey: ["offline-upload", topicId(topic, "offline_upload:")],
    });
    void queryClient.invalidateQueries({ queryKey: ["offline-uploads"] });
    return;
  }
  if (topic === "dagster_runs") {
    void queryClient.invalidateQueries({ queryKey: ["ops", "dagster"] });
    return;
  }
  if (topic.startsWith("dagster_run:")) {
    void queryClient.invalidateQueries({ queryKey: ["ops", "dagster"] });
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

export function useOpsLiveInvalidation({
  topics,
  enabled = true,
  pollIntervalMs = 2_000,
}: {
  topics: readonly OpsLiveTopic[];
  enabled?: boolean;
  pollIntervalMs?: number;
}) {
  const queryClient = useQueryClient();
  const topicKey = Array.from(new Set(topics)).sort().join(",");
  const stableTopics = useMemo(
    () =>
      topicKey
        ? (topicKey.split(",").filter(Boolean) as OpsLiveTopic[])
        : ([] as OpsLiveTopic[]),
    [topicKey],
  );
  const [state, setState] = useState<OpsLiveConnectionState>("connecting");
  const [lastError, setLastError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || stableTopics.length === 0) {
      return undefined;
    }
    if (typeof window === "undefined" || !("WebSocket" in window)) {
      return undefined;
    }

    let closed = false;
    let reconnectAttempt = 0;
    let reconnectTimer: number | null = null;
    let socket: WebSocket | null = null;

    function scheduleReconnect() {
      if (closed) {
        return;
      }
      setState("reconnecting");
      const delay =
        reconnectDelaysMs[
          Math.min(reconnectAttempt, reconnectDelaysMs.length - 1)
        ];
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(connect, delay);
    }

    function connect() {
      if (closed) {
        return;
      }
      setState(reconnectAttempt === 0 ? "connecting" : "reconnecting");
      try {
        socket = new WebSocket(buildOpsLiveUrl(stableTopics, pollIntervalMs));
      } catch (error) {
        setLastError(error instanceof Error ? error.message : String(error));
        scheduleReconnect();
        return;
      }
      socket.onmessage = (event) => {
        if (typeof event.data !== "string") {
          return;
        }
        const message = parseLiveMessage(event.data);
        if (!message) {
          return;
        }
        if (message.type === "hello" || message.type === "heartbeat") {
          reconnectAttempt = 0;
          setState("live");
          return;
        }
        if (message.type === "error") {
          setLastError(message.message ?? "ops live error");
          return;
        }
        if (
          (message.type === "snapshot" || message.type === "update") &&
          message.topic
        ) {
          reconnectAttempt = 0;
          setState("live");
          invalidateLiveTopic(queryClient, message.topic);
        }
      };
      socket.onopen = () => {
        setLastError(null);
      };
      socket.onerror = () => {
        setLastError("ops live websocket error");
      };
      socket.onclose = () => {
        if (!closed) {
          scheduleReconnect();
        }
      };
    }

    connect();
    return () => {
      closed = true;
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
      }
      socket?.close(1000);
    };
  }, [enabled, pollIntervalMs, queryClient, stableTopics]);

  const browserSupportsWebSocket =
    typeof window === "undefined" || "WebSocket" in window;
  const effectiveState: OpsLiveConnectionState =
    !enabled || stableTopics.length === 0
      ? "disabled"
      : browserSupportsWebSocket
        ? state
        : "unavailable";

  return { state: effectiveState, lastError, topics: stableTopics };
}
