"use client";

import { AlertTriangleIcon, RefreshCwIcon, SearchIcon } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import {
  useApiCallLogs,
  useSystemLogs,
  type SystemLogLevel,
} from "@/api/ops";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatCount, formatDateTime, shortId } from "@/lib/format";

const LEVELS: Array<SystemLogLevel | "all"> = [
  "critical",
  "error",
  "warning",
  "info",
  "debug",
  "all",
];
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200, 500] as const;

export function LogsClient() {
  const [systemQ, setSystemQ] = useState("");
  const deferredSystemQ = useDeferredValue(systemQ.trim());
  const [systemLevel, setSystemLevel] = useState<SystemLogLevel | "all">("all");
  const [systemSource, setSystemSource] = useState("");
  const [systemCursor, setSystemCursor] = useState<string | null>(null);

  const [apiMethod, setApiMethod] = useState("");
  const [apiPath, setApiPath] = useState("");
  const [apiMinStatus, setApiMinStatus] = useState("");
  const [apiCursor, setApiCursor] = useState<string | null>(null);
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
  const refreshAll = () => {
    void systemLogs.refetch();
    void apiLogs.refetch();
  };

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
      description="system log와 opt-in API call log를 같은 운영 화면에서 조회합니다."
      section="Ops"
      title="Logs"
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
                setSystemCursor(null);
                setApiCursor(null);
              }}
            >
              {PAGE_SIZE_OPTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Badge variant="outline">
              system {formatCount(systemLogs.data?.meta.count)}
            </Badge>
            <Badge variant="outline">
              api {formatCount(apiLogs.data?.meta.count)}
            </Badge>
          </div>
        </div>

        <Tabs defaultValue="system">
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
                      setSystemCursor(null);
                    }}
                  />
                </div>
                <NativeSelect
                  aria-label="system log level"
                  value={systemLevel}
                  onChange={(event) => {
                    setSystemLevel(event.target.value as SystemLogLevel | "all");
                    setSystemCursor(null);
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
                    setSystemCursor(null);
                  }}
                />
                <Button
                  disabled={!systemCursor}
                  type="button"
                  variant="outline"
                  onClick={() => setSystemCursor(null)}
                >
                  첫 페이지
                </Button>
                <Button
                  disabled={!systemLogs.data?.data.next_cursor}
                  type="button"
                  variant="outline"
                  onClick={() =>
                    setSystemCursor(systemLogs.data?.data.next_cursor ?? null)
                  }
                >
                  다음
                </Button>
              </div>
              {systemLogs.isLoading ? <Skeleton className="m-4 h-96" /> : null}
              <div className="overflow-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>created</TableHead>
                      <TableHead>level</TableHead>
                      <TableHead>source</TableHead>
                      <TableHead>event</TableHead>
                      <TableHead>message</TableHead>
                      <TableHead>request</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {systemItems.map((item) => (
                      <TableRow key={item.system_log_key}>
                        <TableCell className="text-muted-foreground">
                          {formatDateTime(item.created_at)}
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={item.level} />
                        </TableCell>
                        <TableCell>{item.source}</TableCell>
                        <TableCell>{item.event}</TableCell>
                        <TableCell className="max-w-96">
                          <div className="line-clamp-2">{item.message}</div>
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {shortId(item.request_id)}
                        </TableCell>
                      </TableRow>
                    ))}
                    {!systemLogs.isLoading && systemItems.length === 0 ? (
                      <TableRow>
                        <TableCell
                          className="h-32 text-center text-muted-foreground"
                          colSpan={6}
                        >
                          system log가 없습니다.
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </div>
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
                    setApiCursor(null);
                  }}
                />
                <Input
                  aria-label="api log path"
                  placeholder="path contains"
                  value={apiPath}
                  onChange={(event) => {
                    setApiPath(event.target.value);
                    setApiCursor(null);
                  }}
                />
                <Input
                  aria-label="api log min status"
                  placeholder="min status"
                  value={apiMinStatus}
                  onChange={(event) => {
                    setApiMinStatus(event.target.value);
                    setApiCursor(null);
                  }}
                />
                <Button
                  disabled={!apiCursor}
                  type="button"
                  variant="outline"
                  onClick={() => setApiCursor(null)}
                >
                  첫 페이지
                </Button>
                <Button
                  disabled={!apiLogs.data?.data.next_cursor}
                  type="button"
                  variant="outline"
                  onClick={() =>
                    setApiCursor(apiLogs.data?.data.next_cursor ?? null)
                  }
                >
                  다음
                </Button>
              </div>
              {apiLogs.isLoading ? <Skeleton className="m-4 h-96" /> : null}
              <div className="overflow-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>created</TableHead>
                      <TableHead>method</TableHead>
                      <TableHead>status</TableHead>
                      <TableHead>duration</TableHead>
                      <TableHead>path</TableHead>
                      <TableHead>request</TableHead>
                      <TableHead>error</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {apiItems.map((item) => (
                      <TableRow key={item.api_call_log_key}>
                        <TableCell className="text-muted-foreground">
                          {formatDateTime(item.created_at)}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{item.method}</Badge>
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={String(item.status_code)} />
                        </TableCell>
                        <TableCell className="font-mono">
                          {item.duration_ms}ms
                        </TableCell>
                        <TableCell className="max-w-96 break-all font-mono text-xs">
                          {item.path}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {shortId(item.request_id)}
                        </TableCell>
                        <TableCell>{item.error_code ?? "-"}</TableCell>
                      </TableRow>
                    ))}
                    {!apiLogs.isLoading && apiItems.length === 0 ? (
                      <TableRow>
                        <TableCell
                          className="h-32 text-center text-muted-foreground"
                          colSpan={7}
                        >
                          API call log가 없습니다.
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </div>
            </section>
          </TabsContent>
        </Tabs>
      </div>
    </AdminShell>
  );
}
