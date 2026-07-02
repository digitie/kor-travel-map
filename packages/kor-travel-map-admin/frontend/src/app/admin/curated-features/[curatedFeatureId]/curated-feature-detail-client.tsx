"use client";

import {
  AlertTriangleIcon,
  ArrowLeftIcon,
  ExternalLinkIcon,
  RefreshCwIcon,
} from "lucide-react";
import Link from "next/link";

import { useAdminCuratedFeature, useAdminCuratedThemes } from "@/api/curated";
import { AdminShell } from "@/components/admin-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { statusLabel } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  CuratedFeatureDetailPreview,
  CuratedFeatureLocationPanel,
  CuratedPlaceSearchPanel,
  FeatureEditor,
} from "../curated-features-client";

function featureHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

function uiLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return value
    .replace(/kor-travel-concierge/gi, "place-candidate")
    .replace(/concierge/gi, "place-candidate")
    .replace(/컨시어지/g, "장소 후보");
}

export function CuratedFeatureDetailClient({
  curatedFeatureId,
}: {
  curatedFeatureId: string;
}) {
  const feature = useAdminCuratedFeature(curatedFeatureId);
  const themes = useAdminCuratedThemes({ limit: 200 });
  const item = feature.data?.data ?? null;

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
      description="curated 후보의 위치, 장소 검색 결과, display 속성, detail snapshot을 한 화면에서 검토합니다."
      section="관리"
      title="큐레이션 피처 상세"
    >
      <div className="flex flex-col gap-4">
        {feature.isLoading ? <Skeleton className="h-[34rem] w-full" /> : null}
        {feature.isError ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>curated feature 상세 조회 실패</AlertTitle>
            <AlertDescription>{feature.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {item ? (
          <>
            <section className="rounded-lg border bg-background p-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline">{item.theme_name}</Badge>
                    <Badge variant="outline">{item.feature_kind}</Badge>
                    <Badge variant="secondary">
                      {statusLabel(item.curation_status)}
                    </Badge>
                  </div>
                  <h2 className="mt-3 break-keep text-xl font-semibold">
                    {item.display_title ?? item.feature_name}
                  </h2>
                  <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
                    {shortId(item.curated_feature_id, 32)}
                  </div>
                </div>
                <dl className="grid min-w-64 grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
                  <dt className="text-muted-foreground">selected</dt>
                  <dd>{formatDateTime(item.selected_at)}</dd>
                  <dt className="text-muted-foreground">updated</dt>
                  <dd>{formatDateTime(item.updated_at)}</dd>
                  <dt className="text-muted-foreground">rank</dt>
                  <dd>{item.rank_score.toFixed(2)}</dd>
                  <dt className="text-muted-foreground">source</dt>
                  <dd>{uiLabel(item.source_name)}</dd>
                </dl>
              </div>
            </section>

            <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_28rem]">
              <div className="flex min-w-0 flex-col gap-4">
                <CuratedFeatureLocationPanel feature={item} />
                <CuratedFeatureDetailPreview feature={item} />
              </div>
              <aside className="flex min-w-0 flex-col gap-4">
                <CuratedPlaceSearchPanel
                  feature={item}
                  key={`${item.curated_feature_id}:place-search`}
                />
                {/* updated_at in the key remounts the editor after a patch
                    (place-search 반영 / 저장) so its inputs re-sync to the
                    refetched feature instead of showing stale useState. */}
                <FeatureEditor
                  feature={item}
                  key={`${item.curated_feature_id}:${item.updated_at}:editor`}
                  themes={themes.data?.data.items ?? []}
                />
              </aside>
            </div>
          </>
        ) : null}
      </div>
    </AdminShell>
  );
}
