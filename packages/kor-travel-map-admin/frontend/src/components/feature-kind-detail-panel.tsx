"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (detail) · design-system: design.md · designed-as-app

import Link from "next/link";
import type { ReactNode } from "react";

import {
  useAreaContainedFeatures,
  type FeatureSummary,
} from "@/api/features";
import { DetailList, type DetailItem } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { FeaturePricePanel } from "@/components/feature-price-panel";
import { FeatureWeatherPanel } from "@/components/feature-weather-panel";
import { JsonViewer } from "@/components/json-viewer";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";

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
  if (typeof value !== "number" || !Number.isFinite(value)) return NULL_GLYPH;
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toLocaleString("ko-KR", {
      maximumFractionDigits: 2,
    })} km2`;
  }
  return `${Math.round(value).toLocaleString("ko-KR")} m2`;
}

function formatDistance(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return NULL_GLYPH;
  if (value >= 1000) {
    return `${(value / 1000).toLocaleString("ko-KR", {
      maximumFractionDigits: 2,
    })} km`;
  }
  return `${Math.round(value).toLocaleString("ko-KR")} m`;
}

function formatDuration(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return NULL_GLYPH;
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  if (hours <= 0) return `${minutes}분`;
  return minutes === 0 ? `${hours}시간` : `${hours}시간 ${minutes}분`;
}

function featureHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

/**
 * kind 상세 key-value — DetailList(inline `라벨 | 값`)만 쓴다(m9). 값이 없는 행은 빼고,
 * 남는 행이 없으면 EmptyState 한 문장.
 */
function InfoRows({
  rows,
}: {
  rows: Array<[string, string | null | undefined, { mono?: boolean }?]>;
}) {
  const items: DetailItem[] = rows
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([label, value, options]) => ({
      label,
      value,
      mono: options?.mono,
    }));
  if (items.length === 0) {
    return <EmptyState size="sm" title="표시할 상세값이 없습니다." />;
  }
  return <DetailList items={items} layout="inline" />;
}

/**
 * kind 패널의 flush 섹션(카드 없음): 제목(h3 15px/600) + 한 줄 설명 + 우측 건수(muted 텍스트).
 * 지도 위 floating 패널(compact)과 상세 rail 양쪽에서 같은 모양이다.
 */
function PanelShell({
  title,
  description,
  count,
  children,
}: {
  title: string;
  description: string;
  count?: string;
  children: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h3 className="text-sm leading-snug font-semibold text-text-primary">{title}</h3>
        {count ? (
          <span className="text-xs text-text-secondary tabular-nums">{count}</span>
        ) : null}
        <p className="basis-full text-xs text-text-secondary">{description}</p>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function EventDetailPanel({ feature }: { feature: FeatureKindDetail }) {
  const detail = feature.detail;
  const startsOn = textValue(detail, "starts_on");
  const endsOn = textValue(detail, "ends_on");
  const period =
    startsOn && endsOn ? `${startsOn} – ${endsOn}` : startsOn ?? endsOn ?? null;

  return (
    <PanelShell description="기간, 장소, 연락처 등 행사 메타" title="Event">
      <InfoRows
        rows={[
          ["기간", period],
          ["종류", textValue(detail, "event_kind")],
          ["장소", textValue(detail, "venue_name")],
          ["전화", textValue(detail, "tel")],
          ["timezone", textValue(detail, "timezone"), { mono: true }],
          ["content_id", textValue(detail, "content_id"), { mono: true }],
          ["content_type", textValue(detail, "content_type_id"), { mono: true }],
        ]}
      />
    </PanelShell>
  );
}

function AreaContainedList({ items }: { items: FeatureSummary[] }) {
  if (items.length === 0) {
    return (
      <EmptyState
        description="이 구역 경계 안에 위치한 feature가 없습니다."
        size="sm"
        title="포함된 feature가 없습니다."
      />
    );
  }
  return (
    <ul className="divide-y divide-border">
      {items.map((item) => (
        <li key={item.feature_id}>
          <Link
            className="-mx-2 flex flex-col gap-0.5 rounded-control px-2 py-2 text-sm text-text-primary transition-colors outline-none hover:bg-surface-subtle focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus active:bg-surface-muted"
            href={featureHref(item.feature_id)}
          >
            <span className="flex min-w-0 items-center justify-between gap-2">
              <span className="truncate font-medium">{item.name}</span>
              <Badge variant="neutral">{item.kind}</Badge>
            </span>
            <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
              {shortId(item.feature_id, 18)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
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
      count={contained.data ? `${formatCount(items.length)}건` : undefined}
      description="면적과 공간 안의 feature"
      title="Area"
    >
      <div className="flex flex-col gap-4">
        <InfoRows
          rows={[
            ["면적", formatArea(area)],
            ["종류", textValue(detail, "area_kind")],
            ["boundary", textValue(detail, "boundary_source"), { mono: true }],
            ["관리", textValue(detail, "administrative_office")],
            ["규제", textValue(detail, "regulation_scope")],
            ["설명", textValue(detail, "description")],
          ]}
        />
        {contained.isLoading ? (
          <div aria-busy="true" className="flex flex-col gap-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        ) : null}
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
    <PanelShell description="구간, 거리, 난이도 등 route 메타" title="Route">
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
          ["geometry", textValue(detail, "geometry_status"), { mono: true }],
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

function FacilityDisclosure({
  label,
  value,
  defaultOpen = false,
}: {
  label: string;
  value: DetailRecord | null;
  defaultOpen?: boolean;
}) {
  if (!value) return null;
  return (
    <details className="group/details" open={defaultOpen}>
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
        <JsonViewer maxHeight="sm" value={value} />
      </div>
    </details>
  );
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
    <PanelShell description="행정안전부 지방행정 인허가 상세" title="MOIS place">
      <div className="flex flex-col gap-4">
        <InfoRows
          rows={[
            ["상호", feature.name],
            ["인허가 업종", textValue(payload, "title")],
            ["영업상태", textValue(payload, "status_name")],
            ["상세상태", textValue(payload, "detail_status_name")],
            ["인허가일", textValue(detail, "license_date")],
            ["관리번호", textValue(payload, "mng_no"), { mono: true }],
            ["개방자치단체", textValue(payload, "opn_authority_code"), { mono: true }],
            ["place_kind", textValue(detail, "place_kind"), { mono: true }],
            ["category", feature.category, { mono: true }],
            ["MOIS 분류", textValue(facilityInfo, "category")],
            ["service_slug", textValue(facilityInfo, "service_slug"), { mono: true }],
            ["세부업종", textValue(facilityInfo, "subtype_name")],
            ["영업방식", textValue(facilityInfo, "sales_method_name")],
            ["전화", arrayText(detail, "phones")],
          ]}
        />
        <div className="flex flex-col gap-2">
          <FacilityDisclosure defaultOpen label="facility_info.building" value={building} />
          <FacilityDisclosure defaultOpen label="facility_info.food" value={food} />
          <FacilityDisclosure label="facility_info.medical" value={medical} />
          <FacilityDisclosure label="facility_info.culture_sports" value={cultureSports} />
        </div>
      </div>
    </PanelShell>
  );
}

function noticeStartOriginLabel(value: string | null): string | null {
  if (value === "source") return "원천 시간";
  if (value === "first_probe") return "최초 probing";
  return value;
}

function NoticeDetailPanel({ feature }: { feature: FeatureKindDetail }) {
  const detail = feature.detail;
  const payload = objectValue(detail, "payload") ?? {};

  return (
    <PanelShell description="공지 시간, 출처, 도로 돌발 메타" title="Notice">
      <InfoRows
        rows={[
          ["종류", textValue(detail, "notice_type")],
          ["시작", formatDateTime(textValue(detail, "valid_start_time"))],
          ["시작 기준", noticeStartOriginLabel(textValue(payload, "valid_start_origin"))],
          ["종료", formatDateTime(textValue(detail, "valid_end_time"))],
          ["발령 기관", textValue(detail, "source_agency")],
          ["심각도", textValue(detail, "severity")],
          ["노선", textValue(payload, "route_name") ?? textValue(payload, "route_no")],
          ["방향", textValue(payload, "direction")],
          ["위치", textValue(payload, "point_name")],
          ["상태", textValue(payload, "process_status")],
          ["설명", textValue(payload, "description")],
        ]}
      />
    </PanelShell>
  );
}

function GenericDetailPanel({ feature }: { feature: FeatureKindDetail }) {
  return (
    <PanelShell description="kind 전용 상세 화면이 아직 없는 feature" title="Feature">
      <InfoRows
        rows={[
          ["kind", feature.kind, { mono: true }],
          ["category", feature.category, { mono: true }],
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
  if (feature.kind === "notice") {
    return <NoticeDetailPanel feature={feature} />;
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
