"use client";

import {
  AlertTriangleIcon,
  ArrowLeftIcon,
  CopyIcon,
  ExternalLinkIcon,
  LockIcon,
  RefreshCwIcon,
} from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { useAdminCuratedFeature } from "@/api/curated";
import { AdminShell } from "@/components/admin-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { statusLabel } from "@/lib/status-label";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  CuratedFeatureDetailPreview,
  CuratedFeatureLocationPanel,
} from "../curated-features-client";
import { CuratedLifecycleStrip } from "../curated-lifecycle";

function featureHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

export function CuratedFeatureDetailClient({
  curatedFeatureId,
}: {
  curatedFeatureId: string;
}) {
  const feature = useAdminCuratedFeature(curatedFeatureId);
  const item = feature.data?.data ?? null;
  const pageTitle = item
    ? `${item.display_title ?? item.feature_name} · ${statusLabel(item.curation_status)}`
    : "큐레이션";

  const copyId = () => {
    if (!item) return;
    void navigator.clipboard.writeText(item.curated_feature_id).then(() => {
      toast.success("복사됨");
    });
  };

  return (
    <AdminShell
      actions={
        <>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features/curated"
          >
            <ArrowLeftIcon data-icon="inline-start" />
            목록
          </Link>
          {item ? (
            <Link
              className={cn(buttonVariants({ variant: "ghost" }))}
              href={featureHref(item.feature_id)}
            >
              <ExternalLinkIcon data-icon="inline-start" />
              feature
            </Link>
          ) : null}
          <Button
            disabled={feature.isFetching}
            type="button"
            variant="outline"
            onClick={() => void feature.refetch()}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
        </>
      }
      breadcrumbs={[
        { label: "Feature 관리" },
        { label: "큐레이션 관리", href: "/admin/features/curated" },
        { label: curatedFeatureId },
      ]}
      section="Feature 관리"
      title={pageTitle}
    >
      <div className="flex flex-col gap-4">
        {feature.isLoading ? <Skeleton className="h-[34rem] w-full" /> : null}
        {feature.isError ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>큐레이션 상세 조회 실패</AlertTitle>
            <AlertDescription>{feature.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {item ? (
          <>
            <section className="rounded-lg border bg-background px-4 py-3">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline">{item.theme_name}</Badge>
                    <Badge variant="outline">{item.feature_kind}</Badge>
                    <Badge variant="secondary">
                      {statusLabel(item.curation_status)}
                    </Badge>
                  </div>
                  <h2 className="mt-2 truncate text-base font-semibold">
                    {item.feature_name}
                  </h2>
                  {item.display_title ? (
                    <div className="truncate text-sm text-muted-foreground">
                      {item.display_title}
                    </div>
                  ) : null}
                  <div className="mt-1 flex items-center gap-1">
                    <span className="break-all font-mono text-xs text-muted-foreground">
                      {shortId(item.curated_feature_id, 32)}
                    </span>
                    <Button
                      aria-label="ID 복사"
                      size="icon-sm"
                      title="ID 복사"
                      type="button"
                      variant="ghost"
                      onClick={copyId}
                    >
                      <CopyIcon />
                    </Button>
                  </div>
                </div>
                <dl className="grid min-w-64 grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
                  <dt className="text-muted-foreground">채택 시각</dt>
                  <dd>{formatDateTime(item.selected_at)}</dd>
                  <dt className="text-muted-foreground">수정 시각</dt>
                  <dd>{formatDateTime(item.updated_at)}</dd>
                  <dt className="text-muted-foreground">순위</dt>
                  <dd>{item.rank_score.toFixed(2)}</dd>
                </dl>
              </div>
              <div className="mt-2">
                <CuratedLifecycleStrip
                  activeStatus={item.curation_status}
                  compact
                />
              </div>
            </section>

            <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_28rem]">
              <div className="flex min-w-0 flex-col gap-4">
                <CuratedFeatureLocationPanel feature={item} />
                <CuratedFeatureDetailPreview feature={item} />
              </div>
              <aside className="flex min-w-0 flex-col gap-4">
                <Alert>
                  <LockIcon data-icon="inline-start" />
                  <AlertTitle>legacy 큐레이션 쓰기 봉인 (T-VN-40A)</AlertTitle>
                  <AlertDescription>
                    이 화면은 읽기 전용입니다. 채택·해제·보관·편집은 canonical
                    컬렉션 관리에서 합니다. legacy 표는 T-VN-40C에서 삭제됩니다.
                    <Link
                      className={cn(
                        buttonVariants({ variant: "outline", size: "sm" }),
                        "mt-2",
                      )}
                      href="/admin/features/curated"
                    >
                      컬렉션 관리로
                    </Link>
                  </AlertDescription>
                </Alert>
              </aside>
            </div>
          </>
        ) : null}
      </div>
    </AdminShell>
  );
}
