"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (list) · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import { RefreshCwIcon, SearchIcon } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import {
  useApiCallLogs,
  useSystemLogs,
  type SystemLogLevel,
} from "@/api/ops";
import { AdminShell } from "@/components/admin-shell";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { CursorPager } from "@/components/pagination-bar";
import { HttpStatusBadge, LevelBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  DataTable,
  DataTableClampCell,
  type DataTableColumnMeta,
} from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { statusLabel } from "@/lib/status-label";

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
          <span className="text-text-secondary">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        accessorKey: "level",
        header: "레벨",
        enableSorting: false,
        cell: ({ row }) => <LevelBadge level={row.original.level} />,
      },
      { accessorKey: "source", header: "소스", enableSorting: false },
      { accessorKey: "event", header: "이벤트", enableSorting: false },
      {
        id: "message",
        header: "메시지",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <DataTableClampCell lines={2}>{row.original.message}</DataTableClampCell>
        ),
      },
      {
        id: "request",
        header: "요청",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs slashed-zero">
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
          <span className="text-text-secondary">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        accessorKey: "method",
        header: "방식",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.method}</span>
        ),
      },
      {
        accessorKey: "status_code",
        header: "상태",
        enableSorting: false,
        cell: ({ row }) => <HttpStatusBadge code={row.original.status_code} />,
      },
      {
        accessorKey: "duration_ms",
        header: "소요시간",
        enableSorting: false,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <span className="tabular-nums">
            {formatCount(row.original.duration_ms)}
            <span className="ml-0.5 text-2xs text-text-secondary">ms</span>
          </span>
        ),
      },
      {
        id: "path",
        header: "경로",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <span className="block max-w-96 font-mono text-xs break-all">
            {row.original.path}
          </span>
        ),
      },
      {
        id: "request",
        header: "요청",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs slashed-zero">
            {shortId(row.original.request_id)}
          </span>
        ),
      },
      {
        accessorKey: "error_code",
        header: "오류",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.error_code ? (
            <span className="font-mono text-xs">{row.original.error_code}</span>
          ) : (
            <span className="text-text-tertiary">{NULL_GLYPH}</span>
          ),
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
  const isRefreshing = systemLogs.isFetching || apiLogs.isFetching;
  return (
    <AdminShell
      actions={
        <Button
          loading={isRefreshing}
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
      <Tabs
        value={activeLogTab}
        onValueChange={(value) => setActiveLogTab(value as LogTab)}
      >
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 border-b border-border">
          <TabsList className="border-b-0" variant="line">
            <TabsTrigger value="system">System logs</TabsTrigger>
            <TabsTrigger value="api">API call logs</TabsTrigger>
          </TabsList>
          <FilterField className="pb-1.5" label="페이지 크기">
            <NativeSelect
              aria-label="log page size"
              size="sm"
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
          </FilterField>
        </div>

        <TabsContent className="mt-4 space-y-4" value="system">
          <FilterBar>
            <FilterField className="min-w-64 grow" label="검색">
              <span className="relative block">
                <SearchIcon
                  aria-hidden="true"
                  className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-text-tertiary"
                />
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
              </span>
            </FilterField>
            <FilterField label="레벨">
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
                    {item === "all" ? "전체" : statusLabel(item)}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </FilterField>
            <FilterField label="소스">
              <Input
                aria-label="system log source"
                placeholder="예: api.request"
                value={systemSource}
                onChange={(event) => {
                  setSystemSource(event.target.value);
                  resetSystemPage();
                }}
              />
            </FilterField>
          </FilterBar>
          <DataTable
            ariaLabel="system log 목록"
            columns={systemColumns}
            data={systemItems}
            emptyState={{
              title: "system log가 없습니다.",
              description: "검색어·레벨·소스 필터를 넓혀 보세요.",
            }}
            error={systemLogs.error}
            errorTitle="system log를 불러오지 못했습니다"
            getRowId={(row) => row.log_id}
            isError={systemLogs.isError}
            isLoading={systemLogs.isLoading}
            onRetry={() => systemLogs.refetch()}
            skeletonRowCount={8}
          />
          <CursorPager
            ariaPrefix="system log"
            hasNext={Boolean(systemLogs.data?.meta.page?.next_cursor)}
            isFetching={systemLogs.isFetching}
            isFirst={systemPageIndex === 1}
            summary={
              <>
                page {systemPageIndex} · 이 페이지{" "}
                {formatCount(systemLogs.data ? systemItems.length : null, {
                  loading: systemLogs.isLoading,
                })}
                건
              </>
            }
            onFirst={resetSystemPage}
            onNext={nextSystemPage}
          />
        </TabsContent>

        <TabsContent className="mt-4 space-y-4" value="api">
          <FilterBar>
            <FilterField label="방식">
              <Input
                aria-label="api log method"
                className="w-32"
                placeholder="예: GET"
                value={apiMethod}
                onChange={(event) => {
                  setApiMethod(event.target.value);
                  resetApiPage();
                }}
              />
            </FilterField>
            <FilterField className="min-w-64 grow" label="경로">
              <Input
                aria-label="api log path"
                placeholder="예: /v1/ops"
                value={apiPath}
                onChange={(event) => {
                  setApiPath(event.target.value);
                  resetApiPage();
                }}
              />
            </FilterField>
            <FilterField hint="이 값 이상인 HTTP 상태만" label="최소 상태 코드">
              <Input
                aria-label="api log min status"
                className="w-32"
                inputMode="numeric"
                placeholder="예: 400"
                value={apiMinStatus}
                onChange={(event) => {
                  setApiMinStatus(event.target.value);
                  resetApiPage();
                }}
              />
            </FilterField>
          </FilterBar>
          <DataTable
            ariaLabel="API call log 목록"
            columns={apiColumns}
            data={apiItems}
            emptyState={{
              title: "API call log가 없습니다.",
              description: "방식·경로·최소 상태 코드 필터를 넓혀 보세요.",
            }}
            error={apiLogs.error}
            errorTitle="API call log를 불러오지 못했습니다"
            getRowId={(row) => row.log_id}
            isError={apiLogs.isError}
            isLoading={apiLogs.isLoading}
            onRetry={() => apiLogs.refetch()}
            skeletonRowCount={8}
          />
          <CursorPager
            ariaPrefix="api log"
            hasNext={Boolean(apiLogs.data?.meta.page?.next_cursor)}
            isFetching={apiLogs.isFetching}
            isFirst={apiPageIndex === 1}
            summary={
              <>
                page {apiPageIndex} · 이 페이지{" "}
                {formatCount(apiLogs.data ? apiItems.length : null, {
                  loading: apiLogs.isLoading,
                })}
                건
              </>
            }
            onFirst={resetApiPage}
            onNext={nextApiPage}
          />
        </TabsContent>
      </Tabs>
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
