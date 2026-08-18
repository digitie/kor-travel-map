"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import {
  useCuratedFeatureDetailSnapshot,
  type CuratedFeature,
} from "@/api/curated";
import { JsonViewer } from "@/components/json-viewer";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import { formatCount, formatDateTime, shortId } from "@/lib/format";

// T-VN-40A: 이 모듈에 있던 legacy write UI(CuratedPlaceSearchPanel — feature_id 교체 patch,
// FeatureEditor — rank/relation/reuse_policy/title patch)는 fence로 410이 됐고 삭제했다.
// 남은 것은 read 패널(위치·상세 미리보기)뿐이며 40C에서 legacy 표와 함께 지운다.

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;

function JsonBlock({ value }: { value: unknown }) {
  return <JsonViewer value={value} maxHeight="lg" copyable />;
}



function coordLabel(feature: CuratedFeature): string {
  const coord = featureCoord(feature);
  if (coord) {
    const [lon, lat] = coord;
    return `${lon.toFixed(5)}, ${lat.toFixed(5)}`;
  }
  return "-";
}

function featureCoord(feature: CuratedFeature): [number, number] | null {
  if (feature.lon == null || feature.lat == null) return null;
  const lon = Number(feature.lon);
  const lat = Number(feature.lat);
  return Number.isFinite(lon) && Number.isFinite(lat) ? [lon, lat] : null;
}


function uiLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return value
    .replace(/kor-travel-concierge/gi, "place-candidate")
    .replace(/concierge/gi, "place-candidate")
    .replace(/컨시어지/g, "장소 후보");
}

function providerLabel(value: string | null | undefined): string {
  return uiLabel(value);
}


function featureAddressLabel(feature: CuratedFeature): string {
  const address = feature.address as Record<string, unknown>;
  for (const key of ["road_address", "jibun_address", "full_address", "address"]) {
    const value = address[key];
    if (typeof value === "string" && value.trim().length > 0) return value;
  }
  return "-";
}

export function CuratedFeatureLocationPanel({
  feature,
}: {
  feature: CuratedFeature | null;
}) {
  if (!feature) return null;
  const coord = featureCoord(feature);

  return (
    <section className="rounded-lg border bg-background">
      <div className="border-b px-4 py-3">
        <div className="font-medium">위치 확인</div>
      </div>
      <div className="flex flex-col gap-3 p-4">
        {coord ? (
          <div className="relative h-80 overflow-hidden rounded-md border 2xl:h-96">
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
                markerColor="#2563eb"
                selected
                size={30}
                title={feature.feature_name}
              />
            </VWorldMapView>
          </div>
        ) : (
          <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            좌표가 없어 지도 marker를 표시할 수 없습니다.
          </div>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">좌표</dt>
          <dd className="font-mono">{coordLabel(feature)}</dd>
          <dt className="text-muted-foreground">주소</dt>
          <dd>{featureAddressLabel(feature)}</dd>
          <dt className="text-muted-foreground">카테고리</dt>
          <dd>
            <Badge variant="outline">{feature.feature_category}</Badge>
          </dd>
          <dt className="text-muted-foreground">provider</dt>
          <dd>
            {providerLabel(feature.provider)} / {feature.dataset_key}
          </dd>
        </dl>
      </div>
    </section>
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
        cell: ({ row }) => row.original.sort_order,
      },
      {
        accessorKey: "relation",
        header: "관계",
        cell: ({ row }) => (
          <Badge variant="outline">{row.original.relation}</Badge>
        ),
      },
      {
        accessorKey: "feature_id",
        header: "feature",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-[12rem] whitespace-normal break-all font-mono text-xs">
            {row.original.feature_id}
          </span>
        ),
      },
      {
        id: "memo",
        header: "메모",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-[12rem] whitespace-normal">
            {row.original.memo ?? "-"}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <section className="rounded-lg border bg-background">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div>
          <div className="font-medium">배포 스냅샷 미리보기</div>
          <div className="text-xs text-muted-foreground">
            다운스트림(PinVi 등)이 복사해 가는 최종 payload — version/etag로
            변경을 감지합니다.
          </div>
        </div>
        {data ? (
          <Badge variant="outline">etag {shortId(data.etag, 10)}</Badge>
        ) : null}
      </div>
      {!feature ? (
        <div className="p-4 text-sm text-muted-foreground">
          후보를 선택하면 배포 스냅샷을 조회합니다.
        </div>
      ) : null}
      {snapshot.isLoading ? <Skeleton className="m-4 h-40" /> : null}
      {snapshot.isError ? (
        <Alert className="m-4" variant="destructive">
          <AlertTitle>배포 스냅샷 조회 실패</AlertTitle>
          <AlertDescription>{snapshot.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {data ? (
        <div className="flex flex-col gap-4 p-4">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">version</dt>
            <dd>{data.version}</dd>
            <dt className="text-muted-foreground">수정 시각</dt>
            <dd>{formatDateTime(data.updated_at)}</dd>
            <dt className="text-muted-foreground">items</dt>
            <dd>{formatCount(data.items.length)}</dd>
          </dl>
          <DataTable
            columns={itemColumns}
            data={data.items}
            getRowId={(item) => item.curated_feature_item_id}
            emptyMessage="detail item이 없습니다."
            manualSorting={false}
          />
          <details>
            <summary className="cursor-pointer text-sm font-medium">content</summary>
            <JsonBlock value={data.content} />
          </details>
          <details>
            <summary className="cursor-pointer text-sm font-medium">source</summary>
            <JsonBlock value={data.source} />
          </details>
          <details>
            <summary className="cursor-pointer text-sm font-medium">theme</summary>
            <JsonBlock value={data.theme} />
          </details>
        </div>
      ) : null}
    </section>
  );
}
