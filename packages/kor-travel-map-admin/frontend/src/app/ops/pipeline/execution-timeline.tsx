"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (list) · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import { XIcon } from "lucide-react";
import { useMemo, useState } from "react";

import {
  type ExecutionKind,
  type ExecutionStatus,
  type PipelineExecutionRootRecord,
  usePipelineExecutions,
  usePipelineExecutionsHead,
} from "@/api/pipeline";
import { EntityLink } from "@/components/entity-link";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { CursorPager } from "@/components/pagination-bar";
import { SectionCard } from "@/components/section-card";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { NULL_GLYPH, formatDateTime, shortId } from "@/lib/format";
import { statusLabel } from "@/lib/status-label";

import {
  executionKindLabel,
  rootIdentityLabel,
  rootProgressLabel,
} from "./pipeline-shared";

const KIND_OPTIONS: Array<ExecutionKind | "all"> = [
  "all",
  "import_job",
  "update_request",
];
const STATUS_OPTIONS: Array<ExecutionStatus | "all"> = [
  "all",
  "queued",
  "running",
  "done",
  "failed",
  "cancelled",
];
const PAGE_SIZE = 50;

/** 적용 중인 딥링크 필터 칩 — hairline chip + kit 아이콘 버튼(≥ 30px hit target, M23). */
const ACTIVE_FILTER_CHIP_CLASS =
  "inline-flex items-center gap-1 rounded-control border border-border bg-card py-0.5 pr-0.5 pl-2.5 text-xs text-text-primary";

function positiveInteger(value: string): number | undefined {
  const parsed = Number(value.trim());
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
}

export interface TimelineFilters {
  kind?: ExecutionKind;
  status?: ExecutionStatus;
  providerDatasetId?: number;
  syncScope?: string;
  operationKey?: string;
  createdFrom?: string;
  createdTo?: string;
}

type TimelineUrlUpdates = Record<string, string | null>;

interface TimelineDrafts {
  providerDatasetId: string | null;
  syncScope: string | null;
  operationKey: string | null;
  urlSignature: string;
}

function padDatePart(value: number): string {
  return String(value).padStart(2, "0");
}

function datetimeLocalValue(value: string | undefined): string {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return [
    parsed.getFullYear(),
    "-",
    padDatePart(parsed.getMonth() + 1),
    "-",
    padDatePart(parsed.getDate()),
    "T",
    padDatePart(parsed.getHours()),
    ":",
    padDatePart(parsed.getMinutes()),
  ].join("");
}

function datetimeLocalIsoValue(value: string): string | undefined {
  if (!value) {
    return undefined;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
}

function useExecutionTimelineController({
  initialFilters,
  initialLoadBatchId,
  initialParentJobId,
  selectedExecutionId,
  onSelectExecution,
  onUrlChange,
}: {
  initialFilters: TimelineFilters;
  initialLoadBatchId?: string;
  initialParentJobId?: string;
  selectedExecutionId: string | null;
  onSelectExecution: (
    kind: ExecutionKind,
    id: string,
    focusExecutionId?: string,
  ) => void;
  onUrlChange: (updates: TimelineUrlUpdates, mode?: "push" | "replace") => void;
}) {
  const kind = initialFilters.kind ?? "all";
  const status = initialFilters.status ?? "all";
  const urlDraftSignature = JSON.stringify([
    initialFilters.providerDatasetId ?? "",
    initialFilters.syncScope ?? "",
    initialFilters.operationKey ?? "",
  ]);
  const [drafts, setDrafts] = useState<TimelineDrafts>({
    providerDatasetId: null,
    syncScope: null,
    operationKey: null,
    urlSignature: urlDraftSignature,
  });
  if (drafts.urlSignature !== urlDraftSignature) {
    setDrafts({
      providerDatasetId: null,
      syncScope: null,
      operationKey: null,
      urlSignature: urlDraftSignature,
    });
  }
  const providerDatasetId =
    drafts.providerDatasetId ??
    (initialFilters.providerDatasetId
      ? String(initialFilters.providerDatasetId)
      : "");
  const syncScope = drafts.syncScope ?? initialFilters.syncScope ?? "";
  const operationKey = drafts.operationKey ?? initialFilters.operationKey ?? "";
  const createdFrom = datetimeLocalValue(initialFilters.createdFrom);
  const createdTo = datetimeLocalValue(initialFilters.createdTo);
  const loadBatchId = initialLoadBatchId ?? "";
  const parentJobId = initialParentJobId ?? "";
  const providerDatasetIdFilter = positiveInteger(providerDatasetId);
  // 세 축을 **전부** 요구하면 안 된다. 서버 `_canonical_dataset_filter`는
  // provider_dataset_id 단독, +sync_scope, +operation_key를 모두 받는다. 예전
  // 판은 셋이 다 차지 않으면 `provider_dataset_id`까지 버려서, 화면에는 ID가
  // 적혀 있는데 목록은 **전 시스템의 모든 실행**이었다 — 좁히는 실패가 아니라
  // 넓히는 실패(fail-open)라 운영자가 남의 실행을 열고 취소할 수 있었다.
  // 형제 패널 `events-panel.tsx`는 처음부터 이 규칙이었다.
  const exactProviderDatasetIdFilter = providerDatasetIdFilter;
  const syncScopeFilter = providerDatasetIdFilter
    ? syncScope.trim() || undefined
    : undefined;
  const operationKeyFilter = providerDatasetIdFilter
    ? operationKey.trim() || undefined
    : undefined;
  const filterSignature = JSON.stringify([
    kind,
    status,
    providerDatasetId,
    syncScope,
    operationKey,
    createdFrom,
    createdTo,
    loadBatchId,
    parentJobId,
  ]);
  const [paginationSignature, setPaginationSignature] =
    useState(filterSignature);
  const [storedCursorStack, setStoredCursorStack] = useState<string[]>([]);
  const [storedBaselineTop, setStoredBaselineTop] = useState<{
    createdAt: string;
    kind: ExecutionKind;
    id: string;
  } | null>(null);
  const paginationIsCurrent = paginationSignature === filterSignature;
  const cursorStack = paginationIsCurrent ? storedCursorStack : [];
  const baselineTop = paginationIsCurrent ? storedBaselineTop : null;
  if (paginationSignature !== filterSignature) {
    setPaginationSignature(filterSignature);
    setStoredCursorStack([]);
    setStoredBaselineTop(null);
  }

  const cursor = cursorStack.at(-1) ?? null;
  const filters = useMemo(
    () => ({
      kind: kind === "all" ? undefined : kind,
      status: status === "all" ? undefined : status,
      provider_dataset_id: exactProviderDatasetIdFilter,
      sync_scope: syncScopeFilter,
      operation_key: operationKeyFilter,
      load_batch_id: loadBatchId.trim() || undefined,
      parent_job_id: parentJobId.trim() || undefined,
      created_from: datetimeLocalIsoValue(createdFrom),
      created_to: datetimeLocalIsoValue(createdTo),
      page_size: PAGE_SIZE,
    }),
    [
      kind,
      status,
      exactProviderDatasetIdFilter,
      syncScopeFilter,
      operationKeyFilter,
      loadBatchId,
      parentJobId,
      createdFrom,
      createdTo,
    ],
  );

  const executions = usePipelineExecutions({ ...filters, cursor });
  // cursor 조사 중에만 head 폴링으로 "새 실행 N건"을 계산한다(설계 §1 — 조사 중
  // 목록 재정렬 방지, 1페이지 자동 갱신은 WS invalidation이 담당).
  const head = usePipelineExecutionsHead(filters, {
    enabled: cursorStack.length > 0,
  });

  const items = useMemo(
    () => executions.data?.data.items ?? [],
    [executions.data],
  );
  const rows = items;

  const newCount = useMemo(() => {
    if (cursorStack.length === 0 || !baselineTop) {
      return 0;
    }
    const headItems = head.data?.data.items ?? [];
    return headItems.filter((item) => {
      if (item.created_at !== baselineTop.createdAt) {
        return item.created_at > baselineTop.createdAt;
      }
      if (item.id !== baselineTop.id) {
        return item.id > baselineTop.id;
      }
      return item.kind > baselineTop.kind;
    }).length;
  }, [cursorStack.length, baselineTop, head.data]);
  const newCountLabel =
    newCount >= PAGE_SIZE ? `${PAGE_SIZE}+` : String(newCount);

  const nextCursor = executions.data?.meta.page?.next_cursor ?? null;

  const resetToFirstPage = () => {
    setStoredCursorStack([]);
    setStoredBaselineTop(null);
    void executions.refetch();
  };

  const goNextPage = () => {
    if (!nextCursor) {
      return;
    }
    if (cursorStack.length === 0) {
      const top = items[0];
      if (top) {
        setStoredBaselineTop({
          createdAt: top.created_at,
          kind: top.kind,
          id: top.id,
        });
      }
    }
    setStoredCursorStack((stack) => [...stack, nextCursor]);
  };

  const columns = useMemo<ColumnDef<PipelineExecutionRootRecord, unknown>[]>(
    () => [
      {
        id: "kind",
        header: "종류",
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="text-xs font-medium">
              {executionKindLabel(row.original.kind)}
            </span>
            {row.original.linked_job_count > 1 ? (
              <span className="text-2xs text-text-secondary tabular-nums">
                작업 {row.original.linked_job_count}
              </span>
            ) : null}
          </div>
        ),
      },
      {
        id: "target",
        header: "대상",
        cell: ({ row }) => {
          const identity = rootIdentityLabel(row.original);
          return (
            <div className="min-w-0">
              <p className="truncate font-medium">{identity.primary}</p>
              <p className="truncate text-xs text-text-secondary">
                {identity.secondary || shortId(row.original.id)}
              </p>
              {row.original.provider_datasets.length > 0 ? (
                <ul
                  className="mt-1 space-y-0.5 text-xs"
                  data-testid={`pipeline-pairs-${row.original.id}`}
                >
                  {row.original.provider_datasets.map((pair) => (
                    <li
                      className="flex flex-wrap items-center gap-1"
                      key={pair.operation_member_id}
                    >
                      <span className="font-mono">
                        {pair.provider}/{pair.dataset_key}
                        {pair.sync_scope ? ` · ${pair.sync_scope}` : ""}
                        {pair.operation_key ? ` · ${pair.operation_key}` : ""}
                      </span>
                      <StatusBadge status={pair.status} />
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          );
        },
      },
      {
        id: "status",
        header: "상태",
        cell: ({ row }) => (
          <div className="flex flex-col gap-1">
            <span className="flex items-center gap-1 text-xs">
              {row.original.kind === "update_request" ? "요청" : "root"}
              <StatusBadge status={row.original.status} />
            </span>
            {row.original.kind === "update_request" ? (
              <span className="flex items-center gap-1 text-xs">
                대표 작업
                <StatusBadge status={row.original.projected_job.status} />
              </span>
            ) : null}
            {row.original.cancellation ? (
              <StatusBadge
                label={`취소 ${statusLabel(row.original.cancellation.status)}`}
                status={row.original.cancellation.status}
              />
            ) : null}
          </div>
        ),
      },
      {
        id: "progress",
        header: "진행",
        cell: ({ row }) => (
          <div className="flex flex-col items-start gap-1">
            <span className="text-sm">{rootProgressLabel(row.original)}</span>
            <Button
              aria-label={`대표 작업 ${shortId(row.original.projected_job.id)} 상세 열기`}
              data-detail-url={row.original.projected_job.detail_url}
              size="sm"
              type="button"
              variant="ghost"
              onClick={(event) => {
                event.stopPropagation();
                onSelectExecution(
                  "import_job",
                  row.original.projected_job.id,
                  row.original.id,
                );
              }}
            >
              대표 작업 {shortId(row.original.projected_job.id)}
            </Button>
          </div>
        ),
      },
      {
        id: "created_at",
        header: "생성",
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-text-secondary">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        id: "dagster",
        header: "Dagster run",
        cell: ({ row }) => {
          const runId =
            row.original.dagster_run_id ??
            row.original.projected_job?.dagster_run_id;
          return runId ? (
            <div className="flex flex-col items-start gap-1">
              <EntityLink id={runId} kind="dagsterRun" newTab>
                {shortId(runId, 8)}
              </EntityLink>
              {(row.original.dagster_run_status ??
              row.original.projected_job.dagster_run_status) ? (
                <StatusBadge
                  status={
                    row.original.dagster_run_status ??
                    row.original.projected_job.dagster_run_status ??
                    "unknown"
                  }
                />
              ) : null}
            </div>
          ) : (
            <span className="text-text-tertiary">{NULL_GLYPH}</span>
          );
        },
      },
    ],
    [onSelectExecution],
  );

  return {
    columns,
    createdFrom,
    createdTo,
    cursorStack,
    executions,
    goNextPage,
    kind,
    loadBatchId,
    newCount,
    newCountLabel,
    nextCursor,
    onSelectExecution,
    onUrlChange,
    parentJobId,
    providerDatasetId,
    providerDatasetIdFilter,
    operationKey,
    resetToFirstPage,
    rows,
    selectedExecutionId,
    setDrafts,
    setStoredBaselineTop,
    setStoredCursorStack,
    status,
    syncScope,
  };
}

/**
 * 실행 목록 필터 막대.
 *
 * `ExecutionTimelineView`에서 떼어냈다 — T-VN-33이 provider dataset ID·sync_scope·
 * operation_key 필터를 더하면서 그 컴포넌트가 300줄 임계를 넘었고 `react-doctor`
 * 게이트가 red가 됐다. 필터는 표시 상태를 갖지 않고 controller 값만 읽으므로
 * 경계가 깨끗하다.
 */
function ExecutionTimelineFilters({
  createdFrom,
  createdTo,
  kind,
  onUrlChange,
  operationKey,
  providerDatasetId,
  providerDatasetIdFilter,
  setDrafts,
  setStoredBaselineTop,
  setStoredCursorStack,
  status,
  syncScope,
}: Pick<
  ReturnType<typeof useExecutionTimelineController>,
  | "createdFrom"
  | "createdTo"
  | "kind"
  | "onUrlChange"
  | "operationKey"
  | "providerDatasetId"
  | "providerDatasetIdFilter"
  | "setDrafts"
  | "setStoredBaselineTop"
  | "setStoredCursorStack"
  | "status"
  | "syncScope"
>) {
  return (
        <FilterBar>
          <FilterField label="종류">
            <NativeSelect
              aria-label="실행 종류"
              value={kind}
              onChange={(event) => {
                const value = event.target.value as ExecutionKind | "all";
                setStoredCursorStack([]);
                setStoredBaselineTop(null);
                onUrlChange({ kind: value === "all" ? null : value });
              }}
            >
              {KIND_OPTIONS.map((value) => (
                <NativeSelectOption key={value} value={value}>
                  {value === "all" ? "전체" : executionKindLabel(value)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterField label="상태">
            <NativeSelect
              aria-label="실행 상태"
              value={status}
              onChange={(event) => {
                const value = event.target.value as ExecutionStatus | "all";
                setStoredCursorStack([]);
                setStoredBaselineTop(null);
                onUrlChange({ status: value === "all" ? null : value });
              }}
            >
              {STATUS_OPTIONS.map((value) => (
                <NativeSelectOption key={value} value={value}>
                  {value === "all" ? "전체" : value}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterField label="provider dataset ID">
            <Input
              aria-label="provider dataset ID 필터"
              inputMode="numeric"
              min="1"
              placeholder="예: 42"
              type="number"
              value={providerDatasetId}
              onBlur={() =>
                setDrafts((current) => ({
                  ...current,
                  providerDatasetId: null,
                }))
              }
              onChange={(event) => {
                const value = event.target.value;
                setDrafts((current) => ({
                  ...current,
                  providerDatasetId: value,
                }));
                setStoredCursorStack([]);
                setStoredBaselineTop(null);
                onUrlChange(
                  { provider_dataset_id: value.trim() || null },
                  "replace",
                );
              }}
              onFocus={() =>
                setDrafts((current) => ({
                  ...current,
                  providerDatasetId,
                }))
              }
            />
          </FilterField>
          <FilterField
            hint={
              <span id="timeline-scope-prerequisite">
                {providerDatasetIdFilter
                  ? "선택한 provider dataset 안의 scope로 좁힙니다."
                  : "provider dataset ID를 먼저 입력하세요."}
              </span>
            }
            label="sync scope"
          >
            <Input
              aria-describedby="timeline-scope-prerequisite"
              aria-label="sync scope 필터"
              disabled={!providerDatasetIdFilter}
              placeholder="예: target_grids"
              value={syncScope}
              onBlur={() =>
                setDrafts((current) => ({ ...current, syncScope: null }))
              }
              onChange={(event) => {
                const value = event.target.value;
                setDrafts((current) => ({ ...current, syncScope: value }));
                setStoredCursorStack([]);
                setStoredBaselineTop(null);
                onUrlChange({ sync_scope: value.trim() || null }, "replace");
              }}
              onFocus={() =>
                setDrafts((current) => ({ ...current, syncScope }))
              }
            />
          </FilterField>
          <FilterField
            hint={
              <span id="timeline-operation-prerequisite">
                {!providerDatasetIdFilter || !syncScope.trim()
                  ? "provider dataset ID와 sync scope를 먼저 입력하세요."
                  : "같은 dataset/scope의 operation으로 좁힙니다."}
              </span>
            }
            label="operation key"
          >
            <Input
              aria-describedby="timeline-operation-prerequisite"
              aria-label="operation key 필터"
              disabled={!providerDatasetIdFilter || !syncScope.trim()}
              placeholder="예: refresh_targeted"
              value={operationKey}
              onBlur={() =>
                setDrafts((current) => ({ ...current, operationKey: null }))
              }
              onChange={(event) => {
                const value = event.target.value;
                setDrafts((current) => ({ ...current, operationKey: value }));
                setStoredCursorStack([]);
                setStoredBaselineTop(null);
                onUrlChange(
                  { operation_key: value.trim() || null },
                  "replace",
                );
              }}
              onFocus={() =>
                setDrafts((current) => ({ ...current, operationKey }))
              }
            />
          </FilterField>
          <FilterField label="시작일">
            <Input
              aria-label="생성 시작일"
              type="datetime-local"
              value={createdFrom}
              onChange={(event) => {
                setStoredCursorStack([]);
                setStoredBaselineTop(null);
                onUrlChange(
                  { created_from: event.target.value || null },
                  "replace",
                );
              }}
            />
          </FilterField>
          <FilterField label="종료일">
            <Input
              aria-label="생성 종료일"
              type="datetime-local"
              value={createdTo}
              onChange={(event) => {
                setStoredCursorStack([]);
                setStoredBaselineTop(null);
                onUrlChange(
                  { created_to: event.target.value || null },
                  "replace",
                );
              }}
            />
          </FilterField>
        </FilterBar>
  );
}

function ExecutionTimelineView({
  columns,
  createdFrom,
  createdTo,
  cursorStack,
  executions,
  goNextPage,
  kind,
  loadBatchId,
  newCount,
  newCountLabel,
  nextCursor,
  onSelectExecution,
  onUrlChange,
  parentJobId,
  providerDatasetId,
  providerDatasetIdFilter,
  operationKey,
  resetToFirstPage,
  rows,
  selectedExecutionId,
  setDrafts,
  setStoredBaselineTop,
  setStoredCursorStack,
  status,
  syncScope,
}: ReturnType<typeof useExecutionTimelineController>) {
  return (
    <SectionCard
      actions={
        newCount > 0 ? (
          <Button
            aria-label={`새 실행 ${newCountLabel}건 반영`}
            size="sm"
            type="button"
            variant="outline"
            onClick={resetToFirstPage}
          >
            새 실행 {newCountLabel}건 — 첫 페이지로
          </Button>
        ) : undefined
      }
      description="request branch·standalone root 단위 통합 목록 — 하위 작업은 별도 행으로 나오지 않습니다."
      title="실행 타임라인"
    >
      <ExecutionTimelineFilters
        createdFrom={createdFrom}
        createdTo={createdTo}
        kind={kind}
        onUrlChange={onUrlChange}
        operationKey={operationKey}
        providerDatasetId={providerDatasetId}
        providerDatasetIdFilter={providerDatasetIdFilter}
        setDrafts={setDrafts}
        setStoredBaselineTop={setStoredBaselineTop}
        setStoredCursorStack={setStoredCursorStack}
        status={status}
        syncScope={syncScope}
      />

      {loadBatchId.trim() || parentJobId.trim() ? (
        <div className="flex flex-wrap items-center gap-2">
          {loadBatchId.trim() ? (
            <span className={ACTIVE_FILTER_CHIP_CLASS}>
              배치 <span className="font-mono">{shortId(loadBatchId)}</span>
              <Button
                aria-label="배치 필터 지우기"
                size="icon-sm"
                type="button"
                variant="ghost"
                onClick={() => {
                  onUrlChange({ load_batch_id: null });
                }}
              >
                <XIcon />
              </Button>
            </span>
          ) : null}
          {parentJobId.trim() ? (
            <span className={ACTIVE_FILTER_CHIP_CLASS}>
              상위 작업 <span className="font-mono">{shortId(parentJobId)}</span>
              <Button
                aria-label="상위 작업 필터 지우기"
                size="icon-sm"
                type="button"
                variant="ghost"
                onClick={() => {
                  onUrlChange({ parent_job_id: null });
                }}
              >
                <XIcon />
              </Button>
            </span>
          ) : null}
          <span className="text-xs text-text-secondary">
            root 전체 구성 작업을 서버에서 cursor와 page limit 적용 전에
            필터링합니다.
          </span>
        </div>
      ) : null}

      <DataTable
        ariaLabel="실행 타임라인"
        columns={columns}
        data={rows}
        emptyState={{
          title: "조건에 맞는 실행이 없습니다.",
          description: "필터를 조정하거나 갱신 요청을 생성하세요.",
        }}
        error={executions.error}
        errorTitle="실행 목록을 불러오지 못했습니다"
        getRowId={(row) => `${row.kind}:${row.id}`}
        isError={executions.isError}
        isLoading={executions.isLoading}
        isRowActive={(row) =>
          selectedExecutionId !== null &&
          (row.id === selectedExecutionId ||
            row.projected_job?.id === selectedExecutionId)
        }
        rowIdentity={(row) =>
          JSON.stringify([row.created_at, row.id, row.kind])
        }
        rowTestId={(row) => `pipeline-execution-row-${row.id}`}
        onRetry={() => executions.refetch()}
        onRowClick={(row) => onSelectExecution(row.kind, row.id, row.id)}
      />

      <CursorPager
        ariaPrefix="실행 타임라인"
        hasNext={Boolean(nextCursor)}
        isFetching={executions.isFetching}
        isFirst={cursorStack.length === 0}
        summary={`page ${cursorStack.length + 1} · 이 페이지 ${rows.length}행`}
        onFirst={resetToFirstPage}
        onNext={goNextPage}
      />
    </SectionCard>
  );
}

export function ExecutionTimeline({
  initialFilters,
  initialLoadBatchId,
  initialParentJobId,
  selectedExecutionId,
  onSelectExecution,
  onUrlChange,
}: {
  initialFilters: TimelineFilters;
  initialLoadBatchId?: string;
  initialParentJobId?: string;
  selectedExecutionId: string | null;
  onSelectExecution: (
    kind: ExecutionKind,
    id: string,
    focusExecutionId?: string,
  ) => void;
  onUrlChange: (updates: TimelineUrlUpdates, mode?: "push" | "replace") => void;
}) {
  const controller = useExecutionTimelineController({ initialFilters, initialLoadBatchId, initialParentJobId, selectedExecutionId, onSelectExecution, onUrlChange });
  return <ExecutionTimelineView {...controller} />;
}
