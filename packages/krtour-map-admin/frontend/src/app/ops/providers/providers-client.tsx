"use client";

import { RefreshCwIcon } from "lucide-react";
import { useMemo } from "react";

import {
  type ProviderSyncStateSummary,
  useProvidersFreshness,
} from "@/api/providers";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCount, formatDateTime } from "@/lib/format";

const STALE_AFTER_HOURS = 48;

function isStale(item: ProviderSyncStateSummary): boolean {
  if (!item.last_success_at) {
    return true;
  }
  const ageMs = Date.now() - new Date(item.last_success_at).getTime();
  return ageMs > STALE_AFTER_HOURS * 60 * 60 * 1000;
}

function rowTone(item: ProviderSyncStateSummary): string | undefined {
  if (item.consecutive_failures > 0) {
    return "bg-destructive/5";
  }
  if (isStale(item)) {
    return "bg-muted/60";
  }
  return undefined;
}

export function ProvidersFreshnessClient() {
  const freshness = useProvidersFreshness();
  const items = useMemo(
    () => freshness.data?.data.items ?? [],
    [freshness.data],
  );

  const summary = useMemo(() => {
    const providers = new Set(items.map((item) => item.provider));
    const failing = items.filter((item) => item.consecutive_failures > 0);
    const stale = items.filter(
      (item) => item.consecutive_failures === 0 && isStale(item),
    );
    return { providers: providers.size, failing, stale };
  }, [items]);

  return (
    <AdminShell
      actions={
        <Button
          disabled={freshness.isFetching}
          type="button"
          variant="outline"
          onClick={() => void freshness.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="전 provider×dataset의 마지막 적재 성공/실패와 연속 실패를 한눈에 봅니다 (provider_sync_state)."
      section="Ops"
      title="Providers"
    >
      <div className="flex flex-col gap-4">
        {freshness.isError ? (
          <Alert variant="destructive">
            <AlertTitle>provider 신선도 조회 실패</AlertTitle>
            <AlertDescription>{freshness.error.message}</AlertDescription>
          </Alert>
        ) : null}

        <section className="flex flex-wrap gap-2">
          <Badge variant="outline">
            {formatCount(summary.providers)} providers
          </Badge>
          <Badge variant="outline">{formatCount(items.length)} datasets</Badge>
          <Badge variant={summary.failing.length > 0 ? "destructive" : "outline"}>
            failing {formatCount(summary.failing.length)}
          </Badge>
          <Badge variant="outline">
            stale(&gt;{STALE_AFTER_HOURS}h) {formatCount(summary.stale.length)}
          </Badge>
        </section>

        {summary.failing.length > 0 ? (
          <Alert variant="destructive">
            <AlertTitle>연속 실패 중인 dataset</AlertTitle>
            <AlertDescription>
              {summary.failing
                .map(
                  (item) =>
                    `${item.provider}/${item.dataset_key} (${item.consecutive_failures}회)`,
                )
                .join(", ")}
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="overflow-auto rounded-lg border bg-background">
          {freshness.isLoading ? <Skeleton className="m-4 h-96" /> : null}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>provider</TableHead>
                <TableHead>dataset</TableHead>
                <TableHead>scope</TableHead>
                <TableHead>status</TableHead>
                <TableHead>last success</TableHead>
                <TableHead>last failure</TableHead>
                <TableHead>failures</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow
                  className={rowTone(item)}
                  key={`${item.provider}/${item.dataset_key}/${item.sync_scope}`}
                >
                  <TableCell className="font-medium">{item.provider}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {item.dataset_key}
                  </TableCell>
                  <TableCell>{item.sync_scope}</TableCell>
                  <TableCell>
                    <StatusBadge status={item.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {item.last_success_at
                      ? formatDateTime(item.last_success_at)
                      : "-"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {item.last_failure_at
                      ? formatDateTime(item.last_failure_at)
                      : "-"}
                  </TableCell>
                  <TableCell>
                    {item.consecutive_failures > 0 ? (
                      <Badge variant="destructive">
                        {item.consecutive_failures}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">0</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {!freshness.isLoading && items.length === 0 ? (
                <TableRow>
                  <TableCell
                    className="h-32 text-center text-muted-foreground"
                    colSpan={7}
                  >
                    sync state가 없습니다. 아직 provider 적재가 실행되지 않았습니다.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      </div>
    </AdminShell>
  );
}
