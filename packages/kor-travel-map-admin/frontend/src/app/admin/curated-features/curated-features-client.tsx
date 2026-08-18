"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (detail) · design-system: design.md · designed-as-app

import type { ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import {
  useCuratedFeatureDetailSnapshot,
  type CuratedFeature,
} from "@/api/curated";
import { DetailList } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { JsonViewer } from "@/components/json-viewer";
import { SectionCard } from "@/components/section-card";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DataTable,
  type DataTableColumnMeta,
} from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

// T-VN-40A: 이 모듈에 있던 legacy write UI(CuratedPlaceSearchPanel — feature_id 교체 patch,
// FeatureEditor — rank/relation/reuse_policy/title patch)는 fence로 410이 됐고 삭제했다.
// 남은 것은 read 패널(위치·상세 미리보기)뿐이며 40C에서 legacy 표와 함께 지운다.

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
/** 미리보기 마커 색은 토큰만(design.md §Theme — `--compare-a/b`). */
const PREVIEW_MARKER_COLOR = "var(--compare-a)";

function coordLabel(feature: CuratedFeature): string | null {
  const coord = featureCoord(feature);
  if (coord) {
    const [lon, lat] = coord;
    return `${lon.toFixed(5)}, ${lat.toFixed(5)}`;
  }
  return null;
}

function featureCoord(feature: CuratedFeature): [number, number] | null {
  if (feature.lon == null || feature.lat == null) return null;
  const lon = Number(feature.lon);
  const lat = Number(feature.lat);
  return Number.isFinite(lon) && Number.isFinite(lat) ? [lon, lat] : null;
}

function uiLabel(value: string | null | undefined): string {
  if (!value) return NULL_GLYPH;
  return value
    .replace(/kor-travel-concierge/gi, "place-candidate")
    .replace(/concierge/gi, "place-candidate")
    .replace(/컨시어지/g, "장소 후보");
}

function providerLabel(value: string | null | undefined): string {
  return uiLabel(value);
}

function featureAddressLabel(feature: CuratedFeature): string | null {
  const address = feature.address as Record<string, unknown>;
  for (const key of ["road_address", "jibun_address", "full_address", "address"]) {
    const value = address[key];
    if (typeof value === "string" && value.trim().length > 0) return value;
  }
  return null;
}

/** 접이식 payload(content/source/theme) — summary 12px/500 mono + JsonViewer(그룹 유일 JSON 렌더러). */
function PayloadDisclosure({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="group/details">
      <summary className="inline-flex h-control-sm cursor-pointer list-none items-center gap-1 rounded-control font-mono text-xs text-text-secondary outline-none select-none hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="w-3 text-text-tertiary group-open/details:hidden">
          +
        </span>
        <span aria-hidden="true" className="hidden w-3 text-text-tertiary group-open/details:inline">
          −
        </span>
        {label}
      </summary>
      <div className="pt-1">
        <JsonViewer copyable maxHeight="lg" value={value} />
      </div>
    </details>
  );
}

export function CuratedFeatureLocationPanel({
  feature,
}: {
  feature: CuratedFeature | null;
}) {
  if (!feature) return null;
  const coord = featureCoord(feature);

  return (
    <SectionCard contentClassName="space-y-4" title="위치 확인">
      {coord ? (
        <div className="relative h-80 overflow-hidden rounded-control bg-surface-subtle 2xl:h-96">
          <VWorldMapView
            apiKey={VWORLD_KEY}
            center={coord}
            className="absolute inset-0 h-full w-full"
            key={feature.curated_feature_id}
            navigation
            scale
            zoom={14}
          >
            <VWorldMarker
              lngLat={coord}
              markerColor={PREVIEW_MARKER_COLOR}
              selected
              size={30}
              title={feature.feature_name}
            />
          </VWorldMapView>
        </div>
      ) : (
        <EmptyState
          description="원본 feature의 주소나 좌표를 보정하면 지도에 표시됩니다."
          size="sm"
          title="좌표가 없어 지도 marker를 표시할 수 없습니다."
        />
      )}
      <DetailList
        items={[
          { label: "좌표", value: coordLabel(feature), mono: true },
          { label: "주소", value: featureAddressLabel(feature) },
          { label: "카테고리", value: feature.feature_category, mono: true },
          {
            label: "provider",
            value: `${providerLabel(feature.provider)} / ${feature.dataset_key}`,
            mono: true,
          },
        ]}
        layout="inline"
      />
    </SectionCard>
  );
}
type CuratedFeatureDetailItem = NonNullable<
  ReturnType<typeof useCuratedFeatureDetailSnapshot>["data"]
>["data"]["items"][number];

export function CuratedFeatureDetailPreview({
  feature,
}: {
  feature: CuratedFeature | null;
}) {
  const snapshot = useCuratedFeatureDetailSnapshot(feature?.curated_feature_id ?? null);
  const data = snapshot.data?.data;

  const itemColumns = useMemo<ColumnDef<CuratedFeatureDetailItem, unknown>[]>(
    () => [
      {
        accessorKey: "sort_order",
        header: "순서",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => row.original.sort_order,
      },
      {
        accessorKey: "relation",
        header: "관계",
        cell: ({ row }) => (
          <span className="font-mono text-xs text-text-secondary">{row.original.relation}</span>
        ),
      },
      {
        accessorKey: "feature_id",
        header: "feature",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <span className="block max-w-[12rem] font-mono text-xs break-all slashed-zero">
            {row.original.feature_id}
          </span>
        ),
      },
      {
        id: "memo",
        header: "메모",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <span
            className={cn(
              "block max-w-[12rem]",
              !row.original.memo && "text-text-tertiary",
            )}
          >
            {row.original.memo ?? NULL_GLYPH}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <SectionCard
      actions={
        data ? (
          <span className="font-mono text-xs text-text-secondary slashed-zero">
            etag {shortId(data.etag, 10)}
          </span>
        ) : undefined
      }
      contentClassName="space-y-4"
      description="다운스트림(PinVi 등)이 복사해 가는 최종 payload — version/etag로 변경을 감지합니다."
      title="배포 스냅샷 미리보기"
    >
      {!feature ? (
        <EmptyState
          description="목록에서 후보를 고르면 이 자리에 payload와 항목이 열립니다."
          size="sm"
          title="후보를 선택하면 배포 스냅샷을 조회합니다."
        />
      ) : null}
      {snapshot.isLoading ? (
        <div aria-busy="true" className="flex flex-col gap-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-28 w-full" />
        </div>
      ) : null}
      {snapshot.isError ? (
        <Alert variant="destructive">
          <AlertTitle>배포 스냅샷 조회 실패</AlertTitle>
          <AlertDescription>{snapshot.error.message}</AlertDescription>
          <AlertActions>
            <Button
              loading={snapshot.isFetching}
              size="sm"
              type="button"
              variant="outline"
              onClick={() => void snapshot.refetch()}
            >
              다시 시도
            </Button>
          </AlertActions>
        </Alert>
      ) : null}
      {data ? (
        <>
          <DetailList
            items={[
              { label: "version", value: data.version, mono: true },
              { label: "수정 시각", value: formatDateTime(data.updated_at) },
              { label: "items", value: formatCount(data.items.length), numeric: true },
            ]}
            layout="inline"
          />
          <DataTable
            columns={itemColumns}
            data={data.items}
            emptyState={{
              title: "detail item이 없습니다.",
              description: "큐레이션 항목이 채택되면 스냅샷 items에 포함됩니다.",
            }}
            getRowId={(item) => item.curated_feature_item_id}
            manualSorting={false}
          />
          <div className="flex flex-col gap-2">
            <PayloadDisclosure label="content" value={data.content} />
            <PayloadDisclosure label="source" value={data.source} />
            <PayloadDisclosure label="theme" value={data.theme} />
          </div>
        </>
      ) : null}
    </SectionCard>
  );
}
