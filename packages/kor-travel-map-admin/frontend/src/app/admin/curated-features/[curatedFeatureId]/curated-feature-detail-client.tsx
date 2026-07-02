"use client";

import {
  AlertTriangleIcon,
  ArchiveIcon,
  ArrowLeftIcon,
  CheckIcon,
  CopyIcon,
  ExternalLinkIcon,
  RefreshCwIcon,
  RotateCcwIcon,
} from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import {
  useAdminCuratedFeature,
  useAdminCuratedThemes,
  useArchiveCuratedFeatureMutation,
  useSelectCuratedFeatureMutation,
  useUnselectCuratedFeatureMutation,
} from "@/api/curated";
import { AdminShell } from "@/components/admin-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { statusLabel } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Skeleton } from "@/components/ui/skeleton";
import { notifyStatusTransition } from "@/lib/curated-labels";
import { formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  CuratedFeatureDetailPreview,
  CuratedFeatureLocationPanel,
  CuratedPlaceSearchPanel,
  FeatureEditor,
} from "../curated-features-client";
import { CuratedLifecycleStrip } from "../curated-lifecycle";

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
  const selectFeature = useSelectCuratedFeatureMutation();
  const unselectFeature = useUnselectCuratedFeatureMutation();
  const archiveFeature = useArchiveCuratedFeatureMutation();
  const item = feature.data?.data ?? null;
  const anyStatusPending =
    selectFeature.isPending ||
    unselectFeature.isPending ||
    archiveFeature.isPending;

  const selectCurated = () => {
    if (!item) return;
    selectFeature.mutate(
      {
        curatedFeatureId: item.curated_feature_id,
        body: { actor: "admin-ui", reason: "admin curated selection" },
      },
      {
        onSuccess: () => {
          // invalidateCurated가 ["curated-feature"]도 무효화해 hero 배지가 자동 갱신.
          notifyStatusTransition("select", item.feature_name);
        },
        onError: (error) => {
          toast.error("채택 실패", { description: error.message });
        },
      },
    );
  };

  const unselectCurated = () => {
    if (!item) return;
    unselectFeature.mutate(
      {
        curatedFeatureId: item.curated_feature_id,
        body: { actor: "admin-ui", reason: "admin curated unselect" },
      },
      {
        onSuccess: () => {
          notifyStatusTransition("unselect", item.feature_name);
        },
        onError: (error) => {
          toast.error("채택 해제 실패", { description: error.message });
        },
      },
    );
  };

  const archiveCurated = () => {
    if (!item) return;
    const ok = window.confirm(
      `"${item.feature_name}"을(를) 보관할까요? 보관하면 규칙 재적용으로 되살아나지 않으며, '보관됨 포함' 필터로만 조회됩니다.`,
    );
    if (!ok) return;
    archiveFeature.mutate(
      {
        curatedFeatureId: item.curated_feature_id,
        body: { actor: "admin-ui", reason: "admin curated archive" },
      },
      {
        onSuccess: () => {
          notifyStatusTransition("archive", item.feature_name);
        },
        onError: (error) => {
          toast.error("보관 실패", { description: error.message });
        },
      },
    );
  };

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
          {item ? (
            item.curation_status === "curated" ? (
              <Button
                disabled={anyStatusPending}
                title="공개에서 제외(거절)"
                type="button"
                variant="outline"
                onClick={unselectCurated}
              >
                <RotateCcwIcon data-icon="inline-start" />
                채택 해제
              </Button>
            ) : (
              <Button
                disabled={anyStatusPending}
                title="공개 목록에 추가"
                type="button"
                onClick={selectCurated}
              >
                <CheckIcon data-icon="inline-start" />
                채택
              </Button>
            )
          ) : null}
          {item ? (
            <Button
              disabled={anyStatusPending}
              title="소프트 삭제"
              type="button"
              variant="destructive"
              onClick={archiveCurated}
            >
              <ArchiveIcon data-icon="inline-start" />
              보관
            </Button>
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
      description="curated 후보의 위치, 장소 검색 결과, 노출 정보, 배포 스냅샷을 한 화면에서 검토합니다."
      section="관리"
      title="큐레이션 상세"
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
                    {item.feature_name}
                  </h2>
                  {item.display_title ? (
                    <div className="mt-1 text-sm text-muted-foreground">
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
                  <dt className="text-muted-foreground">소스</dt>
                  <dd>{uiLabel(item.source_name)}</dd>
                </dl>
              </div>
              <div className="mt-3">
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
                <CuratedPlaceSearchPanel
                  feature={item}
                  key={`${item.curated_feature_id}:place-search`}
                />
                {/* The editor keeps its inputs in an override state that follows
                    the refetched server values while pristine, so the key no
                    longer needs updated_at to re-sync after a patch/save. */}
                <FeatureEditor
                  feature={item}
                  key={`${item.curated_feature_id}:editor`}
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
