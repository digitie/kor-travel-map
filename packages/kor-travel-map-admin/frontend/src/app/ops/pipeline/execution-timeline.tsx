"use client";

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
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { CursorPager } from "@/components/pagination-bar";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { formatDateTime, shortId } from "@/lib/format";

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

export interface TimelineFilters {
  kind?: ExecutionKind;
  status?: ExecutionStatus;
  provider?: string;
  datasetKey?: string;
  syncScope?: string;
  createdFrom?: string;
  createdTo?: string;
}

type TimelineUrlUpdates = Record<string, string | null>;

function padDatePart(value: number): string {
  return String(value).padStart(2, "0");
}

export function datetimeLocalValue(value: string | undefined): string {
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

export function datetimeLocalIsoValue(value: string): string | undefined {
  if (!value) {
    return undefined;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
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
  const kind = initialFilters.kind ?? "all";
  const status = initialFilters.status ?? "all";
  const provider = initialFilters.provider ?? "";
  const datasetKey = initialFilters.datasetKey ?? "";
  const syncScope = initialFilters.syncScope ?? "";
  const createdFrom = datetimeLocalValue(initialFilters.createdFrom);
  const createdTo = datetimeLocalValue(initialFilters.createdTo);
  const loadBatchId = initialLoadBatchId ?? "";
  const parentJobId = initialParentJobId ?? "";
  const filterSignature = JSON.stringify([
    kind,
    status,
    provider,
    datasetKey,
    syncScope,
    createdFrom,
    createdTo,
    loadBatchId,
    parentJobId,
  ]);
  const [paginationSignature, setPaginationSignature] =
    useState(filterSignature);
  const [storedCursorStack, setCursorStack] = useState<string[]>([]);
  const [storedBaselineTop, setBaselineTop] = useState<{
    createdAt: string;
    kind: ExecutionKind;
    id: string;
  } | null>(null);
  const paginationIsCurrent = paginationSignature === filterSignature;
  const cursorStack = paginationIsCurrent ? storedCursorStack : [];
  const baselineTop = paginationIsCurrent ? storedBaselineTop : null;
  if (paginationSignature !== filterSignature) {
    setPaginationSignature(filterSignature);
    setCursorStack([]);
    setBaselineTop(null);
  }

  const cursor = cursorStack.at(-1) ?? null;
  const filters = useMemo(
    () => ({
      kind: kind === "all" ? undefined : kind,
      status: status === "all" ? undefined : status,
      provider: provider.trim() || undefined,
      dataset_key: datasetKey.trim() || undefined,
      sync_scope: syncScope.trim() || undefined,
      created_from: datetimeLocalIsoValue(createdFrom),
      created_to: datetimeLocalIsoValue(createdTo),
      page_size: PAGE_SIZE,
    }),
    [kind, status, provider, datasetKey, syncScope, createdFrom, createdTo],
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
  const rows = useMemo(() => {
    const batch = loadBatchId.trim();
    const parent = parentJobId.trim();
    if (!batch && !parent) {
      return items;
    }
    // load_batch_id/parent_job_id 딥링크 승계 — root 목록에 서버 필터가 없어
    // 로드된 행의 대표 작업(projected_job)에서만 좁힌다(클라이언트 필터).
    return items.filter((root) => {
      const projected = root.projected_job;
      const batchOk = !batch || projected?.load_batch_id === batch;
      const parentOk = !parent || projected?.parent_job_id === parent;
      return batchOk && parentOk;
    });
  }, [items, loadBatchId, parentJobId]);

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
    setCursorStack([]);
    setBaselineTop(null);
    void executions.refetch();
  };

  const goNextPage = () => {
    if (!nextCursor) {
      return;
    }
    if (cursorStack.length === 0) {
      const top = items[0];
      if (top) {
        setBaselineTop({
          createdAt: top.created_at,
          kind: top.kind,
          id: top.id,
        });
      }
    }
    setCursorStack((stack) => [...stack, nextCursor]);
  };

  const columns = useMemo<ColumnDef<PipelineExecutionRootRecord, unknown>[]>(
    () => [
      {
        id: "kind",
        header: "종류",
        cell: ({ row }) => (
          <div className="flex flex-wrap items-center gap-1">
            <Badge variant="outline">
              {executionKindLabel(row.original.kind)}
            </Badge>
            {row.original.linked_job_count > 1 ? (
              <Badge variant="secondary">
                작업 {row.original.linked_job_count}
              </Badge>
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
              <p className="truncate text-xs text-muted-foreground">
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
              <Badge variant="destructive">
                취소 {row.original.cancellation.status}
              </Badge>
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
          <span className="text-sm whitespace-nowrap">
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
            <span className="text-muted-foreground">-</span>
          );
        },
      },
    ],
    [onSelectExecution],
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>실행 타임라인</CardTitle>
            <CardDescription>
              request branch·standalone root 단위 통합 목록 — 하위 작업은 별도
              행으로 나오지 않습니다.
            </CardDescription>
          </div>
          {newCount > 0 ? (
            <Button
              aria-label={`새 실행 ${newCountLabel}건 반영`}
              size="sm"
              type="button"
              variant="outline"
              onClick={resetToFirstPage}
            >
              새 실행 {newCountLabel}건 — 첫 페이지로
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <FilterBar>
          <FilterField label="종류">
            <NativeSelect
              aria-label="실행 종류"
              value={kind}
              onChange={(event) => {
                const value = event.target.value as ExecutionKind | "all";
                setCursorStack([]);
                setBaselineTop(null);
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
                setCursorStack([]);
                setBaselineTop(null);
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
          <FilterField label="provider">
            <Input
              aria-label="provider 필터"
              placeholder="예: python-kma-api"
              value={provider}
              onChange={(event) => {
                setCursorStack([]);
                setBaselineTop(null);
                onUrlChange(
                  { provider: event.target.value.trim() || null },
                  "replace",
                );
              }}
            />
          </FilterField>
          <FilterField label="데이터셋">
            <Input
              aria-label="데이터셋 필터"
              placeholder="예: kma_short_forecast"
              value={datasetKey}
              onChange={(event) => {
                setCursorStack([]);
                setBaselineTop(null);
                onUrlChange(
                  { dataset_key: event.target.value.trim() || null },
                  "replace",
                );
              }}
            />
          </FilterField>
          <FilterField label="sync scope">
            <Input
              aria-label="sync scope 필터"
              placeholder="예: target_grids"
              value={syncScope}
              onChange={(event) => {
                setCursorStack([]);
                setBaselineTop(null);
                onUrlChange(
                  { sync_scope: event.target.value.trim() || null },
                  "replace",
                );
              }}
            />
          </FilterField>
          <FilterField label="시작일">
            <Input
              aria-label="생성 시작일"
              type="datetime-local"
              value={createdFrom}
              onChange={(event) => {
                setCursorStack([]);
                setBaselineTop(null);
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
                setCursorStack([]);
                setBaselineTop(null);
                onUrlChange(
                  { created_to: event.target.value || null },
                  "replace",
                );
              }}
            />
          </FilterField>
        </FilterBar>

        {loadBatchId.trim() || parentJobId.trim() ? (
          <div className="flex flex-wrap items-center gap-2">
            {loadBatchId.trim() ? (
              <Badge variant="secondary">
                배치 {shortId(loadBatchId)}
                <button
                  aria-label="배치 필터 지우기"
                  className="ml-1"
                  type="button"
                  onClick={() => {
                    onUrlChange({ load_batch_id: null });
                  }}
                >
                  <XIcon className="size-3" />
                </button>
              </Badge>
            ) : null}
            {parentJobId.trim() ? (
              <Badge variant="secondary">
                상위 작업 {shortId(parentJobId)}
                <button
                  aria-label="상위 작업 필터 지우기"
                  className="ml-1"
                  type="button"
                  onClick={() => {
                    onUrlChange({ parent_job_id: null });
                  }}
                >
                  <XIcon className="size-3" />
                </button>
              </Badge>
            ) : null}
            <span className="text-xs text-muted-foreground">
              로드된 root의 대표 작업에서만 좁히는 클라이언트 필터입니다 — 다음
              페이지로 추가 탐색하세요.
            </span>
          </div>
        ) : null}

        {executions.isError ? (
          <Alert variant="destructive">
            <AlertTitle>실행 목록 호출 실패</AlertTitle>
            <AlertDescription>{executions.error.message}</AlertDescription>
          </Alert>
        ) : null}

        <DataTable
          ariaLabel="실행 타임라인"
          columns={columns}
          data={rows}
          emptyMessage="조건에 맞는 실행이 없습니다. 필터를 조정하거나 갱신 요청을 생성하세요."
          getRowId={(row) => `${row.kind}:${row.id}`}
          isLoading={executions.isLoading}
          isRowActive={(row) =>
            selectedExecutionId !== null &&
            (row.id === selectedExecutionId ||
              row.projected_job?.id === selectedExecutionId)
          }
          rowTestId={(row) => `pipeline-execution-row-${row.id}`}
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
      </CardContent>
    </Card>
  );
}
