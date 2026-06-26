"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangleIcon,
  ArrowUpRightIcon,
  RefreshCwIcon,
  SearchIcon,
} from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";

import { useOpsLiveInvalidation } from "@/api/live";
import {
  useApiCallLogs,
  useImportJobEvents,
  useSystemLogs,
  type ImportJobEventLevel,
  type SystemLogLevel,
} from "@/api/ops";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDateTime, shortId } from "@/lib/format";

const LEVELS: Array<SystemLogLevel | "all"> = [
  "critical",
  "error",
  "warning",
  "info",
  "debug",
  "all",
];
const EVENT_LEVELS: Array<ImportJobEventLevel | "all"> = [
  "critical",
  "error",
  "warning",
  "info",
  "debug",
  "all",
];
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;

export function LogsClient() {
  const [systemQ, setSystemQ] = useState("");
  const deferredSystemQ = useDeferredValue(systemQ.trim());
  const [systemLevel, setSystemLevel] = useState<SystemLogLevel | "all">("all");
  const [systemSource, setSystemSource] = useState("");
  const [systemCursor, setSystemCursor] = useState<string | null>(null);
  const [systemPageIndex, setSystemPageIndex] = useState(1);

  const [apiMethod, setApiMethod] = useState("");
  const [apiPath, setApiPath] = useState("");
  const [apiMinStatus, setApiMinStatus] = useState("");
  const [apiCursor, setApiCursor] = useState<string | null>(null);
  const [apiPageIndex, setApiPageIndex] = useState(1);

  const [eventJobId, setEventJobId] = useState("");
  const [eventLevel, setEventLevel] = useState<ImportJobEventLevel | "all">("all");
  const [eventProvider, setEventProvider] = useState("");
  const [eventDatasetKey, setEventDatasetKey] = useState("");
  const [eventCursor, setEventCursor] = useState<string | null>(null);
  const [eventPageIndex, setEventPageIndex] = useState(1);

  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>(100);

  const systemParams = useMemo(
    () => ({
      level: systemLevel === "all" ? undefined : systemLevel,
      source: systemSource.trim().length > 0 ? systemSource.trim() : undefined,
      q: deferredSystemQ.length > 0 ? deferredSystemQ : undefined,
      page_size: pageSize,
      cursor: systemCursor ?? undefined,
    }),
    [deferredSystemQ, pageSize, systemCursor, systemLevel, systemSource],
  );
  const apiParams = useMemo(
    () => ({
      method: apiMethod.trim().length > 0 ? apiMethod.trim().toUpperCase() : undefined,
      path: apiPath.trim().length > 0 ? apiPath.trim() : undefined,
      min_status:
        apiMinStatus.trim().length > 0 && Number.isFinite(Number(apiMinStatus))
        ? Number(apiMinStatus)
        : undefined,
      page_size: pageSize,
      cursor: apiCursor ?? undefined,
    }),
    [apiCursor, apiMethod, apiMinStatus, apiPath, pageSize],
  );
  const eventParams = useMemo(
    () => ({
      job_id: eventJobId.trim().length > 0 ? eventJobId.trim() : undefined,
      level: eventLevel === "all" ? undefined : eventLevel,
      provider:
        eventProvider.trim().length > 0 ? eventProvider.trim() : undefined,
      dataset_key:
        eventDatasetKey.trim().length > 0
          ? eventDatasetKey.trim()
          : undefined,
      page_size: pageSize,
      cursor: eventCursor ?? undefined,
    }),
    [
      eventCursor,
      eventDatasetKey,
      eventJobId,
      eventLevel,
      eventProvider,
      pageSize,
    ],
  );

  const systemLogs = useSystemLogs(systemParams);
  const apiLogs = useApiCallLogs(apiParams);
  const jobEvents = useImportJobEvents(eventParams);
  const live = useOpsLiveInvalidation({ topics: ["import_jobs"] });
  const systemItems = systemLogs.data?.data.items ?? [];
  const apiItems = apiLogs.data?.data.items ?? [];
  const eventItems = jobEvents.data?.data.items ?? [];
  const resetSystemPage = () => {
    setSystemCursor(null);
    setSystemPageIndex(1);
  };
  const resetApiPage = () => {
    setApiCursor(null);
    setApiPageIndex(1);
  };
  const resetEventPage = () => {
    setEventCursor(null);
    setEventPageIndex(1);
  };
  const nextSystemPage = () => {
    const nextCursor = systemLogs.data?.meta.page?.next_cursor ?? null;
    if (!nextCursor) return;
    setSystemCursor(nextCursor);
    setSystemPageIndex((page) => page + 1);
  };
  const nextApiPage = () => {
    const nextCursor = apiLogs.data?.meta.page?.next_cursor ?? null;
    if (!nextCursor) return;
    setApiCursor(nextCursor);
    setApiPageIndex((page) => page + 1);
  };
  const nextEventPage = () => {
    const nextCursor = jobEvents.data?.meta.page?.next_cursor ?? null;
    if (!nextCursor) return;
    setEventCursor(nextCursor);
    setEventPageIndex((page) => page + 1);
  };
  const refreshAll = () => {
    void systemLogs.refetch();
    void apiLogs.refetch();
    void jobEvents.refetch();
  };

  type SystemLogRow = (typeof systemItems)[number];
  type ApiLogRow = (typeof apiItems)[number];
  type JobEventRow = (typeof eventItems)[number];

  // 세 로그 테이블은 모두 keyset cursor 목록(next_cursor 페이징) — 서버가 정렬을 소유하므로
  // 모든 accessor 컬럼의 client 정렬을 끈다(#502: manual 기본에서 client 정렬은 현재 페이지만
  // 재배열해 오해를 줌).
  const systemColumns = useMemo<ColumnDef<SystemLogRow, unknown>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: "created",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        accessorKey: "level",
        header: "level",
        enableSorting: false,
        cell: ({ row }) => <StatusBadge status={row.original.level} />,
      },
      { accessorKey: "source", header: "source", enableSorting: false },
      { accessorKey: "event", header: "event", enableSorting: false },
      {
        id: "message",
        header: "message",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="max-w-96">
            <div className="line-clamp-2">{row.original.message}</div>
          </div>
        ),
      },
      {
        id: "request",
        header: "request",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.request_id)}
          </span>
        ),
      },
    ],
    [],
  );

  const apiColumns = useMemo<ColumnDef<ApiLogRow, unknown>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: "created",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        accessorKey: "method",
        header: "method",
        enableSorting: false,
        cell: ({ row }) => <Badge variant="outline">{row.original.method}</Badge>,
      },
      {
        accessorKey: "status_code",
        header: "status",
        enableSorting: false,
        cell: ({ row }) => (
          <StatusBadge status={String(row.original.status_code)} />
        ),
      },
      {
        accessorKey: "duration_ms",
        header: "duration",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono">{row.original.duration_ms}ms</span>
        ),
      },
      {
        id: "path",
        header: "path",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-96 break-all font-mono text-xs">
            {row.original.path}
          </span>
        ),
      },
      {
        id: "request",
        header: "request",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.request_id)}
          </span>
        ),
      },
      {
        accessorKey: "error_code",
        header: "error",
        enableSorting: false,
        cell: ({ row }) => row.original.error_code ?? "-",
      },
    ],
    [],
  );

  const eventColumns = useMemo<ColumnDef<JobEventRow, unknown>[]>(
    () => [
      {
        accessorKey: "occurred_at",
        header: "occurred",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.occurred_at)}
          </span>
        ),
      },
      {
        accessorKey: "level",
        header: "level",
        enableSorting: false,
        cell: ({ row }) => <StatusBadge status={row.original.level} />,
      },
      {
        accessorKey: "provider",
        header: "provider",
        enableSorting: false,
        cell: ({ row }) => row.original.provider ?? "-",
      },
      {
        accessorKey: "dataset_key",
        header: "dataset",
        enableSorting: false,
        cell: ({ row }) => row.original.dataset_key ?? "-",
      },
      {
        accessorKey: "stage",
        header: "stage",
        enableSorting: false,
        cell: ({ row }) => row.original.stage ?? "-",
      },
      {
        id: "message",
        header: "message",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="max-w-96">
            <div className="line-clamp-2">{row.original.message}</div>
          </div>
        ),
      },
      {
        id: "job",
        header: "job",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            <Link
              className={
                "inline-flex items-center gap-1 text-primary hover:underline"
              }
              href={`/ops/import-jobs/${row.original.job_id}`}
            >
              {shortId(row.original.job_id)}
              <ArrowUpRightIcon className="size-3" />
            </Link>
          </span>
        ),
      },
      {
        accessorKey: "code",
        header: "code",
        enableSorting: false,
        cell: ({ row }) => row.original.code ?? "-",
      },
    ],
    [],
  );

  return (
    <AdminShell
      actions={
        <Button
          disabled={
            systemLogs.isFetching || apiLogs.isFetching || jobEvents.isFetching
          }
          type="button"
          variant="outline"
          onClick={refreshAll}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="system log와 opt-in API call log를 같은 운영 화면에서 조회합니다."
      section="Ops"
      title="Logs"
    >
      <div className="flex flex-col gap-4">
        {(systemLogs.isError || apiLogs.isError || jobEvents.isError) && (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>로그 조회 실패</AlertTitle>
            <AlertDescription>
              {systemLogs.error?.message ??
                apiLogs.error?.message ??
                jobEvents.error?.message}
            </AlertDescription>
          </Alert>
        )}

        <div className="rounded-lg border bg-background p-4">
          <div className="flex flex-wrap items-center gap-3">
            <NativeSelect
              aria-label="log page size"
              value={String(pageSize)}
              onChange={(event) => {
                setPageSize(Number(event.target.value) as typeof pageSize);
                resetSystemPage();
                resetApiPage();
                resetEventPage();
              }}
            >
              {PAGE_SIZE_OPTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Badge variant="outline">
              system {systemItems.length}
            </Badge>
            <Badge variant="outline">
              api {apiItems.length}
            </Badge>
            <Badge variant="outline">
              job events {eventItems.length}
            </Badge>
            <Badge variant="outline">
              page size {pageSize}
            </Badge>
            <Badge variant={live.state === "live" ? "default" : "outline"}>
              live {live.state}
            </Badge>
          </div>
        </div>

        <Tabs defaultValue="system">
          <TabsList>
            <TabsTrigger value="system">System logs</TabsTrigger>
            <TabsTrigger value="api">API call logs</TabsTrigger>
            <TabsTrigger value="events">Job events</TabsTrigger>
          </TabsList>

          <TabsContent className="mt-4" value="system">
            <section className="rounded-lg border bg-background">
              <div className="grid gap-3 border-b p-4 md:grid-cols-[minmax(12rem,1fr)_auto_auto_auto_auto]">
                <div className="relative">
                  <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                  <Input
                    aria-label="system log search"
                    className="pl-8"
                    placeholder="event, message, request_id"
                    value={systemQ}
                    onChange={(event) => {
                      setSystemQ(event.target.value);
                      resetSystemPage();
                    }}
                  />
                </div>
                <NativeSelect
                  aria-label="system log level"
                  value={systemLevel}
                  onChange={(event) => {
                    setSystemLevel(event.target.value as SystemLogLevel | "all");
                    resetSystemPage();
                  }}
                >
                  {LEVELS.map((item) => (
                    <NativeSelectOption key={item} value={item}>
                      {item}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
                <Input
                  aria-label="system log source"
                  placeholder="source"
                  value={systemSource}
                  onChange={(event) => {
                    setSystemSource(event.target.value);
                    resetSystemPage();
                  }}
                />
                <Badge variant="outline">page {systemPageIndex}</Badge>
                <Button
                  disabled={systemPageIndex <= 1}
                  type="button"
                  variant="outline"
                  onClick={resetSystemPage}
                >
                  첫 페이지
                </Button>
                <Button
                  disabled={!systemLogs.data?.meta.page?.next_cursor}
                  type="button"
                  variant="outline"
                  onClick={nextSystemPage}
                >
                  다음
                </Button>
              </div>
              <DataTable
                columns={systemColumns}
                data={systemItems}
                getRowId={(row) => row.log_id}
                isLoading={systemLogs.isLoading}
                emptyMessage="system log가 없습니다."
                containerClassName="overflow-auto"
              />
            </section>
          </TabsContent>

          <TabsContent className="mt-4" value="api">
            <section className="rounded-lg border bg-background">
              <div className="grid gap-3 border-b p-4 md:grid-cols-[auto_minmax(12rem,1fr)_auto_auto_auto]">
                <Input
                  aria-label="api log method"
                  placeholder="method"
                  value={apiMethod}
                  onChange={(event) => {
                    setApiMethod(event.target.value);
                    resetApiPage();
                  }}
                />
                <Input
                  aria-label="api log path"
                  placeholder="path contains"
                  value={apiPath}
                  onChange={(event) => {
                    setApiPath(event.target.value);
                    resetApiPage();
                  }}
                />
                <Input
                  aria-label="api log min status"
                  placeholder="min status"
                  value={apiMinStatus}
                  onChange={(event) => {
                    setApiMinStatus(event.target.value);
                    resetApiPage();
                  }}
                />
                <Badge variant="outline">page {apiPageIndex}</Badge>
                <Button
                  disabled={apiPageIndex <= 1}
                  type="button"
                  variant="outline"
                  onClick={resetApiPage}
                >
                  첫 페이지
                </Button>
                <Button
                  disabled={!apiLogs.data?.meta.page?.next_cursor}
                  type="button"
                  variant="outline"
                  onClick={nextApiPage}
                >
                  다음
                </Button>
              </div>
              <DataTable
                columns={apiColumns}
                data={apiItems}
                getRowId={(row) => row.log_id}
                isLoading={apiLogs.isLoading}
                emptyMessage="API call log가 없습니다."
                containerClassName="overflow-auto"
              />
            </section>
          </TabsContent>

          <TabsContent className="mt-4" value="events">
            <section className="rounded-lg border bg-background">
              <div className="grid gap-3 border-b p-4 md:grid-cols-[minmax(16rem,1.2fr)_auto_auto_auto_auto_auto]">
                <Input
                  aria-label="job event job id"
                  placeholder="job_id"
                  value={eventJobId}
                  onChange={(event) => {
                    setEventJobId(event.target.value);
                    resetEventPage();
                  }}
                />
                <NativeSelect
                  aria-label="job event level"
                  value={eventLevel}
                  onChange={(event) => {
                    setEventLevel(
                      event.target.value as ImportJobEventLevel | "all",
                    );
                    resetEventPage();
                  }}
                >
                  {EVENT_LEVELS.map((item) => (
                    <NativeSelectOption key={item} value={item}>
                      {item}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
                <Input
                  aria-label="job event provider"
                  placeholder="provider"
                  value={eventProvider}
                  onChange={(event) => {
                    setEventProvider(event.target.value);
                    resetEventPage();
                  }}
                />
                <Input
                  aria-label="job event dataset key"
                  placeholder="dataset_key"
                  value={eventDatasetKey}
                  onChange={(event) => {
                    setEventDatasetKey(event.target.value);
                    resetEventPage();
                  }}
                />
                <Badge variant="outline">page {eventPageIndex}</Badge>
                <Button
                  disabled={eventPageIndex <= 1}
                  type="button"
                  variant="outline"
                  onClick={resetEventPage}
                >
                  첫 페이지
                </Button>
                <Button
                  disabled={!jobEvents.data?.meta.page?.next_cursor}
                  type="button"
                  variant="outline"
                  onClick={nextEventPage}
                >
                  다음
                </Button>
              </div>
              <DataTable
                columns={eventColumns}
                data={eventItems}
                getRowId={(row) => row.event_id}
                isLoading={jobEvents.isLoading}
                emptyMessage="job event가 없습니다."
                containerClassName="overflow-auto"
              />
            </section>
          </TabsContent>
        </Tabs>
      </div>
    </AdminShell>
  );
}
