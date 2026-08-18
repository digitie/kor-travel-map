"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (form) · design-system: design.md · designed-as-app

import type { Map as MapLibreMap } from "maplibre-gl";
import type { ReactNode } from "react";

import type { CategorySummary } from "@/api/categories";
import type { KorTravelGeoCandidate } from "@/api/korTravelGeo";
import { AdminRegionAutoSearch } from "@/components/admin-region-autosearch";
import { SectionCard } from "@/components/section-card";
import { FormField } from "@/components/ui/form-field-input";
import { FormSelect } from "@/components/ui/form-select";
import { FormTextArea } from "@/components/ui/form-textarea";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import {
  addressCodeError,
  type FeatureAddressField,
  type FeatureAddressValues,
} from "@/lib/feature-address-validation";
import {
  EVENT_STATUS_OPTIONS,
  FEATURE_KIND_OPTIONS,
  PLACE_KIND_OPTIONS,
  withCurrentOption,
} from "@/lib/feature-form-options";
import {
  dateOrdered,
  httpUrl,
  jsonObject,
  phoneNumber,
} from "@/lib/form-validation";
import { NULL_GLYPH } from "@/lib/format";
import { cn } from "@/lib/utils";
import { isVWorldApiKeyConfigured } from "@/lib/vworld-style";
import { DEFAULT_VIEWPORT } from "@/state/map";

type CoordInput = { lon: number; lat: number } | null;

type FeatureFormKind = (typeof FEATURE_KIND_OPTIONS)[number]["value"];
type FeatureLifecycleState = "active" | "retired";
type FeaturePublicationState = "draft" | "published" | "suppressed";
type FeatureQualityState = "valid" | "quarantined";

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

/** "고급 추가 정보" 접이식 블록 — dashed 박스 대신 flat details(C3/M17). summary는 12px/500. */
function AdvancedDisclosure({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <details className={cn("group/details", className)}>
      <summary className="inline-flex h-control-sm cursor-pointer list-none items-center gap-1 rounded-control text-xs font-medium text-text-secondary select-none hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="w-3 text-text-tertiary group-open/details:hidden">
          +
        </span>
        <span aria-hidden="true" className="hidden w-3 text-text-tertiary group-open/details:inline">
          −
        </span>
        고급 추가 정보
      </summary>
      <div className="pt-3">{children}</div>
    </details>
  );
}

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
    <SectionCard
      actions={actions}
      className={cn("min-w-0", className)}
      contentClassName="space-y-3"
      description={
        <span className="font-mono tabular-nums slashed-zero">
          {coord ? `${coord.lon.toFixed(6)}, ${coord.lat.toFixed(6)}` : `좌표 ${NULL_GLYPH}`}
        </span>
      }
      title="좌표"
    >
      <div
        className={cn(
          "relative min-h-0 overflow-hidden rounded-control bg-surface-subtle",
          heightClassName,
        )}
      >
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
        <p className="text-xs text-text-secondary">
          VWorld key 미설정 상태라 회색 배경으로 표시합니다.
        </p>
      ) : null}
    </SectionCard>
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
  lifecycleState,
  publicationState,
  qualityState,
  showStateControls = true,
  onCategoryChange,
  onKindChange,
  onNameChange,
  onPlaceKindChange,
  onLifecycleStateChange,
  onPublicationStateChange,
  onQualityStateChange,
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
  lifecycleState: FeatureLifecycleState;
  publicationState: FeaturePublicationState;
  qualityState: FeatureQualityState;
  showStateControls?: boolean;
  onCategoryChange: (value: string) => void;
  onKindChange: (value: FeatureFormKind) => void;
  onNameChange: (value: string) => void;
  onPlaceKindChange: (value: string) => void;
  onLifecycleStateChange: (value: FeatureLifecycleState) => void;
  onPublicationStateChange: (value: FeaturePublicationState) => void;
  onQualityStateChange: (value: FeatureQualityState) => void;
}) {
  return (
    <SectionCard actions={actions} className={className} title="기본 정보">
      <div className="grid gap-x-3 gap-y-1 lg:grid-cols-4">
        <FormSelect
          aria-label={`${idPrefix} kind`}
          id={`${idPrefix}-kind`}
          label="Feature 종류"
          value={kind}
          onChange={(event) =>
            onKindChange(event.target.value as FeatureFormKind)
          }
        >
          {FEATURE_KIND_OPTIONS.map((item) => (
            <NativeSelectOption key={item.value} value={item.value}>
              {item.label}
            </NativeSelectOption>
          ))}
        </FormSelect>
        {kind === "place" ? (
          <FormSelect
            aria-label={`${idPrefix} place kind`}
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
        {showStateControls ? (
          <>
            <FormSelect
              aria-label={`${idPrefix} lifecycle state`}
              id={`${idPrefix}-lifecycle-state`}
              label="수명"
              value={lifecycleState}
              onChange={(event) =>
                onLifecycleStateChange(
                  event.target.value as FeatureLifecycleState,
                )
              }
            >
              <NativeSelectOption value="active">운영</NativeSelectOption>
              <NativeSelectOption value="retired">종료</NativeSelectOption>
            </FormSelect>
            <FormSelect
              aria-label={`${idPrefix} publication state`}
              id={`${idPrefix}-publication-state`}
              label="공개"
              value={publicationState}
              onChange={(event) =>
                onPublicationStateChange(
                  event.target.value as FeaturePublicationState,
                )
              }
            >
              <NativeSelectOption value="draft">초안</NativeSelectOption>
              <NativeSelectOption value="published">공개</NativeSelectOption>
              <NativeSelectOption value="suppressed">비공개</NativeSelectOption>
            </FormSelect>
            <FormSelect
              aria-label={`${idPrefix} quality state`}
              id={`${idPrefix}-quality-state`}
              label="품질"
              value={qualityState}
              onChange={(event) =>
                onQualityStateChange(event.target.value as FeatureQualityState)
              }
            >
              <NativeSelectOption value="valid">유효</NativeSelectOption>
              <NativeSelectOption value="quarantined">격리</NativeSelectOption>
            </FormSelect>
          </>
        ) : null}
        <FormField
          aria-label={`${idPrefix} name`}
          error={nameError}
          id={`${idPrefix}-name`}
          label="이름"
          required={required}
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
        />
        <FormSelect
          aria-label={`${idPrefix} category`}
          error={categoryError}
          id={`${idPrefix}-category`}
          label="카테고리"
          required={required}
          value={category}
          onChange={(event) => onCategoryChange(event.target.value)}
        >
          {category && !categoryItems.some((item) => item.code === category) ? (
            <NativeSelectOption value={category}>
              현재 값: {category}
            </NativeSelectOption>
          ) : null}
          {categoryItems.map((item) => (
            <NativeSelectOption key={item.code} value={item.code}>
              {categoryOptionLabel(item)}
            </NativeSelectOption>
          ))}
        </FormSelect>
      </div>
    </SectionCard>
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
    <SectionCard className={className} title="주소">
      <div className="grid gap-x-3 gap-y-1 md:grid-cols-2">
        <FormField
          aria-label={`${idPrefix} road address`}
          id={`${idPrefix}-address-road`}
          label="도로명 주소"
          value={values.addressRoad}
          onChange={(event) => onChange("addressRoad", event.target.value)}
        />
        <FormField
          aria-label={`${idPrefix} legal address`}
          id={`${idPrefix}-address-legal`}
          label="법정동 주소"
          value={values.addressLegal}
          onChange={(event) => onChange("addressLegal", event.target.value)}
        />
        <FormField
          aria-label={`${idPrefix} admin address`}
          id={`${idPrefix}-address-admin`}
          label="행정동 주소"
          value={values.addressAdmin}
          onChange={(event) => onChange("addressAdmin", event.target.value)}
        />
        <AdminRegionAutoSearch
          ariaLabel={`${idPrefix} sido code`}
          id={`${idPrefix}-sido-code`}
          kind="sido"
          label="시도 코드"
          value={values.sidoCode}
          onChange={(value) => onChange("sidoCode", value)}
          onSelectCandidate={onSelectRegionCandidate}
          placeholder="시도명 또는 코드 검색"
        />
        <AdminRegionAutoSearch
          ariaLabel={`${idPrefix} sigungu code`}
          id={`${idPrefix}-sigungu-code`}
          kind="sigungu"
          label="시군구 코드"
          value={values.sigunguCode}
          onChange={(value) => onChange("sigunguCode", value)}
          onSelectCandidate={onSelectRegionCandidate}
        />
        <AdminRegionAutoSearch
          ariaLabel={`${idPrefix} legal dong code`}
          id={`${idPrefix}-legal-dong-code`}
          kind="legal_dong"
          label="법정동 코드"
          value={values.legalDongCode}
          onChange={(value) => onChange("legalDongCode", value)}
          onSelectCandidate={onSelectRegionCandidate}
        />
        <AdminRegionAutoSearch
          ariaLabel={`${idPrefix} admin dong code`}
          id={`${idPrefix}-admin-dong-code`}
          kind="admin_dong"
          label="행정동 코드"
          value={values.adminDongCode}
          onChange={(value) => onChange("adminDongCode", value)}
          onSelectCandidate={onSelectRegionCandidate}
        />
        <FormField
          aria-label={`${idPrefix} road name code`}
          error={addressCodeError("roadNameCode", values.roadNameCode)}
          id={`${idPrefix}-road-name-code`}
          inputMode="numeric"
          label="도로명 코드"
          value={values.roadNameCode}
          onChange={(event) => onChange("roadNameCode", event.target.value)}
        />
        <FormField
          aria-label={`${idPrefix} road address management no`}
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
      <AdvancedDisclosure>
        <FormTextArea
          aria-label={`${idPrefix} address JSON`}
          error={jsonObject<FeatureAddressValues>()(
            values.addressExtraJson,
            values,
          )}
          id={`${idPrefix}-address-extra-json`}
          label="주소 추가 정보"
          hint="정해진 입력칸에 없는 값만 JSON object로 입력합니다."
          placeholder='예: {"zipcode": "03187"}'
          value={values.addressExtraJson}
          onChange={(event) => onChange("addressExtraJson", event.target.value)}
        />
      </AdvancedDisclosure>
    </SectionCard>
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
    <SectionCard className={className} title="상세">
      {kind === "event" ? (
        <div className="grid gap-x-3 gap-y-1 md:grid-cols-2">
          <FormField
            aria-label={`${idPrefix} event start`}
            error={dateOrdered<FeatureDetailValues>("endDate")(
              values.startDate,
              values,
            )}
            id={`${idPrefix}-start-date`}
            label="행사 시작"
            type="datetime-local"
            value={values.startDate}
            onChange={(event) => onChange("startDate", event.target.value)}
          />
          <FormField
            aria-label={`${idPrefix} event end`}
            id={`${idPrefix}-end-date`}
            label="행사 종료"
            type="datetime-local"
            value={values.endDate}
            onChange={(event) => onChange("endDate", event.target.value)}
          />
          <FormSelect
            aria-label={`${idPrefix} event status`}
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
        <div className="grid gap-x-3 gap-y-1 md:grid-cols-2">
          <FormField
            aria-label={`${idPrefix} phone`}
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
      <div className="grid gap-x-3 gap-y-1 md:grid-cols-2">
        <FormField
          aria-label={`${idPrefix} homepage url`}
          error={errors?.homepageUrl ?? homepageError}
          id={`${idPrefix}-homepage-url`}
          label="홈페이지"
          placeholder="https://example.kr"
          type="url"
          value={values.homepageUrl}
          onChange={(event) => onChange("homepageUrl", event.target.value)}
        />
        <FormField
          aria-label={`${idPrefix} source url`}
          error={errors?.sourceUrl ?? sourceError}
          id={`${idPrefix}-source-url`}
          label="출처"
          placeholder="https://example.kr/source"
          type="url"
          value={values.sourceUrl}
          onChange={(event) => onChange("sourceUrl", event.target.value)}
        />
      </div>
      <AdvancedDisclosure>
        <div className="grid gap-x-3 gap-y-1 md:grid-cols-2">
          <FormTextArea
            aria-label={`${idPrefix} detail JSON`}
            error={jsonObject<FeatureDetailValues>()(
              values.detailExtraJson,
              values,
            )}
            id={`${idPrefix}-detail-extra-json`}
            label="상세 추가 정보"
            hint="정해진 입력칸에 없는 값만 JSON object로 입력합니다."
            placeholder='예: {"capacity": 120}'
            value={values.detailExtraJson}
            onChange={(event) =>
              onChange("detailExtraJson", event.target.value)
            }
          />
          <FormTextArea
            aria-label={`${idPrefix} urls JSON`}
            error={jsonObject<FeatureDetailValues>()(
              values.urlsExtraJson,
              values,
            )}
            id={`${idPrefix}-urls-extra-json`}
            label="URL 추가 정보"
            hint="홈페이지/출처 외 추가 URL만 JSON object로 입력합니다."
            placeholder='예: {"instagram": "https://…"}'
            value={values.urlsExtraJson}
            onChange={(event) => onChange("urlsExtraJson", event.target.value)}
          />
        </div>
      </AdvancedDisclosure>
    </SectionCard>
  );
}
