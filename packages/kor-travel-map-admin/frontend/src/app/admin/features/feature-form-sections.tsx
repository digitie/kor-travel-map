"use client";

import type { Map as MapLibreMap } from "maplibre-gl";
import type { ReactNode } from "react";

import type { CategorySummary } from "@/api/categories";
import type { KorTravelGeoCandidate } from "@/api/korTravelGeo";
import { AdminRegionAutoSearch } from "@/components/admin-region-autosearch";
import { FormField } from "@/components/ui/form-field-input";
import { FormSelect } from "@/components/ui/form-select";
import { FormTextArea } from "@/components/ui/form-textarea";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import {
  EVENT_STATUS_OPTIONS,
  FEATURE_KIND_OPTIONS,
  FEATURE_STATUS_OPTIONS,
  PLACE_KIND_OPTIONS,
  withCurrentOption,
} from "@/lib/feature-form-options";
import { httpUrl, phoneNumber } from "@/lib/form-validation";
import { cn } from "@/lib/utils";
import { isVWorldApiKeyConfigured } from "@/lib/vworld-style";
import { DEFAULT_VIEWPORT } from "@/state/map";

type CoordInput = { lon: number; lat: number } | null;

type FeatureFormKind = (typeof FEATURE_KIND_OPTIONS)[number]["value"];
type FeatureFormStatus = (typeof FEATURE_STATUS_OPTIONS)[number]["value"];

export interface FeatureAddressValues {
  addressAdmin: string;
  addressExtraJson: string;
  addressLegal: string;
  addressRoad: string;
  adminDongCode: string;
  legalDongCode: string;
  roadAddressManagementNo: string;
  roadNameCode: string;
  sidoCode: string;
  sigunguCode: string;
}

type FeatureAddressField = keyof FeatureAddressValues;

const ADDRESS_CODE_RULES: Record<
  Extract<
    FeatureAddressField,
    | "adminDongCode"
    | "legalDongCode"
    | "roadAddressManagementNo"
    | "roadNameCode"
    | "sidoCode"
    | "sigunguCode"
  >,
  { label: string; length: number }
> = {
  adminDongCode: { label: "행정동 코드", length: 10 },
  legalDongCode: { label: "법정동 코드", length: 10 },
  roadAddressManagementNo: { label: "도로명주소 관리번호", length: 25 },
  roadNameCode: { label: "도로명 코드", length: 12 },
  sidoCode: { label: "시도 코드", length: 2 },
  sigunguCode: { label: "시군구 코드", length: 5 },
};

export function addressCodeError(
  field: keyof typeof ADDRESS_CODE_RULES,
  value: string,
): string | undefined {
  const raw = value.trim();
  if (raw.length === 0) return undefined;
  const rule = ADDRESS_CODE_RULES[field];
  if (!/^\d+$/.test(raw)) {
    return `${rule.label}는 ${rule.length}자리 숫자여야 합니다.`;
  }
  if (raw.length !== rule.length) {
    return `${rule.label}는 ${rule.length}자리여야 합니다.`;
  }
  return undefined;
}

export function validateAddressCodes(
  values: Pick<FeatureAddressValues, keyof typeof ADDRESS_CODE_RULES>,
): void {
  for (const field of Object.keys(ADDRESS_CODE_RULES) as Array<
    keyof typeof ADDRESS_CODE_RULES
  >) {
    const error = addressCodeError(field, values[field]);
    if (error) throw new Error(error);
  }
}

export interface FeatureDetailValues {
  detailExtraJson: string;
  endDate: string;
  eventStatus: string;
  homepageUrl: string;
  organizer: string;
  phone: string;
  sourceUrl: string;
  startDate: string;
  urlsExtraJson: string;
  venue: string;
}

type FeatureDetailField = keyof FeatureDetailValues;

function categoryOptionLabel(category: CategorySummary): string {
  const path =
    category.path.length > 0 ? category.path.join(" > ") : category.label;
  return `${category.code} · ${path}`;
}

export function FeatureLocationPreviewSection({
  actions,
  apiKey,
  className,
  coord,
  heightClassName = "h-[28rem]",
  markerColor,
  markerIcon,
  testId,
  title,
  zoomWhenCoord = 13,
  onLoad,
  onMapClick,
}: {
  actions?: ReactNode;
  apiKey: string | undefined;
  className?: string;
  coord: CoordInput;
  heightClassName?: string;
  markerColor: string;
  markerIcon: string;
  testId: string;
  title: string;
  zoomWhenCoord?: number;
  onLoad?: (map: MapLibreMap) => void;
  onMapClick?: (coord: { lon: number; lat: number }) => void;
}) {
  const center: [number, number] = coord
    ? [coord.lon, coord.lat]
    : [DEFAULT_VIEWPORT.lon, DEFAULT_VIEWPORT.lat];
  const zoom = coord ? zoomWhenCoord : DEFAULT_VIEWPORT.zoom;

  return (
    <div className={cn("flex min-w-0 flex-col rounded-lg border bg-background", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 className="font-medium">좌표</h2>
          <p className="font-mono text-sm text-muted-foreground">
            {coord
              ? `${coord.lon.toFixed(6)}, ${coord.lat.toFixed(6)}`
              : "좌표 없음"}
          </p>
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
      <div className={cn("relative min-h-0 overflow-hidden", heightClassName)}>
        <VWorldMapView
          apiKey={apiKey}
          center={center}
          className="absolute inset-0 h-full w-full"
          key={`${center[0]}:${center[1]}:${zoom}`}
          navigation
          scale
          testId={testId}
          zoom={zoom}
          onClick={
            onMapClick
              ? (event) =>
                  onMapClick({
                    lon: event.lngLat.lng,
                    lat: event.lngLat.lat,
                  })
              : undefined
          }
          onLoad={onLoad}
        >
          {coord ? (
            <VWorldMarker
              lngLat={[coord.lon, coord.lat]}
              markerColor={markerColor}
              markerIcon={markerIcon}
              selected
              size={30}
              title={title}
            />
          ) : null}
        </VWorldMapView>
      </div>
      {!isVWorldApiKeyConfigured(apiKey) ? (
        <div className="border-t px-4 py-3 text-sm text-muted-foreground">
          VWorld key 미설정 상태라 회색 배경으로 표시합니다.
        </div>
      ) : null}
    </div>
  );
}

export function FeatureBasicInfoSection({
  actions,
  category,
  categoryError,
  categoryItems,
  className,
  idPrefix,
  kind,
  name,
  nameError,
  placeKind,
  required = false,
  status,
  onCategoryChange,
  onKindChange,
  onNameChange,
  onPlaceKindChange,
  onStatusChange,
}: {
  actions?: ReactNode;
  category: string;
  categoryError?: string;
  categoryItems: readonly CategorySummary[];
  className?: string;
  idPrefix: string;
  kind: string;
  name: string;
  nameError?: string;
  placeKind: string;
  required?: boolean;
  status: string;
  onCategoryChange: (value: string) => void;
  onKindChange: (value: FeatureFormKind) => void;
  onNameChange: (value: string) => void;
  onPlaceKindChange: (value: string) => void;
  onStatusChange: (value: FeatureFormStatus) => void;
}) {
  return (
    <section className={cn("rounded-lg border bg-background p-4", className)}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-medium">기본 정보</h2>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
      <div className="grid gap-3 lg:grid-cols-4">
        <FormSelect
          id={`${idPrefix}-kind`}
          label="Feature 종류"
          value={kind}
          onChange={(event) => onKindChange(event.target.value as FeatureFormKind)}
        >
          {FEATURE_KIND_OPTIONS.map((item) => (
            <NativeSelectOption key={item.value} value={item.value}>
              {item.label}
            </NativeSelectOption>
          ))}
        </FormSelect>
        {kind === "place" ? (
          <FormSelect
            id={`${idPrefix}-place-kind`}
            label="장소 종류"
            value={placeKind}
            onChange={(event) => onPlaceKindChange(event.target.value)}
          >
            {withCurrentOption(
              PLACE_KIND_OPTIONS,
              placeKind,
              "현재 장소 종류",
            ).map((option) => (
              <NativeSelectOption key={option.value} value={option.value}>
                {option.label}
              </NativeSelectOption>
            ))}
          </FormSelect>
        ) : null}
        <FormSelect
          id={`${idPrefix}-status`}
          label="상태"
          value={status}
          onChange={(event) =>
            onStatusChange(event.target.value as FeatureFormStatus)
          }
        >
          {FEATURE_STATUS_OPTIONS.map((item) => (
            <NativeSelectOption key={item.value} value={item.value}>
              {item.label}
            </NativeSelectOption>
          ))}
        </FormSelect>
        <FormField
          error={nameError}
          id={`${idPrefix}-name`}
          label="이름"
          required={required}
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
        />
        <FormSelect
          error={categoryError}
          id={`${idPrefix}-category`}
          label="카테고리"
          required={required}
          value={category}
          onChange={(event) => onCategoryChange(event.target.value)}
        >
          {category && !categoryItems.some((item) => item.code === category) ? (
            <NativeSelectOption value={category}>현재 값: {category}</NativeSelectOption>
          ) : null}
          {categoryItems.map((item) => (
            <NativeSelectOption key={item.code} value={item.code}>
              {categoryOptionLabel(item)}
            </NativeSelectOption>
          ))}
        </FormSelect>
      </div>
    </section>
  );
}

export function FeatureAddressSection({
  className,
  idPrefix,
  onSelectRegionCandidate,
  values,
  onChange,
}: {
  className?: string;
  idPrefix: string;
  onSelectRegionCandidate?: (candidate: KorTravelGeoCandidate) => void;
  values: FeatureAddressValues;
  onChange: (field: FeatureAddressField, value: string) => void;
}) {
  return (
    <div className={cn("rounded-lg border bg-background p-4", className)}>
      <h2 className="mb-4 font-medium">주소</h2>
      <div className="grid gap-3 md:grid-cols-2">
        <FormField
          id={`${idPrefix}-address-road`}
          label="도로명 주소"
          value={values.addressRoad}
          onChange={(event) => onChange("addressRoad", event.target.value)}
        />
        <FormField
          id={`${idPrefix}-address-legal`}
          label="법정동 주소"
          value={values.addressLegal}
          onChange={(event) => onChange("addressLegal", event.target.value)}
        />
        <FormField
          id={`${idPrefix}-address-admin`}
          label="행정동 주소"
          value={values.addressAdmin}
          onChange={(event) => onChange("addressAdmin", event.target.value)}
        />
        <AdminRegionAutoSearch
          id={`${idPrefix}-sido-code`}
          kind="sido"
          label="시도 코드"
          value={values.sidoCode}
          onChange={(value) => onChange("sidoCode", value)}
          onSelectCandidate={onSelectRegionCandidate}
          placeholder="시도명 또는 코드 검색"
        />
        <AdminRegionAutoSearch
          id={`${idPrefix}-sigungu-code`}
          kind="sigungu"
          label="시군구 코드"
          value={values.sigunguCode}
          onChange={(value) => onChange("sigunguCode", value)}
          onSelectCandidate={onSelectRegionCandidate}
        />
        <AdminRegionAutoSearch
          id={`${idPrefix}-legal-dong-code`}
          kind="legal_dong"
          label="법정동 코드"
          value={values.legalDongCode}
          onChange={(value) => onChange("legalDongCode", value)}
          onSelectCandidate={onSelectRegionCandidate}
        />
        <AdminRegionAutoSearch
          id={`${idPrefix}-admin-dong-code`}
          kind="admin_dong"
          label="행정동 코드"
          value={values.adminDongCode}
          onChange={(value) => onChange("adminDongCode", value)}
          onSelectCandidate={onSelectRegionCandidate}
        />
        <FormField
          error={addressCodeError("roadNameCode", values.roadNameCode)}
          id={`${idPrefix}-road-name-code`}
          inputMode="numeric"
          label="도로명 코드"
          value={values.roadNameCode}
          onChange={(event) => onChange("roadNameCode", event.target.value)}
        />
        <FormField
          className="md:col-span-2"
          error={addressCodeError(
            "roadAddressManagementNo",
            values.roadAddressManagementNo,
          )}
          id={`${idPrefix}-road-address-management-no`}
          inputMode="numeric"
          label="도로명주소 관리번호"
          value={values.roadAddressManagementNo}
          onChange={(event) =>
            onChange("roadAddressManagementNo", event.target.value)
          }
        />
      </div>
      <details className="mt-3 rounded-md border border-dashed p-3">
        <summary className="cursor-pointer text-sm font-medium">
          고급 추가 정보
        </summary>
        <FormTextArea
          className="mt-3"
          id={`${idPrefix}-address-extra-json`}
          label="주소 추가 정보"
          hint="정해진 입력칸에 없는 값만 JSON으로 입력합니다."
          value={values.addressExtraJson}
          onChange={(event) => onChange("addressExtraJson", event.target.value)}
        />
      </details>
    </div>
  );
}

export function FeatureDetailSection({
  className,
  errors,
  idPrefix,
  kind,
  values,
  onChange,
}: {
  className?: string;
  errors?: Partial<Record<FeatureDetailField, string>>;
  idPrefix: string;
  kind: string;
  values: FeatureDetailValues;
  onChange: (field: FeatureDetailField, value: string) => void;
}) {
  const phoneError = phoneNumber<FeatureDetailValues>()(values.phone, values);
  const homepageError = httpUrl<FeatureDetailValues>("홈페이지")(
    values.homepageUrl,
    values,
  );
  const sourceError = httpUrl<FeatureDetailValues>("출처")(
    values.sourceUrl,
    values,
  );

  return (
    <div className={cn("rounded-lg border bg-background p-4", className)}>
      <h2 className="mb-4 font-medium">상세</h2>
      {kind === "event" ? (
        <div className="grid gap-3 md:grid-cols-2">
          <FormField
            id={`${idPrefix}-start-date`}
            label="행사 시작"
            type="datetime-local"
            value={values.startDate}
            onChange={(event) => onChange("startDate", event.target.value)}
          />
          <FormField
            id={`${idPrefix}-end-date`}
            label="행사 종료"
            type="datetime-local"
            value={values.endDate}
            onChange={(event) => onChange("endDate", event.target.value)}
          />
          <FormSelect
            id={`${idPrefix}-event-status`}
            label="행사 상태"
            value={values.eventStatus}
            onChange={(event) => onChange("eventStatus", event.target.value)}
          >
            {withCurrentOption(
              EVENT_STATUS_OPTIONS,
              values.eventStatus,
              "현재 행사 상태",
            ).map((option) => (
              <NativeSelectOption key={option.value} value={option.value}>
                {option.label}
              </NativeSelectOption>
            ))}
          </FormSelect>
          <FormField
            id={`${idPrefix}-organizer`}
            label="주최"
            value={values.organizer}
            onChange={(event) => onChange("organizer", event.target.value)}
          />
          <FormField
            className="md:col-span-2"
            id={`${idPrefix}-venue`}
            label="행사 장소"
            value={values.venue}
            onChange={(event) => onChange("venue", event.target.value)}
          />
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <FormField
            error={errors?.phone ?? phoneError}
            id={`${idPrefix}-phone`}
            inputMode="tel"
            label="전화"
            placeholder="예: 02-123-4567"
            value={values.phone}
            onChange={(event) => onChange("phone", event.target.value)}
          />
        </div>
      )}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <FormField
          error={errors?.homepageUrl ?? homepageError}
          id={`${idPrefix}-homepage-url`}
          label="홈페이지"
          placeholder="https://example.kr"
          type="url"
          value={values.homepageUrl}
          onChange={(event) => onChange("homepageUrl", event.target.value)}
        />
        <FormField
          error={errors?.sourceUrl ?? sourceError}
          id={`${idPrefix}-source-url`}
          label="출처"
          placeholder="https://example.kr/source"
          type="url"
          value={values.sourceUrl}
          onChange={(event) => onChange("sourceUrl", event.target.value)}
        />
      </div>
      <details className="mt-3 rounded-md border border-dashed p-3">
        <summary className="cursor-pointer text-sm font-medium">
          고급 추가 정보
        </summary>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <FormTextArea
            id={`${idPrefix}-detail-extra-json`}
            label="상세 추가 정보"
            hint="정해진 입력칸에 없는 값만 JSON으로 입력합니다."
            value={values.detailExtraJson}
            onChange={(event) => onChange("detailExtraJson", event.target.value)}
          />
          <FormTextArea
            id={`${idPrefix}-urls-extra-json`}
            label="URL 추가 정보"
            hint="홈페이지/출처 외 추가 URL만 JSON으로 입력합니다."
            value={values.urlsExtraJson}
            onChange={(event) => onChange("urlsExtraJson", event.target.value)}
          />
        </div>
      </details>
    </div>
  );
}
