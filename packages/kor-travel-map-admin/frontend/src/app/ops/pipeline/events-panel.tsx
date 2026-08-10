"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import {
  type ExecutionKind,
  type JobEventLevel,
  type PipelineJobEventRecord,
  usePipelineDagsterRunDetail,
  usePipelineDagsterRuns,
  usePipelineEvents,
} from "@/api/pipeline";
import { EntityLink } from "@/components/entity-link";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { withOccurrenceKeys } from "@/lib/occurrence-key";

const LEVEL_OPTIONS: Array<JobEventLevel | "all"> = [
  "all",
  "critical",
  "error",
  "warning",
  "info",
  "debug",
];
const PAGE_SIZE = 50;

function positiveInteger(value: string): number | undefined {
  const parsed = Number(value.trim());
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
}

export function PipelineEventsPanel({
  onSelectExecution,
  onUrlChange,
  providerDatasetId,
  syncScope,
  operationKey,
}: {
  onSelectExecution: (kind: ExecutionKind, id: string) => void;
  onUrlChange: (
    updates: Record<string, string | null>,
    mode?: "push" | "replace",
  ) => void;
  providerDatasetId: string;
  syncScope: string;
  /** membership identity의 나머지 한 축. 비우면 그 dataset/scope의 모든 operation. */
  operationKey: string;
}) {
  const [level, setLevel] = useState<JobEventLevel | "all">("all");
  const [jobId, setJobId] = useState("");
  const filterSignature = JSON.stringify([
    level,
    providerDatasetId,
    syncScope,
    operationKey,
    jobId,
  ]);
  const [paginationSignature, setPaginationSignature] =
    useState(filterSignature);
  const [cursorStack, setCursorStack] = useState<string[]>([]);

  // URL Back/Forward와 same-route pushState가 필터를 바꾸면 이전 filter의
  // opaque cursor를 같은 렌더에서 폐기한다. 서버 cursor fingerprint에 기대기
  // 전에 UI도 잘못된 재사용을 만들지 않는다.
  const paginationIsCurrent = paginationSignature === filterSignature;
  const activeCursorStack = paginationIsCurrent ? cursorStack : [];
  if (!paginationIsCurrent) {
    setPaginationSignature(filterSignature);
    setCursorStack([]);
  }

  const cursor = activeCursorStack.at(-1) ?? null;
  const providerDatasetIdFilter = positiveInteger(providerDatasetId);
  const syncScopeFilter = syncScope.trim() || undefined;
  const operationKeyFilter = operationKey.trim() || undefined;
  const events = usePipelineEvents({
    level: level === "all" ? undefined : level,
    provider_dataset_id: providerDatasetIdFilter,
    sync_scope: providerDatasetIdFilter ? syncScopeFilter : undefined,
    operation_key: providerDatasetIdFilter ? operationKeyFilter : undefined,
    job_id: jobId.trim() || undefined,
    page_size: PAGE_SIZE,
    cursor,
  });

  const items = events.data?.data.items ?? [];
  const nextCursor = events.data?.meta.page?.next_cursor ?? null;

  const resetPage = () => setCursorStack([]);

  const columns = useMemo<ColumnDef<PipelineJobEventRecord, unknown>[]>(
    () => [
      {
        id: "occurred_at",
        header: "발생",
        cell: ({ row }) => (
          <span className="text-sm whitespace-nowrap">
            {formatDateTime(row.original.occurred_at)}
          </span>
        ),
      },
      {
        id: "level",
        header: "레벨",
        cell: ({ row }) => <StatusBadge status={row.original.level} />,
      },
      {
        id: "provider_dataset_id",
        header: "provider dataset ID",
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.provider_dataset_id ?? "-"}
          </span>
        ),
      },
      {
        // provider/dataset 자연키 컬럼은 T-VN-33에서 ID로 접혔지만 sync_scope는
        // ID가 아니라 membership identity의 **다른 축**이다. 이 컬럼이 없으면
        // scope로 좁힌 이벤트 화면에서 각 행이 어느 scope 것인지 알 수 없다.
        id: "sync_scope",
        header: "scope",
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.sync_scope ?? "-"}
          </span>
        ),
      },
      {
        // scope와 같은 이유다 — 여러 operation의 이벤트가 뒤섞인 전역 스트림에서
        // 각 행이 어느 membership 것인지 판별할 열이 하나도 없었다.
        id: "operation_key",
        header: "operation",
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.operation_key ?? "-"}
          </span>
        ),
      },
      {
        id: "message",
        header: "메시지",
        cell: ({ row }) => (
          <p className="line-clamp-2 max-w-96 text-sm">
            {row.original.message}
          </p>
        ),
      },
      {
        id: "job",
        header: "작업",
        cell: ({ row }) => (
          <Button
            aria-label={`작업 ${shortId(row.original.job_id)} 상세 열기`}
            size="sm"
            type="button"
            variant="ghost"
            onClick={() => onSelectExecution("import_job", row.original.job_id)}
          >
            <span className="font-mono">{shortId(row.original.job_id)}</span>
          </Button>
        ),
      },
      {
        id: "code",
        header: "코드",
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.code ?? "-"}</span>
        ),
      },
    ],
    [onSelectExecution],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>전역 job 이벤트</CardTitle>
        <CardDescription>
          어느 작업인지 모르는 상태에서 최근 error를 훑는 전역 스트림입니다.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <FilterBar>
          <FilterField label="레벨">
            <NativeSelect
              aria-label="이벤트 레벨 필터"
              value={level}
              onChange={(event) => {
                setLevel(event.target.value as JobEventLevel | "all");
                resetPage();
              }}
            >
              {LEVEL_OPTIONS.map((value) => (
                <NativeSelectOption key={value} value={value}>
                  {value === "all" ? "전체" : value}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterField label="provider dataset ID">
            <Input
              aria-label="이벤트 provider dataset ID 필터"
              inputMode="numeric"
              min="1"
              type="number"
              value={providerDatasetId}
              onChange={(event) => {
                resetPage();
                onUrlChange(
                  { provider_dataset_id: event.target.value.trim() || null },
                  "replace",
                );
              }}
            />
          </FilterField>
          <FilterField label="sync scope">
            <Input
              aria-label="이벤트 sync scope 필터"
              disabled={!providerDatasetIdFilter}
              value={syncScope}
              onChange={(event) => {
                resetPage();
                onUrlChange(
                  { sync_scope: event.target.value.trim() || null },
                  "replace",
                );
              }}
            />
          </FilterField>
          <FilterField label="operation">
            {/* 이 값은 URL에서 읽어 **쿼리에 그대로 적용**되는데 보여 주거나 지울
                컨트롤이 없었다. 딥링크로 들어온 운영자는 목록이 특정 operation으로
                좁혀져 있다는 사실을 모른 채 빈 목록을 "이벤트 없음"으로 오독한다.
                적용되는 필터는 화면에 있어야 한다. */}
            <Input
              aria-label="이벤트 operation 필터"
              disabled={!providerDatasetIdFilter}
              placeholder="operation_key"
              value={operationKey}
              onChange={(event) => {
                resetPage();
                onUrlChange(
                  { operation_key: event.target.value.trim() || null },
                  "replace",
                );
              }}
            />
          </FilterField>
          <FilterField label="작업 ID">
            <Input
              aria-label="이벤트 작업 ID 필터"
              placeholder="job_id (UUID)"
              value={jobId}
              onChange={(event) => {
                setJobId(event.target.value);
                resetPage();
              }}
            />
          </FilterField>
        </FilterBar>

        {events.isError ? (
          <Alert variant="destructive">
            <AlertTitle>이벤트 목록 호출 실패</AlertTitle>
            <AlertDescription>{events.error.message}</AlertDescription>
          </Alert>
        ) : null}

        <DataTable
          ariaLabel="전역 job 이벤트"
          columns={columns}
          data={items}
          emptyMessage="조건에 맞는 이벤트가 없습니다."
          getRowId={(row) => row.event_id}
          isLoading={events.isLoading}
          rowIdentity={(row) =>
            JSON.stringify([row.occurred_at, row.event_id])
          }
        />

        <CursorPager
          ariaPrefix="job 이벤트"
          hasNext={Boolean(nextCursor)}
          isFetching={events.isFetching}
          isFirst={activeCursorStack.length === 0}
          summary={`page ${activeCursorStack.length + 1} · 이 페이지 ${items.length}건`}
          onFirst={resetPage}
          onNext={() =>
            nextCursor
              ? setCursorStack((stack) => [...stack, nextCursor])
              : undefined
          }
        />
      </CardContent>
    </Card>
  );
}

/** C3c 정본(#690) — `GET /ops/pipeline/dagster-runs/{run_id}` 소비 상세. */
function DagsterRunDetail({ runId }: { runId: string }) {
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const after = cursorStack.at(-1) ?? null;
  const detail = usePipelineDagsterRunDetail(runId, {
    page_size: 50,
    after,
  });
  const data = detail.data?.data;
  return (
    <div
      className="mt-2 rounded-md bg-surface-subtle p-3"
      data-testid={`pipeline-dagster-run-detail-${runId}`}
    >
      {detail.isLoading ? (
        <p className="text-sm text-muted-foreground">run 상세를 불러오는 중…</p>
      ) : null}
      {detail.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Dagster run 상세 호출 실패</AlertTitle>
          <AlertDescription className="break-all">
            {detail.error.message}
          </AlertDescription>
        </Alert>
      ) : null}
      {data ? (
        <div className="space-y-2 text-sm">
          {data.failure_reason ? (
            <Alert variant="destructive">
              <AlertTitle>실패 원인</AlertTitle>
              <AlertDescription className="break-all">
                {data.failure_reason}
              </AlertDescription>
            </Alert>
          ) : null}
          <ul className="space-y-1">
            {withOccurrenceKeys(data.events ?? [], (event) =>
              JSON.stringify([runId, event]),
            ).map(({ key, value: event }) => (
              <li className="flex flex-wrap items-center gap-2" key={key}>
                <span className="font-mono text-xs text-muted-foreground">
                  {event.level ?? event.event_type}
                </span>
                <span className="break-all">{event.message ?? "-"}</span>
              </li>
            ))}
          </ul>
          {data.event_has_more ? (
            <Button
              disabled={!data.event_cursor || detail.isFetching}
              size="sm"
              type="button"
              variant="outline"
              onClick={() =>
                data.event_cursor
                  ? setCursorStack((stack) => [...stack, data.event_cursor as string])
                  : undefined
              }
            >
              다음 이벤트 페이지
            </Button>
          ) : null}
          {cursorStack.length > 0 ? (
            <Button
              size="sm"
              type="button"
              variant="ghost"
              onClick={() => setCursorStack([])}
            >
              첫 이벤트 페이지
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function DagsterRunsPanel() {
  const runs = usePipelineDagsterRuns(20);
  const data = runs.data?.data;
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  return (
    <Card data-testid="pipeline-dagster-runs-panel">
      <CardHeader>
        <CardTitle>Dagster 실행 (보조)</CardTitle>
        <CardDescription>
          적재 작업을 만들지 못하고 죽은 순수 Dagster 실패를 확인하는 보조
          패널입니다 — 상세는 Dagster UI에서 봅니다.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {runs.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Dagster run 호출 실패</AlertTitle>
            <AlertDescription>{runs.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {data && data.status !== "ok" ? (
          <Alert
            variant={data.status === "unavailable" ? "destructive" : "default"}
          >
            <AlertTitle>
              {data.status === "unavailable"
                ? "Dagster 연결 불가"
                : "Dagster 상태 확인 필요"}
            </AlertTitle>
            <AlertDescription>
              {(data.errors ?? []).length > 0
                ? (data.errors ?? []).join(" / ")
                : "Dagster webserver 상태를 확인하세요."}
            </AlertDescription>
          </Alert>
        ) : null}
        {data && (data.runs ?? []).length === 0 && data.status === "ok" ? (
          <p className="text-sm text-muted-foreground">최근 run이 없습니다.</p>
        ) : null}
        {data && (data.runs ?? []).length > 0 ? (
          <ul className="space-y-1.5">
            {(data.runs ?? []).map((run) => (
              <li className="text-sm" key={run.run_id}>
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={run.status} />
                  <span className="truncate">{run.job_name ?? "-"}</span>
                  <EntityLink id={run.run_id} kind="dagsterRun" newTab>
                    {shortId(run.run_id, 8)}
                  </EntityLink>
                  <span className="text-xs text-muted-foreground">
                    {run.start_time
                      ? formatDateTime(
                          new Date(run.start_time * 1000).toISOString(),
                        )
                      : "-"}
                  </span>
                  <Button
                    aria-label={`run ${shortId(run.run_id, 8)} 상세 ${
                      expandedRunId === run.run_id ? "닫기" : "열기"
                    }`}
                    size="sm"
                    type="button"
                    variant="ghost"
                    onClick={() =>
                      setExpandedRunId((current) =>
                        current === run.run_id ? null : run.run_id,
                      )
                    }
                  >
                    {expandedRunId === run.run_id ? "상세 닫기" : "상세"}
                  </Button>
                </div>
                {expandedRunId === run.run_id ? (
                  <DagsterRunDetail runId={run.run_id} />
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
