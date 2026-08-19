"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (list + inspector rail) · design-system: design.md · designed-as-app

import { RefreshCwIcon } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { opsLiveConnectionLabel, useOpsLiveInvalidation } from "@/api/live";
import {
  type ExecutionKind,
  type ExecutionStatus,
  type PipelineOverviewResponse,
  usePipelineOverview,
} from "@/api/pipeline";
import { AdminShell } from "@/components/admin-shell";
import { StatStrip } from "@/components/stat-strip";
import { LiveBadge, StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatCount } from "@/lib/format";
import { statusLabel, toneFor } from "@/lib/status-label";

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
  providerDatasetId?: number;
  syncScope?: string;
  operationKey?: string;
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
    providerDatasetId: initial.providerDatasetId,
    syncScope: initial.syncScope,
    operationKey: initial.operationKey,
    createdFrom: initial.createdFrom,
    createdTo: initial.createdTo,
  };
}

function positiveInteger(value: string): number | undefined {
  const parsed = Number(value.trim());
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
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

function sensorDisplayName(name: string): string {
  if (name === QUEUE_SENSOR_NAME) return "큐 sensor";
  if (name.includes("failure")) return "failure sensor";
  return name;
}

/**
 * 상태별 실행 수 — **키가 없으면 0건**이다.
 *
 * `operations_by_status`는 sparse map이다: 서버가 GROUP BY로 집계하므로 0건인 버킷은 응답에서
 * 아예 빠지고, OpenAPI에도 required 키가 없다(`propertyNames` enum만 있는 additionalProperties).
 * 그래서 키 부재는 "모름"이 아니라 "0건"이다 — 응답이 도착한 뒤에도 undefined로 흘리면 StatStrip이
 * `—`를 그려 **실제 0을 미지값으로** 읽히게 만든다(M36의 반대 오류: 가짜 0이 금지인 만큼 가짜
 * 미지값도 금지다. 빈 큐가 `—`로 보이면 "집계를 못 읽었다"는 뜻이 되어 운영자가 조사를 시작한다).
 * 값을 정말 모르는 구간은 응답 자체가 없는 로딩·에러뿐이므로 그때만 undefined를 남긴다.
 *
 * 읽기를 이 함수 하나로 좁히는 이유: 생성 타입의 index signature(`{ [key: string]: number }`)는
 * 키 부재를 표현하지 못해서(`noUncheckedIndexedAccess` 미사용) `byStatus.queued`가 타입상 `number`로
 * 보이지만 런타임에는 undefined다 — 호출부에서 직접 읽으면 컴파일러가 막아 주지 않는다.
 */
function operationCount(
  data: PipelineOverviewResponse["data"] | undefined,
  status: ExecutionStatus,
): number | undefined {
  if (!data) {
    return undefined;
  }
  return data.operations_by_status[status] ?? 0;
}

/**
 * 상태 스트립(design.md §Macrostructure dashboard · M37) — 아이콘 타일 KPI 대신 StatStrip 하나.
 * 값은 query가 resolve되기 전엔 `—`(M36 — 가짜 0 금지). 반대로 응답이 온 뒤 상태 버킷이 비어 있는
 * 것은 알려진 0이다 — `operationCount()` 참고. Dagster 상태는 라벨 톤 dot + 라벨로,
 * run count·sensor는 caption 한 줄(배지 counter 금지, M22).
 */
function OverviewStrip({
  overview,
}: {
  overview: ReturnType<typeof usePipelineOverview>;
}) {
  const data = overview.data?.data;
  const dagster = data?.dagster;

  const queueState = queueSensorState(overview.data);
  const loading = overview.isLoading || (overview.isError && !overview.data);
  const dagsterStatus = dagster?.status ?? "unknown";
  const runCounts = Object.entries(dagster?.run_counts ?? {});
  const sensors = dagster?.sensors ?? [];

  return (
    <section aria-label="파이프라인 상태 스트립" className="space-y-4">
      {overview.isError ? (
        <Alert variant="destructive">
          <AlertTitle>상태 스트립을 불러오지 못했습니다</AlertTitle>
          <AlertDescription>{overview.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {dagster && dagster.status !== "ok" ? (
        <Alert
          variant={dagster.status === "unavailable" ? "destructive" : "warning"}
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
      <StatStrip
        ariaLabel="파이프라인 요약"
        isLoading={loading}
        items={[
          {
            key: "active",
            label: "활성 작업",
            value: data?.active_operations,
            unit: "건",
            caption: "queued + running",
          },
          // 상태 축(operations_by_status)의 낱말은 tone table이 정본이다(design.md: 문구도
          // `statusLabel()` 한 곳에서). 손으로 적으면 같은 축이 KPI와 실행 행 배지에서 다른
          // 단어로 보인다 — "대기"는 사람의 결정을 기다리는 `pending`(warning)의 낱말이라
          // 기계 큐 `queued`는 "실행 대기"고, `running`도 배지와 같은 글자를 써야 한다.
          {
            key: "queued",
            label: statusLabel("queued"),
            value: operationCount(data, "queued"),
            unit: "건",
            caption: "canonical root",
          },
          {
            key: "running",
            label: statusLabel("running"),
            value: operationCount(data, "running"),
            unit: "건",
            caption: "canonical root",
          },
          {
            key: "failed-24h",
            label: "최근 24시간 실패",
            value: data?.failed_operations_24h,
            unit: "건",
            tone:
              data && (data.failed_operations_24h ?? 0) > 0
                ? "destructive"
                : undefined,
            caption: "canonical root",
          },
          {
            key: "dagster",
            label: "Dagster",
            testId: "dagster-status-card",
            tone: toneFor(dagsterStatus),
            value: (
              <span className="text-lg font-semibold">
                {statusLabel(dagsterStatus)}
              </span>
            ),
            caption: (
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                {dagster?.version ? (
                  <span className="tabular-nums">v{dagster.version}</span>
                ) : null}
                {runCounts.map(([status, count]) => (
                  <span className="font-mono tabular-nums" key={status}>
                    {status.toLowerCase()} {formatCount(count)}
                  </span>
                ))}
                {sensors.map((sensor) => (
                  <span className="inline-flex items-center gap-1" key={sensor.name}>
                    {sensorDisplayName(sensor.name)}
                    <StatusBadge
                      label={sensor.status ? statusLabel(sensor.status) : undefined}
                      status={sensor.status?.toLowerCase() ?? null}
                    />
                  </span>
                ))}
              </span>
            ),
          },
        ]}
      />
    </section>
  );
}

/** URL이 정본인 canonical dataset 필터 축(triple)과 그 fail-closed 정리.
 *
 * `PipelineClient` 본문에서 떼어낸다 — 컴포넌트가 300줄을 넘으면 react-doctor가
 * 막고, 무엇보다 이 규칙 자체가 한 덩어리로 읽혀야 한다.
 */
function useCanonicalDatasetFilters(
  searchParams: ReturnType<typeof useSearchParams>,
  updateUrl: (
    updates: Record<string, string | null>,
    mode?: "push" | "replace",
  ) => void,
): {
  hasProviderDatasetFilter: boolean;
  urlOperationKey: string;
  urlProviderDatasetId: string;
  urlProviderDatasetIdValue: number | undefined;
  urlSyncScope: string;
} {
  const urlProviderDatasetId =
    searchParams.get("provider_dataset_id")?.trim() ?? "";
  const urlProviderDatasetIdValue = positiveInteger(urlProviderDatasetId);
  const urlSyncScope = searchParams.get("sync_scope")?.trim() ?? "";
  const urlOperationKey = searchParams.get("operation_key")?.trim() ?? "";
  // scope/operation은 provider_dataset_id에 매달린 **추가** 축이다. 셋을 모두
  // 요구하면 (id, scope)만 담은 딥링크에서 입력값이 화면에서 사라지고 REST에도
  // 실리지 않아, scope로 좁힌 event/execution 딥링크가 통째로 무력화된다.
  // 게이트 축은 provider_dataset_id 하나다(자연키 시절 provider×dataset pair가
  // 하던 역할). 불완전 tuple의 fail-closed는 아래 정리 effect가 맡는다.
  const hasProviderDatasetFilter = urlProviderDatasetIdValue !== undefined;
  const hasLegacyDatasetFilters = Boolean(
    searchParams.get("provider") ||
      searchParams.get("dataset") ||
      searchParams.get("dataset_key"),
  );
  const hasOrphanScopeFilters = Boolean(
    urlProviderDatasetIdValue === undefined &&
      (urlSyncScope || urlOperationKey),
  );

  // 외부 deep link나 browser history가 이전 자연키 filter를 복원해도 fail-closed한다.
  // provider_dataset_id 없이 남은 scope/operation은 어떤 membership도 가리키지
  // 못하므로 cursor와 함께 폐기한다.
  useEffect(() => {
    if (hasLegacyDatasetFilters || hasOrphanScopeFilters) {
      updateUrl({ sync_scope: null, operation_key: null }, "replace");
    }
  }, [hasLegacyDatasetFilters, hasOrphanScopeFilters, updateUrl]);

  return {
    hasProviderDatasetFilter,
    urlOperationKey,
    urlProviderDatasetId,
    urlProviderDatasetIdValue,
    urlSyncScope,
  };
}

function useTimelineFilters({
  hasProviderDatasetFilter,
  searchParams,
  urlOperationKey,
  urlProviderDatasetIdValue,
  urlSyncScope,
}: {
  hasProviderDatasetFilter: boolean;
  searchParams: ReturnType<typeof useSearchParams>;
  urlOperationKey: string;
  urlProviderDatasetIdValue: number | undefined;
  urlSyncScope: string;
}): ReturnType<typeof normalizeTimelineFilters> {
  return useMemo(
    () =>
      normalizeTimelineFilters({
        kind: searchParams.get("kind") ?? undefined,
        status: searchParams.get("status") ?? undefined,
        providerDatasetId: urlProviderDatasetIdValue,
        syncScope: hasProviderDatasetFilter ? urlSyncScope || undefined : undefined,
        operationKey: hasProviderDatasetFilter
          ? urlOperationKey || undefined
          : undefined,
        createdFrom: searchParams.get("created_from") ?? undefined,
        createdTo: searchParams.get("created_to") ?? undefined,
      }),
    [
      hasProviderDatasetFilter,
      searchParams,
      urlProviderDatasetIdValue,
      urlOperationKey,
      urlSyncScope,
    ],
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
      const providerDatasetId = next.get("provider_dataset_id")?.trim() ?? "";
      const providerDatasetChanged =
        Object.hasOwn(updates, "provider_dataset_id") &&
        providerDatasetId !==
          (previous.get("provider_dataset_id")?.trim() ?? "");
      const scopeExplicitlyUpdated = Object.hasOwn(updates, "sync_scope");
      const operationExplicitlyUpdated = Object.hasOwn(
        updates,
        "operation_key",
      );
      // dataset operation filter는 triple만 유효하다. ID 변경 때 scope와
      // operation을 같이 주지 않았거나 scope 변경 때 operation을 같이 주지
      // 않으면 이전 member 일부를 절대 재사용하지 않는다.
      if (!positiveInteger(providerDatasetId)) {
        next.delete("sync_scope");
        next.delete("operation_key");
      } else if (
        providerDatasetChanged &&
        (!scopeExplicitlyUpdated || !operationExplicitlyUpdated)
      ) {
        next.delete("sync_scope");
        next.delete("operation_key");
      } else if (scopeExplicitlyUpdated && !operationExplicitlyUpdated) {
        next.delete("operation_key");
      }
      // provider/dataset 자연키 filter는 T-VN-33에서 제거됐다.
      next.delete("provider");
      next.delete("dataset");
      next.delete("dataset_key");
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

  const {
    hasProviderDatasetFilter,
    urlOperationKey,
    urlProviderDatasetId,
    urlProviderDatasetIdValue,
    urlSyncScope,
  } = useCanonicalDatasetFilters(searchParams, updateUrl);

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

  const timelineFilters = useTimelineFilters({
    hasProviderDatasetFilter,
    searchParams,
    urlOperationKey,
    urlProviderDatasetIdValue,
    urlSyncScope,
  });
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
          <LiveBadge
            label={opsLiveConnectionLabel(live.state)}
            state={live.state}
          />
          <Button
            loading={overview.isFetching}
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
              disabledReason="큐 sensor가 RUNNING으로 확인될 때까지 새 갱신 요청을 만들지 않습니다."
              type="button"
            >
              갱신 요청 생성
            </Button>
          )}
        </div>
      }
      description="실행 타임라인·전역 이벤트·스케줄·갱신 요청을 한 화면에서 관측하고 조작합니다."
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
          <TabsList className="w-full" variant="line">
            <TabsTrigger value="executions">실행 타임라인</TabsTrigger>
            <TabsTrigger value="events">전역 이벤트</TabsTrigger>
            <TabsTrigger value="schedules">스케줄</TabsTrigger>
          </TabsList>
          <TabsContent className="mt-4" value="executions">
            <div
              className={
                selected
                  ? "grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]"
                  : "space-y-6"
              }
            >
              <div className="min-w-0 space-y-6">
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
              providerDatasetId={urlProviderDatasetId}
              syncScope={hasProviderDatasetFilter ? urlSyncScope : ""}
              operationKey={hasProviderDatasetFilter ? urlOperationKey : ""}
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
