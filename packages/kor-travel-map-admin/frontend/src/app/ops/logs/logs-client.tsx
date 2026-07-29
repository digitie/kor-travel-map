"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangleIcon,
  RefreshCwIcon,
  SearchIcon,
} from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import {
  useApiCallLogs,
  useSystemLogs,
  type SystemLogLevel,
} from "@/api/ops";
import { AdminShell } from "@/components/admin-shell";
import { CursorPager } from "@/components/pagination-bar";
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
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
type LogTab = "system" | "api";

function useLogsClientController({
  initialTab,
  initialLevel,
}: {
  initialTab?: string;
  initialLevel?: string;
} = {}) {
  const [activeLogTab, setActiveLogTab] = useState<LogTab>(() =>
    initialTab === "system" || initialTab === "api"
      ? initialTab
      : "system",
  );
  const [systemQ, setSystemQ] = useState("");
  const deferredSystemQ = useDeferredValue(systemQ.trim());
  const [systemLevel, setSystemLevel] = useState<SystemLogLevel | "all">(() =>
    initialLevel &&
    (LEVELS as readonly string[]).includes(initialLevel)
      ? (initialLevel as SystemLogLevel)
      : "all",
  );
  const [systemSource, setSystemSource] = useState("");
  const [systemCursor, setSystemCursor] = useState<string | null>(null);
  const [systemPageIndex, setSystemPageIndex] = useState(1);

  const [apiMethod, setApiMethod] = useState("");
  const [apiPath, setApiPath] = useState("");
  const [apiMinStatus, setApiMinStatus] = useState("");
  const [apiCursor, setApiCursor] = useState<string | null>(null);
  const [apiPageIndex, setApiPageIndex] = useState(1);

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
  const systemLogs = useSystemLogs(systemParams);
  const apiLogs = useApiCallLogs(apiParams);
  const systemItems = systemLogs.data?.data.items ?? [];
  const apiItems = apiLogs.data?.data.items ?? [];
  const resetSystemPage = () => {
    setSystemCursor(null);
    setSystemPageIndex(1);
  };
  const resetApiPage = () => {
    setApiCursor(null);
    setApiPageIndex(1);
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
  const refreshAll = () => {
    void systemLogs.refetch();
    void apiLogs.refetch();
  };

  type SystemLogRow = (typeof systemItems)[number];
  type ApiLogRow = (typeof apiItems)[number];
  // 두 로그 테이블은 모두 keyset cursor 목록(next_cursor 페이징) — 서버가 정렬을 소유하므로
  // 모든 accessor 컬럼의 client 정렬을 끈다(#502: manual 기본에서 client 정렬은 현재 페이지만
  // 재배열해 오해를 줌).
  const systemColumns = useMemo<ColumnDef<SystemLogRow, unknown>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: "생성",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        accessorKey: "level",
        header: "레벨",
        enableSorting: false,
        cell: ({ row }) => <StatusBadge status={row.original.level} />,
      },
      { accessorKey: "source", header: "소스", enableSorting: false },
      { accessorKey: "event", header: "이벤트", enableSorting: false },
      {
        id: "message",
        header: "메시지",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="max-w-96">
            <div className="line-clamp-2">{row.original.message}</div>
          </div>
        ),
      },
      {
        id: "request",
        header: "요청",
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
        header: "생성",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        accessorKey: "method",
        header: "방식",
        enableSorting: false,
        cell: ({ row }) => <Badge variant="outline">{row.original.method}</Badge>,
      },
      {
        accessorKey: "status_code",
        header: "상태",
        enableSorting: false,
        cell: ({ row }) => (
          <StatusBadge status={String(row.original.status_code)} />
        ),
      },
      {
        accessorKey: "duration_ms",
        header: "소요시간",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono">{row.original.duration_ms}ms</span>
        ),
      },
      {
        id: "path",
        header: "경로",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-96 break-all font-mono text-xs">
            {row.original.path}
          </span>
        ),
      },
      {
        id: "request",
        header: "요청",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.request_id)}
          </span>
        ),
      },
      {
        accessorKey: "error_code",
        header: "오류",
        enableSorting: false,
        cell: ({ row }) => row.original.error_code ?? "-",
      },
    ],
    [],
  );

  return {
    activeLogTab,
    apiColumns,
    apiItems,
    apiLogs,
    apiMethod,
    apiMinStatus,
    apiPageIndex,
    apiPath,
    nextApiPage,
    nextSystemPage,
    pageSize,
    refreshAll,
    resetApiPage,
    resetSystemPage,
    setActiveLogTab,
    setApiMethod,
    setApiMinStatus,
    setApiPath,
    setPageSize,
    setSystemLevel,
    setSystemQ,
    setSystemSource,
    systemColumns,
    systemItems,
    systemLevel,
    systemLogs,
    systemPageIndex,
    systemQ,
    systemSource,
  };
}

function LogsClientView({
  activeLogTab,
  apiColumns,
  apiItems,
  apiLogs,
  apiMethod,
  apiMinStatus,
  apiPageIndex,
  apiPath,
  nextApiPage,
  nextSystemPage,
  pageSize,
  refreshAll,
  resetApiPage,
  resetSystemPage,
  setActiveLogTab,
  setApiMethod,
  setApiMinStatus,
  setApiPath,
  setPageSize,
  setSystemLevel,
  setSystemQ,
  setSystemSource,
  systemColumns,
  systemItems,
  systemLevel,
  systemLogs,
  systemPageIndex,
  systemQ,
  systemSource,
}: ReturnType<typeof useLogsClientController>) {
  return (
    <AdminShell
      actions={
        <Button
          disabled={systemLogs.isFetching || apiLogs.isFetching}
          type="button"
          variant="outline"
          onClick={refreshAll}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="시스템 로그와 API 호출 로그를 조회합니다."
      title="운영 로그"
    >
      <div className="flex flex-col gap-4">
        {(systemLogs.isError || apiLogs.isError) && (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>로그 조회 실패</AlertTitle>
            <AlertDescription>
              {systemLogs.error?.message ?? apiLogs.error?.message}
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
              page size {pageSize}
            </Badge>
          </div>
        </div>

        <Tabs
          value={activeLogTab}
          onValueChange={(value) => setActiveLogTab(value as LogTab)}
        >
          <TabsList>
            <TabsTrigger value="system">System logs</TabsTrigger>
            <TabsTrigger value="api">API call logs</TabsTrigger>
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
                <CursorPager
                  ariaPrefix="system log"
                  hasNext={Boolean(systemLogs.data?.meta.page?.next_cursor)}
                  isFetching={systemLogs.isFetching}
                  summary={<>page {systemPageIndex}</>}
                  onFirst={resetSystemPage}
                  onNext={nextSystemPage}
                />
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
                  placeholder="경로 포함"
                  value={apiPath}
                  onChange={(event) => {
                    setApiPath(event.target.value);
                    resetApiPage();
                  }}
                />
                <Input
                  aria-label="api log min status"
                  placeholder="최소 상태"
                  value={apiMinStatus}
                  onChange={(event) => {
                    setApiMinStatus(event.target.value);
                    resetApiPage();
                  }}
                />
                <CursorPager
                  ariaPrefix="api log"
                  hasNext={Boolean(apiLogs.data?.meta.page?.next_cursor)}
                  isFetching={apiLogs.isFetching}
                  summary={<>page {apiPageIndex}</>}
                  onFirst={resetApiPage}
                  onNext={nextApiPage}
                />
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

        </Tabs>
      </div>
    </AdminShell>
  );
}

export function LogsClient({
  initialTab,
  initialLevel,
}: {
  initialTab?: string;
  initialLevel?: string;
} = {}) {
  const controller = useLogsClientController({ initialTab, initialLevel });
  return <LogsClientView {...controller} />;
}
