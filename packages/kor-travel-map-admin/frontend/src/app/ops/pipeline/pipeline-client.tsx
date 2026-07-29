"use client";

import { RefreshCwIcon } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { opsLiveConnectionLabel, useOpsLiveInvalidation } from "@/api/live";
import {
  type ExecutionKind,
  type PipelineOverviewResponse,
  usePipelineOverview,
} from "@/api/pipeline";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatCount } from "@/lib/format";

import { ExecutionDetailPanel } from "./execution-detail-panel";
import { ExecutionTimeline, type TimelineFilters } from "./execution-timeline";
import { DagsterRunsPanel, PipelineEventsPanel } from "./events-panel";
import { parseExecutionParam } from "./pipeline-shared";
import { RequestCreateDialog } from "./request-dialog";
import { SchedulePanel } from "./schedule-panel";

const QUEUE_SENSOR_NAME = "feature_update_request_queue_sensor";

interface InitialFilters {
  kind?: string;
  status?: string;
  provider?: string;
  datasetKey?: string;
  syncScope?: string;
  createdFrom?: string;
  createdTo?: string;
  loadBatchId?: string;
  parentJobId?: string;
}

function normalizeTimelineFilters(initial: InitialFilters): TimelineFilters {
  return {
    kind:
      initial.kind === "import_job" || initial.kind === "update_request"
        ? initial.kind
        : undefined,
    status:
      initial.status === "queued" ||
      initial.status === "running" ||
      initial.status === "done" ||
      initial.status === "failed" ||
      initial.status === "cancelled"
        ? initial.status
        : undefined,
    provider: initial.provider,
    datasetKey: initial.datasetKey,
    syncScope: initial.syncScope,
    createdFrom: initial.createdFrom,
    createdTo: initial.createdTo,
  };
}

interface QueueSensorState {
  operational: boolean;
  status: string;
  description: string;
}

function queueSensorState(
  response: PipelineOverviewResponse | undefined,
): QueueSensorState | null {
  if (!response) {
    return null;
  }
  if (response.data.dagster.status !== "ok") {
    return {
      operational: false,
      status: `DAGSTER_${response.data.dagster.status.toUpperCase()}`,
      description:
        "Dagster 상태 스냅샷을 신뢰할 수 없습니다. 새 갱신 요청은 안전을 위해 차단됩니다.",
    };
  }
  const sensors = response.data.dagster.sensors ?? [];
  const sensor = sensors.find((item) => item.name === QUEUE_SENSOR_NAME);
  if (!sensor) {
    return {
      operational: false,
      status: "MISSING",
      description:
        "필수 큐 sensor가 응답에 없습니다. 새 갱신 요청은 안전을 위해 차단됩니다.",
    };
  }
  const status = sensor.status ?? "UNKNOWN";
  if (status === "RUNNING") {
    return { operational: true, status, description: "" };
  }
  return {
    operational: false,
    status,
    description: `필수 큐 sensor 상태가 ${status}입니다. 새 갱신 요청은 안전을 위해 차단됩니다.`,
  };
}

function KpiCard({
  label,
  value,
  caption,
}: {
  label: string;
  value: string;
  caption?: string;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-xs font-bold tracking-[0.05em] text-muted-foreground uppercase">
          {label}
        </p>
        <p className="mt-1 text-[36px] leading-none font-bold">{value}</p>
        {caption ? (
          <p className="mt-1 text-xs text-muted-foreground">{caption}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function OverviewStrip({
  overview,
}: {
  overview: ReturnType<typeof usePipelineOverview>;
}) {
  const data = overview.data?.data;
  const dagster = data?.dagster;

  const queueState = queueSensorState(overview.data);
  const operationsByStatus = data?.operations_by_status ?? {};

  return (
    <section aria-label="파이프라인 상태 스트립" className="space-y-4">
      {overview.isError ? (
        <Alert variant="destructive">
          <AlertTitle>상태 스트립 호출 실패</AlertTitle>
          <AlertDescription>{overview.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {dagster && dagster.status !== "ok" ? (
        <Alert
          variant={dagster.status === "unavailable" ? "destructive" : "default"}
        >
          <AlertTitle>
            {dagster.status === "unavailable"
              ? "Dagster 연결 불가"
              : "Dagster 상태 확인 필요"}
          </AlertTitle>
          <AlertDescription>
            {(dagster.errors ?? []).length > 0
              ? (dagster.errors ?? []).join(" / ")
              : "Dagster webserver 상태를 확인하세요."}{" "}
            타임라인(DB)은 계속 동작합니다.
          </AlertDescription>
        </Alert>
      ) : null}
      {queueState && !queueState.operational ? (
        <Alert data-testid="queue-sensor-alert" variant="destructive">
          <AlertTitle>
            {queueState.status === "STOPPED"
              ? "갱신 요청 큐 sensor 중지됨"
              : "갱신 요청 큐 sensor 실행 불가"}
          </AlertTitle>
          <AlertDescription>
            <span className="font-mono">{QUEUE_SENSOR_NAME}</span> —{" "}
            {queueState.description} 스케줄 탭에서 sensor 상태를 확인하세요.
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <KpiCard
          caption="queued + running"
          label="활성 작업"
          value={formatCount(data?.active_operations ?? 0)}
        />
        <KpiCard
          caption="canonical root"
          label="대기"
          value={formatCount(operationsByStatus.queued ?? 0)}
        />
        <KpiCard
          caption="canonical root"
          label="실행 중"
          value={formatCount(operationsByStatus.running ?? 0)}
        />
        <KpiCard
          caption="canonical root"
          label="최근 24시간 실패"
          value={formatCount(data?.failed_operations_24h ?? 0)}
        />
        <Card data-testid="dagster-status-card">
          <CardContent className="pt-6">
            <p className="text-xs font-bold tracking-[0.05em] text-muted-foreground uppercase">
              Dagster
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusBadge status={dagster?.status ?? "unknown"} />
              {dagster?.version ? (
                <span className="text-xs text-muted-foreground">
                  v{dagster.version}
                </span>
              ) : null}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(dagster?.run_counts ?? {}).map(
                ([status, count]) => (
                  <Badge key={status} variant="outline">
                    {status}: {formatCount(count)}
                  </Badge>
                ),
              )}
              {(dagster?.sensors ?? []).map((sensor) => (
                <Badge
                  key={sensor.name}
                  variant={
                    sensor.status === "RUNNING" ? "secondary" : "destructive"
                  }
                >
                  {sensor.name === QUEUE_SENSOR_NAME
                    ? "큐 sensor"
                    : sensor.name.includes("failure")
                      ? "failure sensor"
                      : sensor.name}
                  : {sensor.status ?? "-"}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

export function PipelineClient() {
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const urlStateRef = useRef<string | null>(null);
  if (urlStateRef.current === null) {
    urlStateRef.current = searchParams.toString();
  }
  const focusReturnExecutionIdRef = useRef<string | null>(null);
  const focusAfterCloseRef = useRef(false);
  const urlSchedule = searchParams.get("schedule");
  const selected = useMemo(
    () => parseExecutionParam(searchParams.get("execution") ?? undefined),
    [searchParams],
  );
  const urlTab = searchParams.get("tab");
  const tab =
    urlTab === "events" || urlTab === "schedules"
      ? urlTab
      : urlSchedule
        ? "schedules"
        : "executions";

  const live = useOpsLiveInvalidation({
    topics: [
      "import_jobs",
      "feature_update_requests",
      "dagster_runs",
      "dagster_schedules",
      "provider_sync",
      "dataset_projection",
    ],
  });
  // NUX 없음 — 새 UI는 Dagster iframe을 쓰지 않아 `/ops/pipeline/nux-seen`이
  // 계약에서 제거됐다(플랜 §2 개정, C3a/#687).
  const overview = usePipelineOverview(10);
  const queueOperational =
    queueSensorState(overview.data)?.operational === true;

  const updateUrl = useCallback(
    (
      updates: Record<string, string | null>,
      mode: "push" | "replace" = "push",
    ) => {
      const previous = new URLSearchParams(urlStateRef.current ?? "");
      const next = new URLSearchParams(previous);
      for (const [key, value] of Object.entries(updates)) {
        if (value === null || value === "") {
          next.delete(key);
        } else {
          next.set(key, value);
        }
      }
      const provider = next.get("provider")?.trim() ?? "";
      const datasetKey = next.get("dataset_key")?.trim() ?? "";
      const providerChanged =
        Object.hasOwn(updates, "provider") &&
        provider !== (previous.get("provider")?.trim() ?? "");
      const datasetChanged =
        Object.hasOwn(updates, "dataset_key") &&
        datasetKey !== (previous.get("dataset_key")?.trim() ?? "");
      const datasetExplicitlyUpdated = Object.hasOwn(updates, "dataset_key");
      const scopeExplicitlyUpdated = Object.hasOwn(updates, "sync_scope");
      // provider가 없으면 dataset/scope 모두 invalid다. exact pair의 어느 축이
      // 바뀌어도 같은 전이에 새 scope를 명시하지 않았다면 이전 pair scope를
      // cursor와 함께 폐기한다.
      if (!provider) {
        next.delete("dataset_key");
        next.delete("sync_scope");
      } else if (providerChanged && !datasetExplicitlyUpdated) {
        next.delete("dataset_key");
        next.delete("sync_scope");
      } else if (
        !datasetKey ||
        ((providerChanged || datasetChanged) && !scopeExplicitlyUpdated)
      ) {
        next.delete("sync_scope");
      }
      const query = next.toString();
      const href = query ? `${pathname}?${query}` : pathname;
      const currentQuery = urlStateRef.current ?? "";
      const current = currentQuery ? `${pathname}?${currentQuery}` : pathname;
      if (href === current) {
        return;
      }
      urlStateRef.current = query;
      window.history[mode === "push" ? "pushState" : "replaceState"](
        null,
        "",
        href,
      );
    },
    [pathname],
  );

  useEffect(() => {
    urlStateRef.current = searchParams.toString();
  }, [searchParams]);

  const urlProvider = searchParams.get("provider")?.trim() ?? "";
  const urlDatasetKey = searchParams.get("dataset_key")?.trim() ?? "";
  const urlSyncScope = searchParams.get("sync_scope")?.trim() ?? "";
  const hasExactScopeTuple = Boolean(urlProvider && urlDatasetKey);

  // 외부 deep link나 browser history가 불완전 tuple을 복원해도 scope를
  // fail-closed한다. 하위 목록은 정규화된 props를 받아 cursor를 함께 비운다.
  useEffect(() => {
    if (!urlProvider && (urlDatasetKey || urlSyncScope)) {
      updateUrl({ dataset_key: null, sync_scope: null }, "replace");
    } else if (urlSyncScope && !hasExactScopeTuple) {
      updateUrl({ sync_scope: null }, "replace");
    }
  }, [hasExactScopeTuple, updateUrl, urlDatasetKey, urlProvider, urlSyncScope]);

  const selectExecution = (
    kind: ExecutionKind,
    id: string,
    focusExecutionId = id,
  ) => {
    focusReturnExecutionIdRef.current = focusExecutionId;
    if (selected?.kind === kind && selected.id === id) {
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "execution", kind, id],
      });
    }
    updateUrl({ execution: `${kind}:${id}`, tab: "executions" });
  };

  const timelineFilters = useMemo(
    () =>
      normalizeTimelineFilters({
        kind: searchParams.get("kind") ?? undefined,
        status: searchParams.get("status") ?? undefined,
        provider: urlProvider || undefined,
        datasetKey: urlProvider ? urlDatasetKey || undefined : undefined,
        syncScope: hasExactScopeTuple ? urlSyncScope || undefined : undefined,
        createdFrom: searchParams.get("created_from") ?? undefined,
        createdTo: searchParams.get("created_to") ?? undefined,
      }),
    [
      hasExactScopeTuple,
      searchParams,
      urlDatasetKey,
      urlProvider,
      urlSyncScope,
    ],
  );
  const timelineLoadBatchId = searchParams.get("load_batch_id") ?? undefined;
  const timelineParentJobId = searchParams.get("parent_job_id") ?? undefined;

  useEffect(() => {
    if (selected || !focusAfterCloseRef.current) {
      return;
    }
    focusAfterCloseRef.current = false;
    const focusExecutionId = focusReturnExecutionIdRef.current;
    const frame = requestAnimationFrame(() => {
      const originalRow = focusExecutionId
        ? document.querySelector<HTMLElement>(
            `[data-testid="pipeline-execution-row-${focusExecutionId}"]`,
          )
        : null;
      const fallback =
        document.querySelector<HTMLElement>(
          '[data-testid^="pipeline-execution-row-"]',
        ) ?? document.querySelector<HTMLElement>('[aria-label="실행 종류"]');
      (originalRow ?? fallback)?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [selected]);

  return (
    <AdminShell
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={live.state === "live" ? "default" : "outline"}>
            {opsLiveConnectionLabel(live.state)}
          </Badge>
          <Button
            disabled={overview.isFetching}
            type="button"
            variant="outline"
            onClick={() => void overview.refetch()}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
          {queueOperational ? (
            <RequestCreateDialog onCreated={selectExecution} />
          ) : (
            <Button
              aria-label="갱신 요청 생성 (큐 sensor 확인 필요)"
              disabled
              type="button"
            >
              갱신 요청 생성
            </Button>
          )}
        </div>
      }
      description="실행 타임라인·전역 이벤트·스케줄·갱신 요청을 한 화면에서 관측/조작합니다 (ADR-064 페이지 ①)."
      section="수집 파이프라인"
      title="파이프라인"
    >
      <div className="space-y-6">
        <OverviewStrip overview={overview} />

        <Tabs
          value={tab}
          onValueChange={(value) => {
            updateUrl({ tab: value });
          }}
        >
          <TabsList>
            <TabsTrigger value="executions">실행 타임라인</TabsTrigger>
            <TabsTrigger value="events">전역 이벤트</TabsTrigger>
            <TabsTrigger value="schedules">스케줄</TabsTrigger>
          </TabsList>
          <TabsContent className="mt-4" value="executions">
            <div
              className={
                selected
                  ? "grid gap-4 xl:grid-cols-[minmax(0,1fr)_26rem]"
                  : "space-y-4"
              }
            >
              <div className="min-w-0 space-y-4">
                <ExecutionTimeline
                  initialFilters={timelineFilters}
                  initialLoadBatchId={timelineLoadBatchId}
                  initialParentJobId={timelineParentJobId}
                  selectedExecutionId={selected?.id ?? null}
                  onSelectExecution={selectExecution}
                  onUrlChange={updateUrl}
                />
                <DagsterRunsPanel />
              </div>
              {selected ? (
                <div className="min-w-0">
                  <ExecutionDetailPanel
                    key={`${selected.kind}:${selected.id}`}
                    executionId={selected.id}
                    kind={selected.kind}
                    queueOperational={queueOperational}
                    onClose={() => {
                      focusAfterCloseRef.current = true;
                      updateUrl({ execution: null });
                    }}
                    onSelectExecution={selectExecution}
                  />
                </div>
              ) : null}
            </div>
          </TabsContent>
          <TabsContent className="mt-4" value="events">
            <PipelineEventsPanel
              datasetKey={urlProvider ? urlDatasetKey : ""}
              provider={urlProvider}
              syncScope={hasExactScopeTuple ? urlSyncScope : ""}
              onSelectExecution={selectExecution}
              onUrlChange={updateUrl}
            />
          </TabsContent>
          <TabsContent className="mt-4" value="schedules">
            <SchedulePanel
              highlightSchedule={urlSchedule ?? undefined}
              onHighlightSchedule={(scheduleName) => {
                updateUrl({ schedule: scheduleName, tab: "schedules" });
              }}
            />
          </TabsContent>
        </Tabs>
      </div>
    </AdminShell>
  );
}
