"use client";

import {
  ArrowLeftIcon,
  PlayIcon,
  RefreshCwIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";

import { useOpsLiveInvalidation } from "@/api/live";
import {
  useCancelFeatureUpdateRequestMutation,
  useFeatureUpdateRequest,
  useRunFeatureUpdateRequestNowMutation,
} from "@/api/updateRequests";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button-variants";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime, shortId } from "@/lib/format";

const terminalStatuses = new Set(["done", "failed", "cancelled"]);

export function FeatureUpdateRequestDetailClient({
  requestId,
}: {
  requestId: string;
}) {
  const request = useFeatureUpdateRequest(requestId);
  const cancelRequest = useCancelFeatureUpdateRequestMutation();
  const runNow = useRunFeatureUpdateRequestNowMutation();
  const live = useOpsLiveInvalidation({
    topics: [
      "feature_update_requests",
      `feature_update_request:${requestId}`,
      "import_jobs",
      "dagster_runs",
    ],
  });
  const data = request.data?.data;
  const canCancel = Boolean(data?.status && !terminalStatuses.has(data.status));
  const canRunNow = Boolean(data?.status && data.status !== "running");

  return (
    <AdminShell
      actions={
        <>
          <Link
            className={buttonVariants({ variant: "outline" })}
            href="/admin/features/update-requests"
          >
            <ArrowLeftIcon data-icon="inline-start" />
            목록
          </Link>
          <Badge variant={live.state === "live" ? "default" : "outline"}>
            {live.state}
          </Badge>
          <Button
            disabled={request.isFetching}
            type="button"
            variant="outline"
            onClick={() => void request.refetch()}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
        </>
      }
      description="갱신 요청의 스코프·매칭 스코프·작업·Dagster 실행 상태를 확인합니다."
      section="관리"
      title="갱신 요청 상세"
    >
      <div className="flex flex-col gap-4">
        {request.isError || cancelRequest.isError || runNow.isError ? (
          <Alert variant="destructive">
            <AlertTitle>요청 조회 실패</AlertTitle>
            <AlertDescription>
              {request.error?.message ??
                cancelRequest.error?.message ??
                runNow.error?.message}
            </AlertDescription>
          </Alert>
        ) : null}

        {request.isLoading ? <Skeleton className="h-80" /> : null}

        {data ? (
          <>
            <section className="rounded-lg border bg-background p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="break-all font-mono text-sm">{requestId}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <StatusBadge status={data.status} />
                    <Badge variant="outline">{data.scope_type}</Badge>
                    <Badge variant="outline">{data.run_mode}</Badge>
                    {data.dry_run ? <Badge variant="outline">dry-run</Badge> : null}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {canCancel ? (
                    <Button
                      disabled={cancelRequest.isPending}
                      type="button"
                      variant="outline"
                      onClick={() =>
                        cancelRequest.mutate({
                          requestId,
                          body: {
                            error_message:
                              "cancelled from feature update request detail",
                          },
                        })
                      }
                    >
                      <XIcon data-icon="inline-start" />
                      취소
                    </Button>
                  ) : null}
                  {canRunNow ? (
                    <Button
                      disabled={runNow.isPending}
                      type="button"
                      onClick={() =>
                        runNow.mutate({
                          requestId,
                          body: { reason: "run-now from detail view" },
                        })
                      }
                    >
                      <PlayIcon data-icon="inline-start" />
                      즉시 실행
                    </Button>
                  ) : null}
                </div>
              </div>
              <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2 xl:grid-cols-4">
                <div>
                  <dt className="text-muted-foreground">작업</dt>
                  <dd className="font-mono">
                    {data.job_id ? (
                      <Link
                        className="underline underline-offset-2"
                        href={`/ops/import-jobs/${data.job_id}`}
                      >
                        {shortId(data.job_id)}
                      </Link>
                    ) : (
                      "-"
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Dagster 실행</dt>
                  <dd className="font-mono">{shortId(data.dagster_run_id)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">생성</dt>
                  <dd>{formatDateTime(data.created_at)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">수정</dt>
                  <dd>{formatDateTime(data.updated_at)}</dd>
                </div>
              </dl>
            </section>

            <section className="grid gap-4 xl:grid-cols-2">
              <div className="rounded-lg border bg-background p-4">
                <div className="mb-2 font-medium">스코프</div>
                <pre className="max-h-[32rem] overflow-auto rounded-md bg-muted p-3 text-xs">
                  {JSON.stringify(data.scope, null, 2)}
                </pre>
              </div>
              <div className="rounded-lg border bg-background p-4">
                <div className="mb-2 font-medium">매칭된 스코프</div>
                <pre className="max-h-[32rem] overflow-auto rounded-md bg-muted p-3 text-xs">
                  {JSON.stringify(data.matched_scope, null, 2)}
                </pre>
              </div>
            </section>

            <section className="rounded-lg border bg-background p-4">
              <div className="mb-2 font-medium">정책</div>
              <pre className="max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(data.update_policy, null, 2)}
              </pre>
            </section>
          </>
        ) : null}
      </div>
    </AdminShell>
  );
}
