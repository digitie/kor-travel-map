"use client";

import {
  CalendarDaysIcon,
  ClipboardListIcon,
  RouteIcon,
  RulerIcon,
  ShapesIcon,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  useAreaContainedFeatures,
  type FeatureSummary,
} from "@/api/features";
import { FeaturePricePanel } from "@/components/feature-price-panel";
import { FeatureWeatherPanel } from "@/components/feature-weather-panel";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime, shortId } from "@/lib/format";

type DetailRecord = Record<string, unknown>;

export interface FeatureKindDetail {
  feature_id?: string;
  kind: string;
  name?: string;
  category?: string;
  detail: DetailRecord;
  area_square_meters?: number | null;
  updated_at?: string | null;
}

function textValue(detail: DetailRecord, key: string): string | null {
  const value = detail[key];
  if (typeof value === "string" && value.trim().length > 0) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function numberValue(detail: DetailRecord, key: string): number | null {
  const value = detail[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function objectValue(detail: DetailRecord, key: string): DetailRecord | null {
  const value = detail[key];
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as DetailRecord;
  }
  return null;
}

function arrayText(detail: DetailRecord, key: string): string | null {
  const value = detail[key];
  if (!Array.isArray(value) || value.length === 0) return null;
  return value.map((item) => String(item)).join(", ");
}

function formatArea(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toLocaleString("ko-KR", {
      maximumFractionDigits: 2,
    })} km2`;
  }
  return `${Math.round(value).toLocaleString("ko-KR")} m2`;
}

function formatDistance(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  if (value >= 1000) {
    return `${(value / 1000).toLocaleString("ko-KR", {
      maximumFractionDigits: 2,
    })} km`;
  }
  return `${Math.round(value).toLocaleString("ko-KR")} m`;
}

function formatDuration(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  if (hours <= 0) return `${minutes}분`;
  return minutes === 0 ? `${hours}시간` : `${hours}시간 ${minutes}분`;
}

function featureHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

function InfoRows({
  rows,
}: {
  rows: Array<[string, string | null | undefined]>;
}) {
  const visibleRows = rows.filter(([, value]) => value !== null && value !== undefined);
  if (visibleRows.length === 0) {
    return <div className="text-sm text-muted-foreground">표시할 상세값이 없습니다.</div>;
  }
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
      {visibleRows.map(([label, value]) => (
        <div className="contents" key={label}>
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PanelShell({
  title,
  description,
  badge,
  icon,
  children,
}: {
  title: string;
  description: string;
  badge?: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border bg-background">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 font-medium">
            <span className="text-muted-foreground">{icon}</span>
            {title}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">{description}</div>
        </div>
        {badge ? <Badge variant="secondary">{badge}</Badge> : null}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function EventDetailPanel({ feature }: { feature: FeatureKindDetail }) {
  const detail = feature.detail;
  const startsOn = textValue(detail, "starts_on");
  const endsOn = textValue(detail, "ends_on");
  const period =
    startsOn && endsOn ? `${startsOn} - ${endsOn}` : startsOn ?? endsOn ?? null;

  return (
    <PanelShell
      description="기간, 장소, 연락처 등 행사 메타"
      icon={<CalendarDaysIcon className="size-4" />}
      title="Event"
    >
      <InfoRows
        rows={[
          ["기간", period],
          ["종류", textValue(detail, "event_kind")],
          ["장소", textValue(detail, "venue_name")],
          ["전화", textValue(detail, "tel")],
          ["timezone", textValue(detail, "timezone")],
          ["content_id", textValue(detail, "content_id")],
          ["content_type", textValue(detail, "content_type_id")],
        ]}
      />
    </PanelShell>
  );
}

function AreaContainedList({ items }: { items: FeatureSummary[] }) {
  if (items.length === 0) {
    return <div className="text-sm text-muted-foreground">포함된 feature가 없습니다.</div>;
  }
  return (
    <div className="flex flex-col gap-2">
      {items.map((item) => (
        <Link
          className="rounded-md border bg-muted/30 px-3 py-2 text-sm hover:bg-muted"
          href={featureHref(item.feature_id)}
          key={item.feature_id}
        >
          <div className="flex min-w-0 items-center justify-between gap-2">
            <span className="truncate font-medium">{item.name}</span>
            <Badge variant="outline">{item.kind}</Badge>
          </div>
          <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
            {shortId(item.feature_id, 18)}
          </div>
        </Link>
      ))}
    </div>
  );
}

function AreaDetailPanel({
  featureId,
  feature,
  compact,
}: {
  featureId: string | null;
  feature: FeatureKindDetail;
  compact: boolean;
}) {
  const detail = feature.detail;
  const area =
    feature.area_square_meters ?? numberValue(detail, "area_square_meters");
  const contained = useAreaContainedFeatures(
    featureId,
    { pageSize: compact ? 8 : 25 },
    { enabled: Boolean(featureId) },
  );
  const items = contained.data?.data.items ?? [];

  return (
    <PanelShell
      badge={contained.data ? `${items.length}건` : undefined}
      description="면적과 공간 안의 feature"
      icon={<RulerIcon className="size-4" />}
      title="Area"
    >
      <div className="flex flex-col gap-4">
        <InfoRows
          rows={[
            ["면적", formatArea(area)],
            ["종류", textValue(detail, "area_kind")],
            ["boundary", textValue(detail, "boundary_source")],
            ["관리", textValue(detail, "administrative_office")],
            ["규제", textValue(detail, "regulation_scope")],
            ["설명", textValue(detail, "description")],
          ]}
        />
        {contained.isLoading ? <Skeleton className="h-32 w-full" /> : null}
        {contained.isError ? (
          <Alert variant="destructive">
            <AlertTitle>포함 feature 조회 실패</AlertTitle>
            <AlertDescription>{contained.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {!contained.isLoading && !contained.isError ? (
          <AreaContainedList items={items} />
        ) : null}
      </div>
    </PanelShell>
  );
}

function RouteDetailPanel({ feature }: { feature: FeatureKindDetail }) {
  const detail = feature.detail;
  return (
    <PanelShell
      description="구간, 거리, 난이도 등 route 메타"
      icon={<RouteIcon className="size-4" />}
      title="Route"
    >
      <InfoRows
        rows={[
          ["종류", textValue(detail, "route_type")],
          ["거리", formatDistance(numberValue(detail, "total_distance_meters"))],
          ["예상 시간", formatDuration(numberValue(detail, "expected_duration_minutes"))],
          ["난이도", textValue(detail, "difficulty")],
          ["시작", textValue(detail, "begin_name")],
          ["시작 주소", textValue(detail, "begin_address")],
          ["종료", textValue(detail, "end_name")],
          ["종료 주소", textValue(detail, "end_address")],
          ["geometry", textValue(detail, "geometry_status")],
        ]}
      />
    </PanelShell>
  );
}

function isMoisPlaceDetail(feature: FeatureKindDetail): boolean {
  if (feature.kind !== "place") return false;
  const payload = objectValue(feature.detail, "payload");
  const facilityInfo = objectValue(feature.detail, "facility_info");
  return Boolean(payload?.mng_no || facilityInfo?.service_slug);
}

function MoisPlaceDetailPanel({ feature }: { feature: FeatureKindDetail }) {
  const detail = feature.detail;
  const payload = objectValue(detail, "payload") ?? {};
  const facilityInfo = objectValue(detail, "facility_info") ?? {};
  const building = objectValue(facilityInfo, "building");
  const food = objectValue(facilityInfo, "food");
  const medical = objectValue(facilityInfo, "medical");
  const cultureSports = objectValue(facilityInfo, "culture_sports");

  return (
    <PanelShell
      description="행정안전부 지방행정 인허가 상세"
      icon={<ClipboardListIcon className="size-4" />}
      title="MOIS place"
    >
      <div className="flex flex-col gap-4">
        <InfoRows
          rows={[
            ["상호", feature.name],
            ["인허가 업종", textValue(payload, "title")],
            ["영업상태", textValue(payload, "status_name")],
            ["상세상태", textValue(payload, "detail_status_name")],
            ["인허가일", textValue(detail, "license_date")],
            ["관리번호", textValue(payload, "mng_no")],
            ["개방자치단체", textValue(payload, "opn_authority_code")],
            ["place_kind", textValue(detail, "place_kind")],
            ["category", feature.category],
            ["MOIS 분류", textValue(facilityInfo, "category")],
            ["service_slug", textValue(facilityInfo, "service_slug")],
            ["세부업종", textValue(facilityInfo, "subtype_name")],
            ["영업방식", textValue(facilityInfo, "sales_method_name")],
            ["전화", arrayText(detail, "phones")],
          ]}
        />
        <div className="grid gap-3">
          {building ? (
            <details open>
              <summary className="cursor-pointer text-sm font-medium">
                facility_info.building
              </summary>
              <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(building, null, 2)}
              </pre>
            </details>
          ) : null}
          {food ? (
            <details open>
              <summary className="cursor-pointer text-sm font-medium">
                facility_info.food
              </summary>
              <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(food, null, 2)}
              </pre>
            </details>
          ) : null}
          {medical ? (
            <details>
              <summary className="cursor-pointer text-sm font-medium">
                facility_info.medical
              </summary>
              <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(medical, null, 2)}
              </pre>
            </details>
          ) : null}
          {cultureSports ? (
            <details>
              <summary className="cursor-pointer text-sm font-medium">
                facility_info.culture_sports
              </summary>
              <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(cultureSports, null, 2)}
              </pre>
            </details>
          ) : null}
        </div>
      </div>
    </PanelShell>
  );
}

function GenericDetailPanel({ feature }: { feature: FeatureKindDetail }) {
  return (
    <PanelShell
      description="kind 전용 상세 화면이 아직 없는 feature"
      icon={<ShapesIcon className="size-4" />}
      title="Feature"
    >
      <InfoRows
        rows={[
          ["kind", feature.kind],
          ["category", feature.category],
          ["updated", formatDateTime(feature.updated_at ?? null)],
        ]}
      />
    </PanelShell>
  );
}

export function FeatureKindDetailPanel({
  featureId,
  feature,
  compact = false,
}: {
  featureId: string | null;
  feature: FeatureKindDetail | null | undefined;
  compact?: boolean;
}) {
  if (!feature) return null;
  if (feature.kind === "price") {
    return <FeaturePricePanel compact={compact} featureId={featureId} />;
  }
  if (feature.kind === "weather") {
    return <FeatureWeatherPanel compact={compact} featureId={featureId} />;
  }
  if (feature.kind === "event") {
    return <EventDetailPanel feature={feature} />;
  }
  if (feature.kind === "area") {
    return (
      <AreaDetailPanel compact={compact} feature={feature} featureId={featureId} />
    );
  }
  if (feature.kind === "route") {
    return <RouteDetailPanel feature={feature} />;
  }
  if (isMoisPlaceDetail(feature)) {
    return <MoisPlaceDetailPanel feature={feature} />;
  }
  return <GenericDetailPanel feature={feature} />;
}
