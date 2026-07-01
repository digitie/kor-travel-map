"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  CheckIcon,
  ClipboardListIcon,
  MapPinIcon,
  PlusIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SearchIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useDeferredValue,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { useCategories, type CategorySummary } from "@/api/categories";
import {
  type AdminFeatureChangeAction,
  type AdminFeatureChangeRecord,
  type AdminFeatureChangeStatus,
  type AdminFeatureDetailData,
  type AdminFeatureCreateRequest,
  type AdminFeaturePatchRequest,
  useAdminFeatureDetail,
  useAdminFeatureChangeRequests,
  useApproveAdminFeatureChangeMutation,
  useCreateAdminFeatureMutation,
  useDeleteAdminFeatureMutation,
  usePatchAdminFeatureMutation,
  useRejectAdminFeatureChangeMutation,
} from "@/api/features";
import {
  korTravelGeoCandidateToAddressRecord,
  korTravelGeoCandidateToCoord,
  korTravelGeoCodesFromCandidate,
  reverseGeocode,
  type KorTravelGeoCandidate,
} from "@/api/korTravelGeo";
import { AdminShell } from "@/components/admin-shell";
import { AdminRegionAutoSearch } from "@/components/admin-region-autosearch";
import { StatusBadge, statusLabel } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { DataTable } from "@/components/ui/data-table";
import { FormField } from "@/components/ui/form-field-input";
import { FormSelect } from "@/components/ui/form-select";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import {
  FEATURE_CHANGE_ACTION_OPTIONS,
  FEATURE_KIND_OPTIONS,
  FEATURE_STATUS_OPTIONS,
  MARKER_COLOR_OPTIONS,
  MARKER_ICON_OPTIONS,
  markerColorSelectStyle,
  markerIconLabel,
  readableTextColor,
} from "@/lib/feature-form-options";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import {
  KOREA_COORD_MESSAGE,
  httpUrl,
  isKoreaCoordinate,
  phoneNumber,
} from "@/lib/form-validation";
import { cn } from "@/lib/utils";
import { DEFAULT_VIEWPORT } from "@/state/map";

import {
  FeatureAddressSection,
  FeatureBasicInfoSection,
  FeatureDetailSection,
  FeatureLocationPreviewSection,
  addressCodeError,
  validateAddressCodes,
} from "../feature-form-sections";

const CHANGE_STATUSES: Array<AdminFeatureChangeStatus | "all"> = [
  "pending",
  "applied",
  "rejected",
  "all",
];
const CHANGE_ACTIONS: Array<AdminFeatureChangeAction | "all"> = [
  "all",
  "add",
  "update",
  "delete",
];
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200, 500] as const;
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
const SIDO_SEARCH_LABEL_BY_CODE: Record<string, string> = {
  "11": "서울특별시",
  "26": "부산광역시",
  "27": "대구광역시",
  "28": "인천광역시",
  "29": "광주광역시",
  "30": "대전광역시",
  "31": "울산광역시",
  "36": "세종특별자치시",
  "41": "경기도",
  "42": "강원특별자치도",
  "43": "충청북도",
  "44": "충청남도",
  "45": "전북특별자치도",
  "46": "전라남도",
  "47": "경상북도",
  "48": "경상남도",
  "50": "제주특별자치도",
  "51": "강원특별자치도",
  "52": "전북특별자치도",
};

type FeatureMutationStatus = (typeof FEATURE_STATUS_OPTIONS)[number]["value"];
type FeatureMutationKind = (typeof FEATURE_KIND_OPTIONS)[number]["value"];

interface SigunguCandidate {
  code: string;
  label: string;
  lon?: number;
  lat?: number;
}

export interface FeatureChangeRequestPrefill {
  action?: string;
  featureId?: string;
  key: string;
  reason?: string;
}

interface FeatureChangeFormState {
  action: AdminFeatureChangeAction;
  addressAdmin: string;
  addressJson: string;
  addressLegal: string;
  addressRoad: string;
  adminDongCode: string;
  category: string;
  coordPrecisionDigits: string;
  detailJson: string;
  endDate: string;
  eventStatus: string;
  featureId: string;
  homepageUrl: string;
  idempotencyKey: string;
  kind: FeatureMutationKind;
  lat: string;
  legalDongCode: string;
  lon: string;
  markerColor: string;
  markerIcon: string;
  name: string;
  operator: string;
  organizer: string;
  parentFeatureId: string;
  phone: string;
  placeKind: string;
  reason: string;
  roadAddressManagementNo: string;
  roadNameCode: string;
  siblingGroupId: string;
  sidoCode: string;
  sigunguCode: string;
  sourceUrl: string;
  startDate: string;
  status: FeatureMutationStatus;
  urlsJson: string;
  venue: string;
}

const EMPTY_JSON = "";
type LocationDraft = Pick<
  FeatureChangeFormState,
  "lat" | "lon" | "markerColor" | "markerIcon" | "sigunguCode"
>;
type UpdateFeatureChangeForm = <K extends keyof FeatureChangeFormState>(
  key: K,
  value: FeatureChangeFormState[K],
) => void;

function initialForm(): FeatureChangeFormState {
  return {
    action: "add",
    addressAdmin: "",
    addressJson: EMPTY_JSON,
    addressLegal: "",
    addressRoad: "",
    adminDongCode: "",
    category: "01070300",
    coordPrecisionDigits: "",
    detailJson: EMPTY_JSON,
    endDate: "",
    eventStatus: "",
    featureId: "",
    homepageUrl: "",
    idempotencyKey: "",
    kind: "place",
    lat: "",
    legalDongCode: "",
    lon: "",
    markerColor: "P-01",
    markerIcon: "marker",
    name: "",
    operator: "local-admin",
    organizer: "",
    parentFeatureId: "",
    phone: "",
    placeKind: "",
    reason: "",
    roadAddressManagementNo: "",
    roadNameCode: "",
    siblingGroupId: "",
    sidoCode: "",
    sigunguCode: "",
    sourceUrl: "",
    startDate: "",
    status: "active",
    urlsJson: EMPTY_JSON,
    venue: "",
  };
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function isFeatureMutationKind(value: string): value is FeatureMutationKind {
  return FEATURE_KIND_OPTIONS.some((option) => option.value === value);
}

function isFeatureMutationStatus(value: string): value is FeatureMutationStatus {
  return FEATURE_STATUS_OPTIONS.some((option) => option.value === value);
}

function formatCoordInput(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(6)
    : "";
}

function parseCoordInput(
  lonValue: string,
  latValue: string,
): { lon: number; lat: number } | null {
  const lon = Number(lonValue);
  const lat = Number(latValue);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  if (!isKoreaCoordinate(lon, lat)) return null;
  return { lon, lat };
}

function coordValidationMessage(lonValue: string, latValue: string): string | null {
  const hasLon = lonValue.trim().length > 0;
  const hasLat = latValue.trim().length > 0;
  if (!hasLon && !hasLat) return null;
  if (!hasLon || !hasLat) return "경도와 위도는 함께 입력하세요.";
  const lon = Number(lonValue);
  const lat = Number(latValue);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    return "좌표는 숫자로 입력하세요.";
  }
  return isKoreaCoordinate(lon, lat) ? null : KOREA_COORD_MESSAGE;
}

function jsonObjectText(value: Record<string, unknown>): string {
  return Object.keys(value).length > 0 ? JSON.stringify(value, null, 2) : "";
}

function fieldText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function omitKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): Record<string, unknown> {
  const next = { ...value };
  for (const key of keys) {
    delete next[key];
  }
  return next;
}

function compactObject(
  value: Record<string, unknown>,
): Record<string, unknown> | undefined {
  const entries = Object.entries(value).filter(([, item]) => {
    if (item === null || item === undefined) return false;
    if (typeof item === "string" && item.trim().length === 0) return false;
    return true;
  });
  return entries.length > 0 ? Object.fromEntries(entries) : undefined;
}

function dateTimeLocalText(value: unknown): string {
  const text = fieldText(value);
  if (text.length === 0) return "";
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(text);
  return match ? `${match[1]}T${match[2]}` : text;
}

function optionLabel(
  options: readonly { value: string; label: string }[],
  value: string,
): string {
  return options.find((option) => option.value === value)?.label ?? value;
}

function actionLabel(value: string): string {
  return optionLabel(FEATURE_CHANGE_ACTION_OPTIONS, value);
}

function sigunguCandidateFromGeoCandidate(
  candidate: KorTravelGeoCandidate,
): SigunguCandidate | null {
  const codes = korTravelGeoCodesFromCandidate(candidate);
  const code = codes.sigungu_code;
  if (!code || code.length !== 5) return null;
  const region = candidate.region;
  const label = [
    region?.sido ?? SIDO_SEARCH_LABEL_BY_CODE[code.slice(0, 2)],
    region?.sigungu,
  ]
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value))
    .join(" ");
  if (label.length === 0) return null;
  const coord = korTravelGeoCandidateToCoord(candidate);
  return {
    code,
    label,
    ...(coord ? { lon: coord.lon, lat: coord.lat } : {}),
  };
}

function detailToFormPatch(
  feature: AdminFeatureDetailData["feature"],
): Partial<FeatureChangeFormState> {
  const address = feature.address;
  const detail = feature.detail;
  const urls = feature.urls;
  return {
    action: "update",
    addressAdmin: fieldText(address.admin),
    addressJson: jsonObjectText(
      omitKeys(address, [
        "admin",
        "legal",
        "road",
        "bjd_code",
        "legal_dong_code",
        "sigungu_code",
        "sido_code",
        "admin_dong_code",
        "road_name_code",
        "road_address_management_no",
      ]),
    ),
    addressLegal: fieldText(address.legal),
    addressRoad: fieldText(address.road),
    adminDongCode: fieldText(
      feature.admin_dong_code ?? address.admin_dong_code,
    ),
    category: feature.category,
    coordPrecisionDigits: fieldText(feature.coord_precision_digits),
    detailJson: jsonObjectText(
      omitKeys(detail, [
        "phone",
        "place_kind",
        "event_status",
        "starts_at",
        "ends_at",
        "organizer",
        "venue",
      ]),
    ),
    endDate: dateTimeLocalText(detail.ends_at),
    eventStatus: fieldText(detail.event_status),
    featureId: feature.feature_id,
    homepageUrl: fieldText(urls.homepage),
    kind: isFeatureMutationKind(feature.kind) ? feature.kind : "place",
    lat: formatCoordInput(feature.lat),
    legalDongCode: fieldText(
      feature.legal_dong_code ?? address.bjd_code ?? address.legal_dong_code,
    ),
    lon: formatCoordInput(feature.lon),
    markerColor: feature.marker_color ?? "P-01",
    markerIcon: feature.marker_icon ?? "marker",
    name: feature.name,
    organizer: fieldText(detail.organizer),
    parentFeatureId: fieldText(feature.parent_feature_id),
    phone: fieldText(detail.phone),
    placeKind: fieldText(detail.place_kind),
    roadAddressManagementNo: fieldText(
      feature.road_address_management_no ??
        address.road_address_management_no,
    ),
    roadNameCode: fieldText(feature.road_name_code ?? address.road_name_code),
    siblingGroupId: fieldText(feature.sibling_group_id),
    sidoCode: fieldText(feature.sido_code ?? address.sido_code),
    sigunguCode: fieldText(feature.sigungu_code ?? address.sigungu_code),
    sourceUrl: fieldText(urls.source),
    startDate: dateTimeLocalText(detail.starts_at),
    status: isFeatureMutationStatus(feature.status) ? feature.status : "active",
    urlsJson: jsonObjectText(omitKeys(urls, ["homepage", "source"])),
    venue: fieldText(detail.venue),
  };
}

function locationDraftFromForm(form: FeatureChangeFormState): LocationDraft {
  return {
    lat: form.lat,
    lon: form.lon,
    markerColor: form.markerColor,
    markerIcon: form.markerIcon,
    sigunguCode: form.sigunguCode,
  };
}

function parseOptionalJsonObject(
  label: string,
  value: string,
): Record<string, unknown> | undefined {
  if (value.trim().length === 0) {
    return undefined;
  }
  const parsed = JSON.parse(value) as unknown;
  if (
    parsed === null ||
    Array.isArray(parsed) ||
    typeof parsed !== "object"
  ) {
    throw new Error(`${label}는 JSON object여야 합니다.`);
  }
  return parsed as Record<string, unknown>;
}

function parseOptionalCoord(
  lonValue: string,
  latValue: string,
): { lon: number; lat: number } | undefined {
  const hasLon = lonValue.trim().length > 0;
  const hasLat = latValue.trim().length > 0;
  if (!hasLon && !hasLat) {
    return undefined;
  }
  if (!hasLon || !hasLat) {
    throw new Error("lon과 lat은 함께 입력해야 합니다.");
  }
  const lon = Number(lonValue);
  const lat = Number(latValue);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    throw new Error("lon과 lat은 숫자여야 합니다.");
  }
  if (!isKoreaCoordinate(lon, lat)) {
    throw new Error(KOREA_COORD_MESSAGE);
  }
  return { lon, lat };
}

function parseOptionalInteger(label: string, value: string): number | undefined {
  const raw = value.trim();
  if (raw.length === 0) return undefined;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed)) {
    throw new Error(`${label}는 정수여야 합니다.`);
  }
  return parsed;
}

function optionalString(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function buildAddressPayload(
  form: FeatureChangeFormState,
): Record<string, unknown> | undefined {
  const extra = parseOptionalJsonObject("address extra JSON", form.addressJson);
  return compactObject({
    ...(extra ?? {}),
    admin: optionalString(form.addressAdmin),
    legal: optionalString(form.addressLegal),
    road: optionalString(form.addressRoad),
    bjd_code: optionalString(form.legalDongCode),
    sigungu_code: optionalString(form.sigunguCode),
    sido_code: optionalString(form.sidoCode),
    admin_dong_code: optionalString(form.adminDongCode),
    road_name_code: optionalString(form.roadNameCode),
    road_address_management_no: optionalString(form.roadAddressManagementNo),
  });
}

function buildDetailPayload(
  form: FeatureChangeFormState,
): Record<string, unknown> | undefined {
  const extra = parseOptionalJsonObject("detail extra JSON", form.detailJson);
  return compactObject({
    ...(extra ?? {}),
    phone: optionalString(form.phone),
    place_kind: optionalString(form.placeKind),
    event_status: optionalString(form.eventStatus),
    starts_at: optionalString(form.startDate),
    ends_at: optionalString(form.endDate),
    organizer: optionalString(form.organizer),
    venue: optionalString(form.venue),
  });
}

function buildUrlsPayload(
  form: FeatureChangeFormState,
): Record<string, unknown> | undefined {
  const extra = parseOptionalJsonObject("urls extra JSON", form.urlsJson);
  return compactObject({
    ...(extra ?? {}),
    homepage: optionalString(form.homepageUrl),
    source: optionalString(form.sourceUrl),
  });
}

function validateTextFields(
  form: FeatureChangeFormState,
  categoryItems: readonly CategorySummary[],
): void {
  validateAddressCodes(form);
  parseOptionalCoord(form.lon, form.lat);
  const phoneError = phoneNumber<FeatureChangeFormState>()(form.phone, form);
  if (phoneError) {
    throw new Error(phoneError);
  }
  for (const [label, value] of [
    ["홈페이지", form.homepageUrl],
    ["출처", form.sourceUrl],
  ] as const) {
    const urlError = httpUrl<FeatureChangeFormState>(label)(value, form);
    if (urlError) {
      throw new Error(urlError);
    }
  }
  if (!MARKER_ICON_OPTIONS.includes(form.markerIcon)) {
    throw new Error("목록에 있는 마커 아이콘을 선택하세요.");
  }
  if (!MARKER_COLOR_OPTIONS.some((item) => item.code === form.markerColor)) {
    throw new Error("목록에 있는 마커 색상을 선택하세요.");
  }
  if (
    categoryItems.length > 0 &&
    !categoryItems.some((item) => item.code === form.category)
  ) {
    throw new Error("목록에 있는 카테고리를 선택하세요.");
  }
}

function buildCreatePayload(
  form: FeatureChangeFormState,
): AdminFeatureCreateRequest {
  if (form.name.trim().length === 0) {
    throw new Error("name은 필수입니다.");
  }
  if (form.category.trim().length === 0) {
    throw new Error("category는 필수입니다.");
  }
  if (form.reason.trim().length === 0) {
    throw new Error("reason은 필수입니다.");
  }
  return {
    kind: form.kind,
    name: form.name.trim(),
    category: form.category.trim(),
    coord: parseOptionalCoord(form.lon, form.lat),
    coord_precision_digits: parseOptionalInteger(
      "coord_precision_digits",
      form.coordPrecisionDigits,
    ),
    marker_icon: form.markerIcon.trim(),
    marker_color: form.markerColor.trim(),
    status: form.status,
    reason: form.reason.trim(),
    operator: optionalString(form.operator),
    feature_id: optionalString(form.featureId),
    idempotency_key: optionalString(form.idempotencyKey),
    sido_code: optionalString(form.sidoCode),
    sigungu_code: optionalString(form.sigunguCode),
    legal_dong_code: optionalString(form.legalDongCode),
    admin_dong_code: optionalString(form.adminDongCode),
    road_name_code: optionalString(form.roadNameCode),
    road_address_management_no: optionalString(form.roadAddressManagementNo),
    parent_feature_id: optionalString(form.parentFeatureId),
    sibling_group_id: optionalString(form.siblingGroupId),
    address: buildAddressPayload(form),
    detail: buildDetailPayload(form),
    urls: buildUrlsPayload(form),
  };
}

// category/marker_icon/marker_color는 initialForm 기본값이 비어있지 않아 optionalString이
// 항상 통과 → prefill 안 된 update에서 기존 feature 값을 기본값으로 덮어쓰는 사고가 났다(#613).
// 로드된 feature(baseline)와 다를 때만 PATCH에 포함하고, baseline이 없으면 생략한다.
function patchDefaultedField(
  formValue: string,
  baselineValue: string | null | undefined,
  baseline: AdminFeatureDetailData["feature"] | null,
): string | undefined {
  const trimmed = formValue.trim();
  if (trimmed.length === 0) return undefined;
  if (!baseline) return undefined;
  if (baselineValue != null && trimmed === baselineValue) return undefined;
  return trimmed;
}

function buildPatchPayload(
  form: FeatureChangeFormState,
  baseline: AdminFeatureDetailData["feature"] | null,
): AdminFeaturePatchRequest {
  if (form.featureId.trim().length === 0) {
    throw new Error("update에는 feature_id가 필요합니다.");
  }
  if (form.reason.trim().length === 0) {
    throw new Error("reason은 필수입니다.");
  }
  const coord = parseOptionalCoord(form.lon, form.lat);
  return {
    reason: form.reason.trim(),
    operator: optionalString(form.operator),
    name: optionalString(form.name),
    category: patchDefaultedField(form.category, baseline?.category, baseline),
    coord,
    coord_precision_digits: parseOptionalInteger(
      "coord_precision_digits",
      form.coordPrecisionDigits,
    ),
    marker_icon: patchDefaultedField(form.markerIcon, baseline?.marker_icon, baseline),
    marker_color: patchDefaultedField(form.markerColor, baseline?.marker_color, baseline),
    sido_code: optionalString(form.sidoCode),
    sigungu_code: optionalString(form.sigunguCode),
    legal_dong_code: optionalString(form.legalDongCode),
    admin_dong_code: optionalString(form.adminDongCode),
    road_name_code: optionalString(form.roadNameCode),
    road_address_management_no: optionalString(form.roadAddressManagementNo),
    parent_feature_id: optionalString(form.parentFeatureId),
    sibling_group_id: optionalString(form.siblingGroupId),
    address: buildAddressPayload(form),
    detail: buildDetailPayload(form),
    urls: buildUrlsPayload(form),
  };
}

function ChangeRequestDetail({
  request,
}: {
  request: AdminFeatureChangeRecord | null;
}) {
  if (!request) {
    return (
      <div className="rounded-lg border bg-background p-5 text-sm text-muted-foreground">
        요청 행을 선택하면 payload와 처리 시각을 확인할 수 있습니다.
      </div>
    );
  }

  return (
    <aside className="flex min-w-0 flex-col gap-4 rounded-lg border bg-background p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
        <div className="font-medium">요청 상세</div>
          <div className="break-all font-mono text-xs text-muted-foreground">
            {request.request_id}
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          <Badge variant="outline">{actionLabel(request.action)}</Badge>
          <StatusBadge status={request.status} />
        </div>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Feature</dt>
        <dd className="break-all font-mono">{request.feature_id}</dd>
        <dt className="text-muted-foreground">검수 방식</dt>
        <dd>{request.review_mode}</dd>
        <dt className="text-muted-foreground">요청자</dt>
        <dd>{request.requested_by ?? "-"}</dd>
        <dt className="text-muted-foreground">검수자</dt>
        <dd>{request.reviewed_by ?? "-"}</dd>
        <dt className="text-muted-foreground">생성</dt>
        <dd>{formatDateTime(request.created_at)}</dd>
        <dt className="text-muted-foreground">반영</dt>
        <dd>{formatDateTime(request.applied_at)}</dd>
      </dl>
      <div>
        <div className="mb-2 text-sm font-medium">사유</div>
        <p className="text-sm text-muted-foreground">{request.reason ?? "-"}</p>
      </div>
      <div>
        <div className="mb-2 text-sm font-medium">변경 내용</div>
        <JsonBlock value={request.payload} />
      </div>
    </aside>
  );
}

function LocationEditDialog({
  form,
  updateForm,
  onClose,
}: {
  form: FeatureChangeFormState;
  updateForm: UpdateFeatureChangeForm;
  onClose: () => void;
}) {
  const [reverseMessage, setReverseMessage] = useState<string | null>(null);
  const [draft, setDraft] = useState<LocationDraft>(() =>
    locationDraftFromForm(form),
  );
  const mountedRef = useRef(true);
  const coord = parseCoordInput(draft.lon, draft.lat);
  const coordError = coordValidationMessage(draft.lon, draft.lat);
  const sigunguCodeError = addressCodeError("sigunguCode", draft.sigunguCode);
  const markerColorStyle = markerColorSelectStyle(draft.markerColor);
  const markerIconOptions = MARKER_ICON_OPTIONS.includes(draft.markerIcon)
    ? MARKER_ICON_OPTIONS
    : [draft.markerIcon, ...MARKER_ICON_OPTIONS].filter(Boolean);
  const dialogCenter: [number, number] = coord
    ? [coord.lon, coord.lat]
    : [DEFAULT_VIEWPORT.lon, DEFAULT_VIEWPORT.lat];
  const dialogZoom = coord ? 13 : DEFAULT_VIEWPORT.zoom;

  const updateDraft = <K extends keyof LocationDraft>(
    key: K,
    value: LocationDraft[K],
  ) => setDraft((current) => ({ ...current, [key]: value }));

  useEffect(
    () => () => {
      mountedRef.current = false;
    },
    [],
  );

  const selectPoint = async (lon: number, lat: number) => {
    setDraft((current) => ({
      ...current,
      lat: lat.toFixed(6),
      lon: lon.toFixed(6),
    }));
      setReverseMessage("위치의 시군구를 확인하는 중...");
    try {
      const response = await reverseGeocode({ lon, lat });
      const candidate = response.candidates[0];
      const sigungu = candidate
        ? sigunguCandidateFromGeoCandidate(candidate)
        : null;
      if (!mountedRef.current) return;
      if (sigungu) {
        setDraft((current) => ({ ...current, sigunguCode: sigungu.code }));
        setReverseMessage(`${sigungu.label} · ${sigungu.code}`);
      } else {
        setReverseMessage("시군구 후보 없음");
      }
    } catch (error) {
      if (!mountedRef.current) return;
      setReverseMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const applyDraft = () => {
    updateForm("lon", draft.lon);
    updateForm("lat", draft.lat);
    updateForm("markerIcon", draft.markerIcon);
    updateForm("markerColor", draft.markerColor);
    updateForm("sigunguCode", draft.sigunguCode);
    onClose();
  };

  return (
    <div
      aria-labelledby="change-location-dialog-title"
      aria-modal="true"
      className="fixed inset-0 z-50 overflow-hidden bg-black/45 p-2 sm:p-4"
      role="dialog"
    >
      <div className="mx-auto flex h-[calc(100dvh-1rem)] max-w-6xl flex-col overflow-hidden rounded-lg border bg-background shadow-xl sm:h-[min(48rem,calc(100dvh-2rem))]">
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <div className="min-w-0">
            <div className="font-medium" id="change-location-dialog-title">
              위치/마커 편집
            </div>
            <div className="break-all font-mono text-xs text-muted-foreground">
              {coord
                ? `${coord.lon.toFixed(6)}, ${coord.lat.toFixed(6)}`
                : "좌표 없음"}
            </div>
          </div>
          <Button
            aria-label="위치 편집 닫기"
            size="icon"
            type="button"
            variant="ghost"
            onClick={onClose}
          >
            <XIcon data-icon="inline-start" />
          </Button>
        </div>
        <div className="grid min-h-0 flex-1 grid-rows-[minmax(16rem,42dvh)_minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_22rem] lg:grid-rows-1">
          <div className="relative min-h-0">
            <VWorldMapView
              apiKey={VWORLD_KEY}
              center={dialogCenter}
              className="absolute inset-0 h-full w-full"
              navigation
              onContextMenu={(event) => {
                event.originalEvent.preventDefault();
                void selectPoint(event.lngLat.lng, event.lngLat.lat);
              }}
              onLongPress={(event) => {
                event.originalEvent.preventDefault();
                void selectPoint(event.lngLat.lng, event.lngLat.lat);
              }}
              scale
              testId="feature-change-location-map"
              zoom={dialogZoom}
            >
              {coord ? (
                <VWorldMarker
                  lngLat={[coord.lon, coord.lat]}
                  markerColor={draft.markerColor}
                  markerIcon={draft.markerIcon}
                  selected
                  size={34}
                  title={form.name || "feature change point"}
                />
              ) : null}
            </VWorldMapView>
          </div>
          <div className="min-h-0 overflow-auto border-t p-3 sm:p-4 lg:border-l lg:border-t-0">
            <div className="grid gap-3">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <FormField
                  error={coordError}
                  inputMode="decimal"
                  label="경도"
                  value={draft.lon}
                  onChange={(event) => updateDraft("lon", event.target.value)}
                />
                <FormField
                  error={coordError}
                  inputMode="decimal"
                  label="위도"
                  value={draft.lat}
                  onChange={(event) => updateDraft("lat", event.target.value)}
                />
              </div>
              <FormSelect
                label="마커 아이콘"
                value={draft.markerIcon}
                onChange={(event) => updateDraft("markerIcon", event.target.value)}
              >
                {markerIconOptions.map((item) => (
                  <NativeSelectOption key={item} value={item}>
                    {markerIconLabel(item)}
                  </NativeSelectOption>
                ))}
              </FormSelect>
              <FormSelect
                label="마커 색상"
                style={markerColorStyle}
                value={draft.markerColor}
                onChange={(event) => updateDraft("markerColor", event.target.value)}
              >
                {MARKER_COLOR_OPTIONS.map((item) => (
                  <NativeSelectOption
                    key={item.code}
                    style={{
                      backgroundColor: item.hex,
                      color: readableTextColor(item.hex),
                    }}
                    value={item.code}
                  >
                    {item.label}
                  </NativeSelectOption>
                ))}
              </FormSelect>
              <AdminRegionAutoSearch
                id="change-location-sigungu-code"
                kind="sigungu"
                label="시군구 코드"
                value={draft.sigunguCode}
                onChange={(value) => updateDraft("sigunguCode", value)}
                onSelectCandidate={(candidate) => {
                  const sigungu = sigunguCandidateFromGeoCandidate(candidate);
                  if (sigungu) {
                    setReverseMessage(`${sigungu.label} · ${sigungu.code}`);
                  }
                }}
              />
              <div className="flex flex-wrap gap-2">
                {reverseMessage ? (
                  <Badge variant="outline">{reverseMessage}</Badge>
                ) : null}
              </div>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t px-4 py-3">
          <Button
            className="flex-1 sm:flex-none"
            type="button"
            variant="outline"
            onClick={onClose}
          >
            <XIcon data-icon="inline-start" />
            취소
          </Button>
          <Button
            className="flex-1 sm:flex-none"
            disabled={Boolean(coordError || sigunguCodeError)}
            type="button"
            onClick={applyDraft}
          >
            <CheckIcon data-icon="inline-start" />
            적용
          </Button>
        </div>
      </div>
    </div>
  );
}

export function FeatureChangeRequestsClient({
  prefill,
  view = "request",
}: {
  prefill?: FeatureChangeRequestPrefill;
  view?: "request" | "review";
}) {
  const queryPrefillKey = prefill?.key ?? "";
  const prefillFeatureId = prefill?.featureId?.trim() || null;
  const [status, setStatus] = useState<AdminFeatureChangeStatus | "all">("pending");
  const [action, setAction] = useState<AdminFeatureChangeAction | "all">("all");
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>(100);
  const [q, setQ] = useState("");
  const deferredQ = useDeferredValue(q.trim());
  const [selectedRequest, setSelectedRequest] =
    useState<AdminFeatureChangeRecord | null>(null);
  const [form, setForm] = useState<FeatureChangeFormState>(() => initialForm());
  const [formError, setFormError] = useState<string | null>(null);
  const [locationDialogOpen, setLocationDialogOpen] = useState(false);
  const appliedQueryPrefillRef = useRef<string | null>(null);
  const appliedFeaturePrefillRef = useRef<string | null>(null);
  const categories = useCategories({ active_only: false, include_counts: false });
  // update 대상 feature는 URL prefill뿐 아니라 폼의 Feature ID 입력에서도 조회한다 —
  // 폼이 실제 feature 값으로 채워져야 기본값 덮어쓰기(#613)를 막을 수 있다.
  const detailLookupId =
    form.action === "update"
      ? form.featureId.trim() || prefillFeatureId
      : prefillFeatureId;
  const prefillFeature = useAdminFeatureDetail(detailLookupId);
  const loadedUpdateFeature =
    form.action === "update" &&
    prefillFeature.data?.data.feature?.feature_id === form.featureId.trim()
      ? prefillFeature.data.data.feature
      : null;

  const params = useMemo(
    () => ({
      status: status === "all" ? undefined : [status],
      action: action === "all" ? undefined : [action],
      q: deferredQ.length > 0 ? deferredQ : undefined,
      page_size: pageSize,
    }),
    [action, deferredQ, pageSize, status],
  );
  const changes = useAdminFeatureChangeRequests(params);
  const createFeature = useCreateAdminFeatureMutation();
  const patchFeature = usePatchAdminFeatureMutation();
  const deleteFeature = useDeleteAdminFeatureMutation();
  const approveChange = useApproveAdminFeatureChangeMutation();
  const rejectChange = useRejectAdminFeatureChangeMutation();
  const approveChangeRequest = approveChange.mutate;
  const rejectChangeRequest = rejectChange.mutate;
  const items = changes.data?.data.items ?? [];
  const reviewMode = changes.data?.data.review_mode ?? "unknown";
  const anyMutationPending =
    createFeature.isPending ||
    patchFeature.isPending ||
    deleteFeature.isPending ||
    approveChange.isPending ||
    rejectChange.isPending;
  const mutationError =
    createFeature.error ??
    patchFeature.error ??
    deleteFeature.error ??
    approveChange.error ??
    rejectChange.error;
  const categoryItems = categories.data?.data.items ?? [];
  const formCoord = parseCoordInput(form.lon, form.lat);
  const formCoordError =
    form.action === "delete" ? null : coordValidationMessage(form.lon, form.lat);
  const formMarkerIconOptions = MARKER_ICON_OPTIONS.includes(form.markerIcon)
    ? MARKER_ICON_OPTIONS
    : [form.markerIcon, ...MARKER_ICON_OPTIONS].filter(Boolean);
  const showRequestForm = view === "request";
  const showReview = view === "review";

  const updateForm = <K extends keyof FeatureChangeFormState>(
    key: K,
    value: FeatureChangeFormState[K],
  ) => setForm((current) => ({ ...current, [key]: value }));

  const resetForm = () => {
    setForm(initialForm());
    setFormError(null);
    appliedQueryPrefillRef.current = null;
    appliedFeaturePrefillRef.current = null;
  };

  const applyRegionCandidate = (candidate: KorTravelGeoCandidate) => {
    const nextCoord = korTravelGeoCandidateToCoord(candidate);
    const address = korTravelGeoCandidateToAddressRecord(candidate);
    const codes = korTravelGeoCodesFromCandidate(candidate);
    setForm((current) => ({
      ...current,
      addressAdmin: fieldText(address.admin) || current.addressAdmin,
      addressLegal: fieldText(address.legal) || current.addressLegal,
      addressRoad: fieldText(address.road) || current.addressRoad,
      adminDongCode: codes.admin_dong_code ?? current.adminDongCode,
      legalDongCode: codes.legal_dong_code ?? current.legalDongCode,
      roadNameCode: codes.road_name_code ?? current.roadNameCode,
      sidoCode: codes.sido_code ?? current.sidoCode,
      sigunguCode: codes.sigungu_code ?? current.sigunguCode,
      ...(nextCoord
        ? {
            lat: nextCoord.lat.toFixed(6),
            lon: nextCoord.lon.toFixed(6),
          }
        : {}),
    }));
  };

  useEffect(() => {
    if (!queryPrefillKey || appliedQueryPrefillRef.current === queryPrefillKey) {
      return;
    }
    const nextAction = prefill?.action;
    const nextFeatureId = prefill?.featureId?.trim() ?? "";
    const nextReason = prefill?.reason?.trim() ?? "";
    setForm((current) => ({
      ...current,
      action:
        nextAction === "add" || nextAction === "update" || nextAction === "delete"
          ? nextAction
          : current.action,
      featureId: nextFeatureId || current.featureId,
      reason: nextReason || current.reason,
    }));
    appliedQueryPrefillRef.current = queryPrefillKey;
  }, [prefill, queryPrefillKey]);

  useEffect(() => {
    const feature = prefillFeature.data?.data.feature;
    if (!feature) return;
    // URL prefill 또는 update에서 직접 입력한 Feature ID의 feature가 로드되면 폼을 그 값으로 채운다.
    const targetId =
      form.action === "update"
        ? form.featureId.trim() || prefillFeatureId
        : prefillFeatureId;
    if (!targetId || feature.feature_id !== targetId) return;
    const key = `${feature.feature_id}:${feature.updated_at}`;
    if (appliedFeaturePrefillRef.current === key) return;
    setForm((current) => ({
      ...current,
      ...detailToFormPatch(feature),
      reason: current.reason || "admin feature detail edit",
    }));
    appliedFeaturePrefillRef.current = key;
  }, [prefillFeature.data?.data.feature, prefillFeatureId, form.action, form.featureId]);

  const submitChange = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    try {
      // delete는 feature_id + reason만 필요 — marker/category/coord 카탈로그 검증은 건너뛴다(#613).
      if (form.action !== "delete") {
        validateTextFields(form, categoryItems);
      }
      if (form.action === "add") {
        const response = await createFeature.mutateAsync(buildCreatePayload(form));
        setSelectedRequest(response.data.request);
      } else if (form.action === "update") {
        const featureId = form.featureId.trim();
        const response = await patchFeature.mutateAsync({
          featureId,
          body: buildPatchPayload(form, loadedUpdateFeature),
        });
        setSelectedRequest(response.data.request);
      } else {
        const featureId = form.featureId.trim();
        if (featureId.length === 0) {
          throw new Error("delete에는 feature_id가 필요합니다.");
        }
        if (form.reason.trim().length === 0) {
          throw new Error("reason은 필수입니다.");
        }
        const response = await deleteFeature.mutateAsync({
          featureId,
          body: {
            operator: optionalString(form.operator),
            reason: form.reason.trim(),
          },
        });
        setSelectedRequest(response.data.request);
      }
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error));
    }
  };

  const approve = useCallback((request: AdminFeatureChangeRecord) => {
    approveChangeRequest(
      {
        requestId: request.request_id,
        body: { operator: "local-admin", reason: "admin-ui approve" },
      },
      { onSuccess: (data) => setSelectedRequest(data.data.request) },
    );
  }, [approveChangeRequest]);

  const reject = useCallback((request: AdminFeatureChangeRecord) => {
    rejectChangeRequest(
      {
        requestId: request.request_id,
        body: { operator: "local-admin", reason: "admin-ui reject" },
      },
      { onSuccess: (data) => setSelectedRequest(data.data.request) },
    );
  }, [rejectChangeRequest]);

  const columns = useMemo<ColumnDef<AdminFeatureChangeRecord, unknown>[]>(
    () => [
      {
        id: "request",
        header: "요청",
        enableSorting: false,
        cell: ({ row }) => {
          const request = row.original;
          return (
            <>
              <div className="font-mono text-xs">
                {shortId(request.request_id, 18)}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {request.requested_by ?? "-"}
              </div>
            </>
          );
        },
      },
      {
        id: "action_status",
        header: "작업/상태",
        accessorFn: (request) => request.status,
        cell: ({ row }) => {
          const request = row.original;
          return (
            <div className="flex flex-wrap gap-1">
              <Badge variant="outline">{actionLabel(request.action)}</Badge>
              <StatusBadge status={request.status} />
            </div>
          );
        },
      },
      {
        id: "feature",
        header: "feature",
        enableSorting: false,
        cell: ({ row }) => {
          const request = row.original;
          return (
            <div className="max-w-64">
              <div className="break-all font-mono text-xs">
                {shortId(request.feature_id, 28)}
              </div>
              {typeof request.payload.name === "string" ? (
                <div className="mt-1 truncate text-sm">
                  {request.payload.name}
                </div>
              ) : null}
            </div>
          );
        },
      },
      {
        id: "review",
        header: "리뷰",
        enableSorting: false,
        cell: ({ row }) => {
          const request = row.original;
          return (
            <>
              <div>{request.review_mode}</div>
              <div className="text-xs text-muted-foreground">
                {request.reviewed_by ?? "-"}
              </div>
            </>
          );
        },
      },
      {
        id: "reason",
        header: "사유",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-56 truncate">
            {row.original.reason ?? "-"}
          </span>
        ),
      },
      {
        accessorKey: "created_at",
        header: "생성",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        cell: ({ row }) => {
          const request = row.original;
          if (request.status === "pending") {
            return (
              <div className="flex flex-wrap gap-1">
                <Button
                  disabled={anyMutationPending}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={(event) => {
                    event.stopPropagation();
                    approve(request);
                  }}
                >
                  <CheckIcon data-icon="inline-start" />
                  승인
                </Button>
                <Button
                  disabled={anyMutationPending}
                  size="sm"
                  type="button"
                  variant="ghost"
                  onClick={(event) => {
                    event.stopPropagation();
                    reject(request);
                  }}
                >
                  <XIcon data-icon="inline-start" />
                  반려
                </Button>
              </div>
            );
          }
          if (request.action === "delete") {
            return (
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Trash2Icon className="size-3.5" />
                완료
              </div>
            );
          }
          return <span className="text-sm text-muted-foreground">완료</span>;
        },
      },
    ],
    [anyMutationPending, approve, reject],
  );

  return (
    <AdminShell
      actions={
        <>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features"
          >
            <ClipboardListIcon data-icon="inline-start" />
            목록
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href={
              showReview
                ? "/admin/features/change-requests"
                : "/admin/features/change-reviews"
            }
          >
            {showReview ? (
              <PlusIcon data-icon="inline-start" />
            ) : (
              <CheckIcon data-icon="inline-start" />
            )}
            {showReview ? "변경 요청 작성" : "검수 화면"}
          </Link>
          <Button
            disabled={changes.isFetching}
            type="button"
            variant="outline"
            onClick={() => void changes.refetch()}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
        </>
      }
      description={
        showReview
          ? "변경 요청을 검수합니다."
          : "Feature를 추가·수정·삭제하는 요청을 작성합니다."
      }
      section="Feature"
      title={showReview ? "Feature 검수" : "변경 요청 작성"}
    >
      <div className="flex flex-col gap-4">
        {(changes.isError || mutationError || formError) && (
          <Alert variant="destructive">
            <AlertTitle>Feature 변경 처리 실패</AlertTitle>
            <AlertDescription>
              {formError ?? changes.error?.message ?? mutationError?.message}
            </AlertDescription>
          </Alert>
        )}

        {showRequestForm ? (
          <form className="flex flex-col gap-4" onSubmit={submitChange}>
          <section className="rounded-lg border bg-background p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <h2 className="font-medium">변경 요청 작성</h2>
                <div className="mt-1 flex min-h-6 flex-wrap items-center gap-2 text-sm text-muted-foreground">
                  {prefillFeature.isFetching ? (
                    <Badge variant="outline">불러오는 중</Badge>
                  ) : null}
                  {prefillFeatureId && prefillFeature.data?.data.feature ? (
                    <Badge variant="secondary">데이터 로드됨</Badge>
                  ) : null}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={resetForm}
                >
                  <RotateCcwIcon data-icon="inline-start" />
                  초기화
                </Button>
                <Button
                  disabled={
                    anyMutationPending ||
                    (form.action === "update" && prefillFeature.isFetching)
                  }
                  size="sm"
                  type="submit"
                >
                  <PlusIcon data-icon="inline-start" />
                  요청 생성
                </Button>
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-4">
              <FormSelect
                aria-label="change action"
                id="change-action"
                label="요청 종류"
                value={form.action}
                onChange={(event) =>
                  updateForm(
                    "action",
                    event.target.value as AdminFeatureChangeAction,
                  )
                }
              >
                {FEATURE_CHANGE_ACTION_OPTIONS.map((option) => (
                  <NativeSelectOption key={option.value} value={option.value}>
                    {option.label}
                  </NativeSelectOption>
                ))}
              </FormSelect>
              <FormField
                aria-label="change feature id"
                id="change-feature-id"
                label="Feature ID"
                placeholder={
                  form.action === "add" ? "비우면 자동 생성" : "수정할 Feature ID"
                }
                value={form.featureId}
                onChange={(event) => updateForm("featureId", event.target.value)}
              />
              <FormField
                aria-label="change reason"
                id="change-reason"
                label="변경 사유"
                placeholder="예: 전화번호 수정"
                value={form.reason}
                onChange={(event) => updateForm("reason", event.target.value)}
              />
              <FormField
                aria-label="change operator"
                id="change-operator"
                label="담당자"
                value={form.operator}
                onChange={(event) => updateForm("operator", event.target.value)}
              />
            </div>
            <div className="mt-3 grid gap-3 lg:grid-cols-4">
              <FormField
                aria-label="change idempotency key"
                id="change-idempotency-key"
                label="중복 방지 키"
                hint="같은 요청을 한 번만 만들 때 사용합니다."
                value={form.idempotencyKey}
                onChange={(event) =>
                  updateForm("idempotencyKey", event.target.value)
                }
              />
              <FormField
                aria-label="change parent feature id"
                id="change-parent-feature-id"
                label="상위 Feature ID"
                value={form.parentFeatureId}
                onChange={(event) =>
                  updateForm("parentFeatureId", event.target.value)
                }
              />
              <FormField
                aria-label="change sibling group id"
                id="change-sibling-group-id"
                label="같은 그룹 ID"
                value={form.siblingGroupId}
                onChange={(event) =>
                  updateForm("siblingGroupId", event.target.value)
                }
              />
              <FormField
                aria-label="change coord precision digits"
                id="change-coord-precision-digits"
                inputMode="numeric"
                label="좌표 소수 자릿수"
                value={form.coordPrecisionDigits}
                onChange={(event) =>
                  updateForm("coordPrecisionDigits", event.target.value)
                }
              />
            </div>
          </section>

          {form.action !== "delete" ? (
            <>
              <FeatureBasicInfoSection
                category={form.category}
                categoryItems={categoryItems}
                idPrefix="change"
                kind={form.kind}
                name={form.name}
                status={form.status}
                onCategoryChange={(value) => updateForm("category", value)}
                onKindChange={(value) =>
                  updateForm("kind", value as FeatureMutationKind)
                }
                onNameChange={(value) => updateForm("name", value)}
                onStatusChange={(value) =>
                  updateForm("status", value as FeatureMutationStatus)
                }
              />
              {categories.isError ? (
                <div className="text-sm text-destructive">
                  {categories.error.message}
                </div>
              ) : null}
              {prefillFeature.isError ? (
                <Alert variant="destructive">
                  <AlertTitle>feature 상세 prefill 실패</AlertTitle>
                  <AlertDescription>{prefillFeature.error.message}</AlertDescription>
                </Alert>
              ) : null}

              <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_28rem]">
                <FeatureLocationPreviewSection
                  apiKey={VWORLD_KEY}
                  coord={formCoord}
                  heightClassName="h-[18rem] sm:h-[24rem]"
                  markerColor={form.markerColor}
                  markerIcon={form.markerIcon}
                  testId="feature-change-location-preview-map"
                  title={form.name || "feature change point"}
                  actions={
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setLocationDialogOpen(true)}
                    >
                      <MapPinIcon data-icon="inline-start" />
                      위치 편집
                    </Button>
                  }
                  onMapClick={({ lon, lat }) => {
                    updateForm("lon", lon.toFixed(6));
                    updateForm("lat", lat.toFixed(6));
                  }}
                />

                <section className="rounded-lg border bg-background p-4">
                  <h2 className="mb-3 font-medium">위치/마커</h2>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                    <FormField
                      aria-label="change lon"
                      error={formCoordError}
                      id="change-lon"
                      inputMode="decimal"
                      label="경도"
                      value={form.lon}
                      onChange={(event) => updateForm("lon", event.target.value)}
                    />
                    <FormField
                      aria-label="change lat"
                      error={formCoordError}
                      id="change-lat"
                      inputMode="decimal"
                      label="위도"
                      value={form.lat}
                      onChange={(event) => updateForm("lat", event.target.value)}
                    />
                    <FormSelect
                      aria-label="change marker icon"
                      id="change-marker-icon"
                      label="마커 아이콘"
                      value={form.markerIcon}
                      onChange={(event) =>
                        updateForm("markerIcon", event.target.value)
                      }
                    >
                      {formMarkerIconOptions.map((item) => (
                        <NativeSelectOption key={item} value={item}>
                          {markerIconLabel(item)}
                        </NativeSelectOption>
                      ))}
                    </FormSelect>
                    <FormSelect
                      aria-label="change marker color"
                      id="change-marker-color"
                      label="마커 색상"
                      style={markerColorSelectStyle(form.markerColor)}
                      value={form.markerColor}
                      onChange={(event) =>
                        updateForm("markerColor", event.target.value)
                      }
                    >
                      {MARKER_COLOR_OPTIONS.map((item) => (
                        <NativeSelectOption
                          key={item.code}
                          style={{
                            backgroundColor: item.hex,
                            color: readableTextColor(item.hex),
                          }}
                          value={item.code}
                        >
                          {item.label}
                        </NativeSelectOption>
                      ))}
                    </FormSelect>
                  </div>
                </section>
              </section>

              <section className="grid gap-4 xl:grid-cols-2">
                <FeatureAddressSection
                  idPrefix="change"
                  values={{
                    addressAdmin: form.addressAdmin,
                    addressExtraJson: form.addressJson,
                    addressLegal: form.addressLegal,
                    addressRoad: form.addressRoad,
                    adminDongCode: form.adminDongCode,
                    legalDongCode: form.legalDongCode,
                    roadAddressManagementNo: form.roadAddressManagementNo,
                    roadNameCode: form.roadNameCode,
                    sidoCode: form.sidoCode,
                    sigunguCode: form.sigunguCode,
                  }}
                  onSelectRegionCandidate={applyRegionCandidate}
                  onChange={(field, value) => {
                    if (field === "addressExtraJson") {
                      updateForm("addressJson", value);
                    } else {
                      updateForm(field, value);
                    }
                  }}
                />
                <FeatureDetailSection
                  idPrefix="change"
                  kind={form.kind}
                  values={{
                    detailExtraJson: form.detailJson,
                    endDate: form.endDate,
                    eventStatus: form.eventStatus,
                    homepageUrl: form.homepageUrl,
                    organizer: form.organizer,
                    phone: form.phone,
                    placeKind: form.placeKind,
                    sourceUrl: form.sourceUrl,
                    startDate: form.startDate,
                    urlsExtraJson: form.urlsJson,
                    venue: form.venue,
                  }}
                  onChange={(field, value) => {
                    if (field === "detailExtraJson") {
                      updateForm("detailJson", value);
                    } else if (field === "urlsExtraJson") {
                      updateForm("urlsJson", value);
                    } else {
                      updateForm(field, value);
                    }
                  }}
                />
              </section>
            </>
          ) : null}
        </form>
        ) : null}

        {showRequestForm && locationDialogOpen ? (
          <LocationEditDialog
            form={form}
            updateForm={updateForm}
            onClose={() => setLocationDialogOpen(false)}
          />
        ) : null}

        {showRequestForm && selectedRequest ? (
          <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_30rem]">
            <Alert>
              <AlertTitle>변경 요청 생성됨</AlertTitle>
              <AlertDescription>
                요청은 Feature 검수 화면에서 승인하거나 반려할 수 있습니다.
              </AlertDescription>
            </Alert>
            <ChangeRequestDetail request={selectedRequest} />
          </section>
        ) : null}

        {showReview ? (
        <>
        <section className="rounded-lg border bg-background p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-medium">변경 요청 목록</h2>
            <div className="flex flex-wrap gap-2 text-sm text-muted-foreground">
              <Badge variant="outline">review mode</Badge>
              <StatusBadge status={reviewMode} />
              <Badge variant="outline">rows {formatCount(items.length)}</Badge>
              <Badge variant="outline">
                limit {changes.data?.meta.page?.page_size ?? pageSize}
              </Badge>
              <Badge variant="outline">
                duration {changes.data?.meta.duration_ms ?? 0}ms
              </Badge>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-[minmax(12rem,1fr)_auto_auto_auto]">
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                aria-label="change search"
                className="pl-8"
                placeholder="feature_id, request_id, reason"
                value={q}
                onChange={(event) => setQ(event.target.value)}
              />
            </div>
            <NativeSelect
              aria-label="change status"
              value={status}
              onChange={(event) =>
                setStatus(event.target.value as AdminFeatureChangeStatus | "all")
              }
            >
              {CHANGE_STATUSES.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item === "all" ? "전체" : statusLabel(item)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="change action filter"
              value={action}
              onChange={(event) =>
                setAction(event.target.value as AdminFeatureChangeAction | "all")
              }
            >
              {CHANGE_ACTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item === "all" ? "전체" : actionLabel(item)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="change page size"
              value={String(pageSize)}
              onChange={(event) =>
                setPageSize(Number(event.target.value) as typeof pageSize)
              }
            >
              {PAGE_SIZE_OPTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
        </section>

        <section className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_30rem]">
          <DataTable
            columns={columns}
            data={items}
            getRowId={(row) => row.request_id}
            isLoading={changes.isLoading}
            emptyMessage="변경 요청이 없습니다."
            manualSorting={false}
            containerClassName="min-w-0 overflow-auto rounded-lg border bg-background"
            onRowClick={(row) => setSelectedRequest(row)}
            isRowActive={(row) =>
              selectedRequest?.request_id === row.request_id
            }
          />

          <ChangeRequestDetail request={selectedRequest} />
        </section>
        </>
        ) : null}
      </div>
    </AdminShell>
  );
}
