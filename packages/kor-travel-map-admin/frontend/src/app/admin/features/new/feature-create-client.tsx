"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (form) · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import type { Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  ArrowLeftIcon,
  CheckCircle2Icon,
  LocateFixedIcon,
  MapPinIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SearchIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useMemo,
  useReducer,
  useRef,
  type FormEvent,
} from "react";

import { useCategories, type CategorySummary } from "@/api/categories";
import { ApiClientError } from "@/api/client";
import {
  useCreateAdminFeatureMutation,
  useNearbyFeatures,
  type AdminFeatureCreateRequest,
  type AdminFeatureCreateKind,
} from "@/api/features";
import {
  geocodeAddress,
  korTravelGeoCandidateToAddressRecord,
  korTravelGeoCandidateToCoord,
  korTravelGeoCodesFromCandidate,
  reverseGeocode,
  type KorTravelGeoCandidate,
} from "@/api/korTravelGeo";
import { AdminShell } from "@/components/admin-shell";
import { SectionCard } from "@/components/section-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { FormField } from "@/components/ui/form-field-input";
import { FormSelect } from "@/components/ui/form-select";
import {
  DataTable,
  type DataTableColumnMeta,
} from "@/components/ui/data-table";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { validateAddressCodes } from "@/lib/feature-address-validation";
import {
  MARKER_COLOR_OPTIONS,
  MARKER_ICON_OPTIONS,
  markerColorSelectStyle,
  markerIconLabel,
  readableTextColor,
} from "@/lib/feature-form-options";
import {
  KOREA_COORD_MESSAGE,
  dateOrdered,
  httpUrl,
  isKoreaCoordinate,
  jsonObject,
  koreaLatitude,
  koreaLongitude,
  parseJsonObjectField,
  phoneNumber,
  required,
  validateForm,
} from "@/lib/form-validation";
import { NULL_GLYPH } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  FeatureAddressSection,
  FeatureBasicInfoSection,
  FeatureDetailSection,
  FeatureLocationPreviewSection,
} from "../feature-form-sections";

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;

type FeatureCreateField = keyof FeatureCreateFormState;

interface FeatureCreateFormState {
  addressAdmin: string;
  addressExtraJson: string;
  addressLegal: string;
  addressRoad: string;
  adminDongCode: string;
  category: string;
  detailExtraJson: string;
  duplicateRadiusM: string;
  endDate: string;
  eventStatus: string;
  geocodeQuery: string;
  geocodeType: "parcel" | "road";
  homepageUrl: string;
  kind: AdminFeatureCreateKind;
  lat: string;
  legalDongCode: string;
  lon: string;
  markerColor: string;
  markerIcon: string;
  name: string;
  organizer: string;
  phone: string;
  placeKind: string;
  reason: string;
  roadAddressManagementNo: string;
  roadNameCode: string;
  sidoCode: string;
  sigunguCode: string;
  sourceUrl: string;
  startDate: string;
  urlsExtraJson: string;
  venue: string;
}

function initialForm(): FeatureCreateFormState {
  return {
    addressAdmin: "",
    addressExtraJson: "",
    addressLegal: "",
    addressRoad: "",
    adminDongCode: "",
    category: "01070300",
    detailExtraJson: "",
    duplicateRadiusM: "150",
    endDate: "",
    eventStatus: "",
    geocodeQuery: "",
    geocodeType: "road",
    homepageUrl: "",
    kind: "place",
    lat: "",
    legalDongCode: "",
    lon: "",
    markerColor: "P-01",
    markerIcon: "marker",
    name: "",
    organizer: "",
    phone: "",
    placeKind: "",
    reason: "",
    roadAddressManagementNo: "",
    roadNameCode: "",
    sidoCode: "",
    sigunguCode: "",
    sourceUrl: "",
    startDate: "",
    urlsExtraJson: "",
    venue: "",
  };
}

function featureDetailHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

function optionalString(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function parseJsonObject(
  label: string,
  value: string,
): Record<string, unknown> {
  // §4: 제출 payload 변환은 parseJsonObjectField로 통일(인라인 jsonObject()와 짝).
  const parsed = parseJsonObjectField(value, label);
  if (parsed.error) {
    throw new Error(`${label}: ${parsed.error}`);
  }
  return parsed.value ?? {};
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

function parseCoord(form: FeatureCreateFormState): {
  lon: number;
  lat: number;
} {
  const lon = Number(form.lon);
  const lat = Number(form.lat);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    throw new Error("좌표는 숫자로 입력하세요.");
  }
  if (!isKoreaCoordinate(lon, lat)) {
    throw new Error(KOREA_COORD_MESSAGE);
  }
  return { lon, lat };
}

function coordValidationMessage(form: FeatureCreateFormState): string | null {
  if (form.lon.trim().length === 0 || form.lat.trim().length === 0) {
    return null;
  }
  try {
    parseCoord(form);
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
}

function validateCreateTextFields(
  form: FeatureCreateFormState,
  categoryItems: readonly CategorySummary[],
) {
  const phoneError = phoneNumber<FeatureCreateFormState>()(form.phone, form);
  if (phoneError) throw new Error(phoneError);
  const homepageError = httpUrl<FeatureCreateFormState>("홈페이지")(
    form.homepageUrl,
    form,
  );
  if (homepageError) throw new Error(homepageError);
  const sourceError = httpUrl<FeatureCreateFormState>("출처")(
    form.sourceUrl,
    form,
  );
  if (sourceError) throw new Error(sourceError);
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
  validateAddressCodes(form);
}

function coordOrNull(
  form: FeatureCreateFormState,
): { lon: number; lat: number } | null {
  if (form.lon.trim().length === 0 || form.lat.trim().length === 0) {
    return null;
  }
  try {
    return parseCoord(form);
  } catch {
    return null;
  }
}

function radiusOrNull(value: string): number | null {
  const radius = Number(value);
  if (!Number.isFinite(radius) || radius <= 0 || radius > 100_000) {
    return null;
  }
  return radius;
}

function buildCreatePayload(
  form: FeatureCreateFormState,
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
  const coord = parseCoord(form);
  const address = compactObject({
    admin: optionalString(form.addressAdmin),
    legal: optionalString(form.addressLegal),
    road: optionalString(form.addressRoad),
    bjd_code: optionalString(form.legalDongCode),
    sigungu_code: optionalString(form.sigunguCode),
    sido_code: optionalString(form.sidoCode),
    admin_dong_code: optionalString(form.adminDongCode),
    road_name_code: optionalString(form.roadNameCode),
    road_address_management_no: optionalString(form.roadAddressManagementNo),
    ...parseJsonObject("address extra JSON", form.addressExtraJson),
  });
  const detail =
    form.kind === "event"
      ? compactObject({
          event_status: optionalString(form.eventStatus),
          starts_at: optionalString(form.startDate),
          ends_at: optionalString(form.endDate),
          organizer: optionalString(form.organizer),
          venue: optionalString(form.venue),
          ...parseJsonObject("detail extra JSON", form.detailExtraJson),
        })
      : compactObject({
          phone: optionalString(form.phone),
          place_kind: optionalString(form.placeKind),
          ...parseJsonObject("detail extra JSON", form.detailExtraJson),
        });
  const urls = compactObject({
    homepage: optionalString(form.homepageUrl),
    source: optionalString(form.sourceUrl),
    ...parseJsonObject("urls extra JSON", form.urlsExtraJson),
  });

  return {
    kind: form.kind,
    name: form.name.trim(),
    category: form.category.trim(),
    coord,
    marker_icon: form.markerIcon.trim(),
    marker_color: form.markerColor.trim(),
    reason: form.reason.trim(),
    sigungu_code: optionalString(form.sigunguCode),
    sido_code: optionalString(form.sidoCode),
    legal_dong_code: optionalString(form.legalDongCode),
    admin_dong_code: optionalString(form.adminDongCode),
    road_name_code: optionalString(form.roadNameCode),
    road_address_management_no: optionalString(form.roadAddressManagementNo),
    address,
    detail,
    urls,
  };
}

const SERVER_FIELD_TO_FORM_FIELDS = {
  body: [],
  category: ["category"],
  coord: ["lon", "lat"],
  "coord.lat": ["lat"],
  "coord.lon": ["lon"],
  lat: ["lat"],
  lon: ["lon"],
  marker_color: ["markerColor"],
  marker_icon: ["markerIcon"],
  name: ["name"],
  reason: ["reason"],
} satisfies Record<string, readonly FeatureCreateField[]>;

function problemErrorField(error: Record<string, unknown>): string | null {
  if (typeof error.field === "string" && error.field.trim().length > 0) {
    return error.field.trim();
  }
  const location = error.loc;
  if (Array.isArray(location)) {
    const parts: string[] = [];
    for (const item of location) {
      if (item !== "body") {
        parts.push(String(item));
      }
    }
    return parts.length > 0 ? parts.join(".") : "body";
  }
  return null;
}

function problemErrorMessage(error: Record<string, unknown>): string | null {
  if (typeof error.message === "string" && error.message.trim().length > 0) {
    return error.message.trim();
  }
  if (typeof error.msg === "string" && error.msg.trim().length > 0) {
    return error.msg.trim();
  }
  return null;
}

function manualCreateValidationErrors(
  error: unknown,
): Partial<Record<FeatureCreateField, string>> | null {
  if (!(error instanceof ApiClientError) || error.status !== 422) {
    return null;
  }
  const fieldErrors: Partial<Record<FeatureCreateField, string>> = {};
  for (const item of error.problem?.errors ?? []) {
    if (typeof item !== "object" || item === null) continue;
    const problemError = item as Record<string, unknown>;
    const field = problemErrorField(problemError);
    const message =
      problemErrorMessage(problemError) ??
      "요청 값이 수동 Feature 생성 계약과 맞지 않습니다.";
    const formFields =
      field && field in SERVER_FIELD_TO_FORM_FIELDS
        ? SERVER_FIELD_TO_FORM_FIELDS[
            field as keyof typeof SERVER_FIELD_TO_FORM_FIELDS
          ]
        : [];
    for (const formField of formFields) {
      fieldErrors[formField] = message;
    }
  }
  return Object.keys(fieldErrors).length > 0 ? fieldErrors : null;
}

function manualCreateErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    switch (error.problem?.code) {
      case "MANUAL_FEATURE_EXACT_DUPLICATE":
        return "같은 이름·종류·좌표의 수동 Feature가 이미 있습니다. 중복 후보를 확인하세요.";
      case "FEATURE_IDENTITY_CONFLICT":
        return "서버가 발급한 Feature identity가 기존 값과 충돌했습니다. 새로고침 후 다시 시도하세요.";
      case "MANUAL_FEATURE_CREATE_NOT_READY":
        return "수동 Feature 생성 기능이 아직 활성화되지 않았습니다.";
      case "ADMIN_FEATURE_CREATE_SCOPE_REQUIRED":
        return "수동 Feature 생성 전용 권한을 확인하지 못했습니다.";
      default:
        return error.message;
    }
  }
  return error instanceof Error ? error.message : String(error);
}

function fieldText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : undefined;
}

function korTravelGeoCandidateKey(candidate: KorTravelGeoCandidate): string {
  const coord = korTravelGeoCandidateToCoord(candidate);
  return [
    candidate.match_kind,
    candidate.address?.road_address,
    candidate.address?.parcel_address,
    candidate.address?.full,
    coord ? coord.lon.toFixed(6) : "",
    coord ? coord.lat.toFixed(6) : "",
    candidate.distance_m,
  ]
    .map((item) => String(item ?? ""))
    .join("|");
}

function korTravelGeoCandidateAddressText(
  candidate: KorTravelGeoCandidate,
): string {
  const address = candidate.address;
  const region = candidate.region;
  const regionText = [
    region?.sido,
    region?.sigungu,
    region?.legal_dong ?? region?.admin_dong,
  ]
    .map((item) => item?.trim())
    .filter(Boolean)
    .join(" ");
  return (
    address?.road_address ??
    address?.parcel_address ??
    address?.full ??
    (regionText.length > 0 ? regionText : undefined) ??
    candidate.match_kind ??
    ""
  );
}

interface FeatureCreateState {
  form: FeatureCreateFormState;
  formError: string | null;
  fieldErrors: Partial<Record<FeatureCreateField, string>>;
  korTravelGeoError: string | null;
  korTravelGeoCandidates: KorTravelGeoCandidate[];
  korTravelGeoPending: boolean;
  selectedKorTravelGeoKey: string | null;
  createdFeatureId: string | null;
}

type FeatureCreateAction =
  | {
      type: "patch-form";
      patch: Partial<FeatureCreateFormState>;
      clearErrors?: FeatureCreateField[];
      selectedCandidateKey?: string;
    }
  | { type: "geo-start" }
  | { type: "geo-success"; candidates: KorTravelGeoCandidate[] }
  | { type: "geo-error"; message: string }
  | { type: "reset" }
  | { type: "submit-start" }
  | {
      type: "validation-errors";
      errors: Partial<Record<FeatureCreateField, string>>;
    }
  | { type: "create-success"; featureId: string }
  | { type: "create-error"; message: string };

function initialFeatureCreateState(): FeatureCreateState {
  return {
    form: initialForm(),
    formError: null,
    fieldErrors: {},
    korTravelGeoError: null,
    korTravelGeoCandidates: [],
    korTravelGeoPending: false,
    selectedKorTravelGeoKey: null,
    createdFeatureId: null,
  };
}

function featureCreateReducer(
  state: FeatureCreateState,
  action: FeatureCreateAction,
): FeatureCreateState {
  switch (action.type) {
    case "patch-form": {
      const fieldErrors = { ...state.fieldErrors };
      for (const field of action.clearErrors ?? []) {
        delete fieldErrors[field];
      }
      return {
        ...state,
        form: { ...state.form, ...action.patch },
        fieldErrors,
        selectedKorTravelGeoKey:
          action.selectedCandidateKey ?? state.selectedKorTravelGeoKey,
      };
    }
    case "geo-start":
      return {
        ...state,
        korTravelGeoError: null,
        korTravelGeoPending: true,
      };
    case "geo-success":
      return {
        ...state,
        korTravelGeoCandidates: action.candidates,
        korTravelGeoPending: false,
        selectedKorTravelGeoKey: null,
      };
    case "geo-error":
      return {
        ...state,
        korTravelGeoError: action.message,
        korTravelGeoPending: false,
      };
    case "reset":
      return initialFeatureCreateState();
    case "submit-start":
      return { ...state, formError: null, fieldErrors: {} };
    case "validation-errors":
      return { ...state, fieldErrors: action.errors };
    case "create-success":
      return { ...state, createdFeatureId: action.featureId };
    case "create-error":
      return { ...state, formError: action.message };
  }
}

function useFeatureCreateClientController() {
  const mapRef = useRef<MapLibreMap | null>(null);
  const geoRequestIdRef = useRef(0);
  const submitCreateInFlightRef = useRef(false);

  const [state, dispatch] = useReducer(
    featureCreateReducer,
    undefined,
    initialFeatureCreateState,
  );
  const {
    createdFeatureId,
    fieldErrors,
    form,
    formError,
    korTravelGeoCandidates,
    korTravelGeoError,
    korTravelGeoPending,
    selectedKorTravelGeoKey,
  } = state;

  const categories = useCategories();
  const createFeature = useCreateAdminFeatureMutation();
  const coord = useMemo(() => coordOrNull(form), [form]);
  const coordError = coordValidationMessage(form);
  const categoryItems = categories.data?.data.items ?? [];
  const formMarkerIconOptions = MARKER_ICON_OPTIONS.includes(form.markerIcon)
    ? MARKER_ICON_OPTIONS
    : [form.markerIcon, ...MARKER_ICON_OPTIONS].filter(Boolean);
  const duplicateRadius = radiusOrNull(form.duplicateRadiusM);
  const nearby = useNearbyFeatures(
    coord && duplicateRadius
      ? {
          lon: coord.lon,
          lat: coord.lat,
          radius_m: duplicateRadius,
          page_size: 8,
          sort: "distance",
        }
      : null,
  );
  const duplicateItems = nearby.data?.data.items ?? [];
  type DuplicateRow = NonNullable<typeof nearby.data>["data"]["items"][number];
  const duplicateColumns = useMemo<ColumnDef<DuplicateRow, unknown>[]>(
    () => [
      {
        id: "feature",
        header: "feature",
        enableSorting: false,
        cell: ({ row }) => {
          const item = row.original;
          return (
            <div className="flex min-w-0 flex-col gap-0.5">
              <Link
                className="truncate rounded-control font-medium text-brand underline-offset-4 hover:text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                href={featureDetailHref(item.feature_id)}
                onClick={(event) => event.stopPropagation()}
              >
                {item.name}
              </Link>
              <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
                {item.kind} · {item.category}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "distance_m",
        header: "거리",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <span className="tabular-nums">{row.original.distance_m.toFixed(1)}m</span>
        ),
      },
    ],
    [],
  );

  const updateForm = <K extends FeatureCreateField>(
    key: K,
    value: FeatureCreateFormState[K],
  ) => {
    dispatch({
      type: "patch-form",
      patch: { [key]: value },
      clearErrors: [key],
    });
  };

  const updateCoord = useCallback((lon: number, lat: number, fly = false) => {
    dispatch({
      type: "patch-form",
      patch: { lon: lon.toFixed(6), lat: lat.toFixed(6) },
      clearErrors: ["lon", "lat"],
    });
    if (fly && mapRef.current) {
      mapRef.current.easeTo({
        center: [lon, lat],
        zoom: Math.max(mapRef.current.getZoom(), 14),
        duration: 400,
      });
    }
  }, []);

  const applyCandidate = (candidate: KorTravelGeoCandidate) => {
    const nextCoord = korTravelGeoCandidateToCoord(candidate);
    const address = korTravelGeoCandidateToAddressRecord(candidate);
    const codes = korTravelGeoCodesFromCandidate(candidate);
    const addressText = korTravelGeoCandidateAddressText(candidate);
    const addressAdmin = fieldText(address.admin);
    const addressLegal = fieldText(address.legal);
    const addressRoad = fieldText(address.road);
    dispatch({
      type: "patch-form",
      selectedCandidateKey: korTravelGeoCandidateKey(candidate),
      patch: {
        ...(addressAdmin !== undefined ? { addressAdmin } : {}),
        ...(addressLegal !== undefined ? { addressLegal } : {}),
        ...(addressRoad !== undefined ? { addressRoad } : {}),
        ...(addressText ? { geocodeQuery: addressText } : {}),
        ...(codes.admin_dong_code
          ? { adminDongCode: codes.admin_dong_code }
          : {}),
        ...(codes.legal_dong_code
          ? { legalDongCode: codes.legal_dong_code }
          : {}),
        ...(codes.road_name_code ? { roadNameCode: codes.road_name_code } : {}),
        ...(codes.sido_code ? { sidoCode: codes.sido_code } : {}),
        ...(codes.sigungu_code ? { sigunguCode: codes.sigungu_code } : {}),
        ...(nextCoord
          ? {
              lon: nextCoord.lon.toFixed(6),
              lat: nextCoord.lat.toFixed(6),
            }
          : {}),
      },
      clearErrors: nextCoord ? ["lon", "lat"] : undefined,
    });
    if (nextCoord && mapRef.current) {
      mapRef.current.easeTo({
        center: [nextCoord.lon, nextCoord.lat],
        zoom: Math.max(mapRef.current.getZoom(), 14),
        duration: 400,
      });
    }
  };

  const runReverseGeocode = async () => {
    const requestId = ++geoRequestIdRef.current;
    dispatch({ type: "geo-start" });
    try {
      const selectedCoord = parseCoord(form);
      const response = await reverseGeocode(selectedCoord);
      if (requestId !== geoRequestIdRef.current) return;
      dispatch({ type: "geo-success", candidates: response.candidates });
      if (response.candidates[0]) {
        applyCandidate(response.candidates[0]);
      }
    } catch (error) {
      if (requestId !== geoRequestIdRef.current) return;
      dispatch({
        type: "geo-error",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const runGeocode = async () => {
    const query = form.geocodeQuery.trim();
    if (query.length === 0) {
      dispatch({ type: "geo-error", message: "주소 검색어를 입력하세요." });
      return;
    }
    const requestId = ++geoRequestIdRef.current;
    dispatch({ type: "geo-start" });
    try {
      const response = await geocodeAddress(query, form.geocodeType);
      if (requestId !== geoRequestIdRef.current) return;
      dispatch({ type: "geo-success", candidates: response.candidates });
      if (response.candidates[0]) {
        applyCandidate(response.candidates[0]);
      }
    } catch (error) {
      if (requestId !== geoRequestIdRef.current) return;
      dispatch({
        type: "geo-error",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const applyMapCenter = () => {
    const center = mapRef.current?.getCenter();
    if (!center) return;
    updateCoord(center.lng, center.lat);
  };

  const resetForm = () => {
    geoRequestIdRef.current += 1;
    dispatch({ type: "reset" });
  };

  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitCreateInFlightRef.current) return;
    dispatch({ type: "submit-start" });
    // §4: 필드 규칙을 제출 전에 일괄 검증해 인라인 에러로 보여준다 —
    // 서버/예외 메시지 keyword 라우팅(구 message.includes 분기)은 제거.
    const result = validateForm(form, [
      { field: "name", validate: required("name은 필수입니다.") },
      { field: "category", validate: required("category는 필수입니다.") },
      { field: "reason", validate: required("reason은 필수입니다.") },
      { field: "lon", validate: required(KOREA_COORD_MESSAGE) },
      { field: "lat", validate: required(KOREA_COORD_MESSAGE) },
      { field: "lon", validate: koreaLongitude() },
      { field: "lat", validate: koreaLatitude() },
      { field: "phone", validate: phoneNumber() },
      { field: "homepageUrl", validate: httpUrl("홈페이지") },
      { field: "sourceUrl", validate: httpUrl("출처") },
      { field: "startDate", validate: dateOrdered("endDate") },
      { field: "addressExtraJson", validate: jsonObject() },
      { field: "detailExtraJson", validate: jsonObject() },
      { field: "urlsExtraJson", validate: jsonObject() },
    ]);
    if (!result.isValid) {
      dispatch({ type: "validation-errors", errors: result.errors });
      return;
    }
    submitCreateInFlightRef.current = true;
    try {
      validateCreateTextFields(form, categoryItems);
      const payload = buildCreatePayload(form);
      const response = await createFeature.mutateAsync(payload);
      dispatch({ type: "create-success", featureId: response.data.feature_id });
    } catch (error) {
      const fieldErrors = manualCreateValidationErrors(error);
      if (fieldErrors !== null) {
        dispatch({ type: "validation-errors", errors: fieldErrors });
      }
      dispatch({ type: "create-error", message: manualCreateErrorMessage(error) });
    } finally {
      submitCreateInFlightRef.current = false;
    }
  };

  return {
    applyCandidate,
    applyMapCenter,
    categories,
    categoryItems,
    coord,
    coordError,
    createFeature,
    createdFeatureId,
    duplicateColumns,
    duplicateItems,
    duplicateRadius,
    fieldErrors,
    form,
    formError,
    formMarkerIconOptions,
    korTravelGeoCandidates,
    korTravelGeoError,
    korTravelGeoPending,
    mapRef,
    nearby,
    resetForm,
    runGeocode,
    runReverseGeocode,
    selectedKorTravelGeoKey,
    submitCreate,
    updateCoord,
    updateForm,
  };
}

type FailureItem = { source: string; message: string | undefined };

function FeatureCreateFeedback({
  createFeature,
  createdFeatureId,
  formError,
  korTravelGeoError,
}: Pick<
  ReturnType<typeof useFeatureCreateClientController>,
  "createFeature" | "createdFeatureId" | "formError" | "korTravelGeoError"
>) {
  const failureCandidates: Array<FailureItem | null> = [
    formError ? { source: "입력 검증", message: formError } : null,
    korTravelGeoError ? { source: "kor-travel-geo", message: korTravelGeoError } : null,
    createFeature.isError
      ? { source: "생성 요청", message: createFeature.error?.message }
      : null,
  ];
  const failures = failureCandidates.filter((item): item is FailureItem => item !== null);
  return (
    // CTA 바로 위의 예약 슬롯 — 오류가 나타나도 저장 행이 밀리지 않는다(M13).
    <div aria-live="polite" className="flex min-h-[1lh] flex-col gap-3">
      {failures.length > 0 ? (
        <Alert variant="destructive">
          <AlertTitle>Feature 작성 실패</AlertTitle>
          <AlertDescription>
            {failures.length === 1 ? (
              <p>{failures[0].message}</p>
            ) : (
              <ul className="list-disc space-y-0.5 pl-4">
                {failures.map((item) => (
                  <li key={item.source}>
                    <span className="font-medium">{item.source}</span>
                    {item.message ? <> — {item.message}</> : null}
                  </li>
                ))}
              </ul>
            )}
            <p>입력값을 고친 뒤 다시 요청을 생성하세요.</p>
          </AlertDescription>
        </Alert>
      ) : null}

      {createdFeatureId ? (
        <Alert>
          <CheckCircle2Icon data-icon="inline-start" />
          <AlertTitle>Feature 생성됨</AlertTitle>
          <AlertDescription>
            수동 Feature가 생성되었습니다. 생성된 feature{" "}
            <Link
              className="rounded-control text-brand underline underline-offset-4 hover:text-brand-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
              href={featureDetailHref(createdFeatureId)}
            >
              {createdFeatureId}
            </Link>
            에서 상세와 상태를 확인하세요.
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

/** 지오코딩 후보 행 — SelectableRow 레시피(테두리 없는 행, 선택 = brand-tint + 좌측 마크)를 native button으로. */
const candidateRowClass =
  "group/row relative flex w-full cursor-pointer flex-col items-start gap-0.5 rounded-control px-3 py-2 text-left text-sm text-text-primary transition-[color,background-color] select-none hover:bg-surface-subtle focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus active:bg-surface-muted aria-pressed:bg-brand-tint aria-pressed:hover:bg-brand-tint aria-pressed:before:absolute aria-pressed:before:inset-y-2 aria-pressed:before:left-0 aria-pressed:before:w-0.5 aria-pressed:before:rounded-full aria-pressed:before:bg-brand aria-pressed:before:content-['']";

function FeatureCreateLocationWorkspace({
  applyCandidate,
  applyMapCenter,
  coord,
  duplicateColumns,
  duplicateItems,
  duplicateRadius,
  fieldErrors,
  form,
  korTravelGeoCandidates,
  korTravelGeoPending,
  mapRef,
  nearby,
  runGeocode,
  runReverseGeocode,
  selectedKorTravelGeoKey,
  updateCoord,
  updateForm,
}: Pick<
  ReturnType<typeof useFeatureCreateClientController>,
  | "applyCandidate"
  | "applyMapCenter"
  | "coord"
  | "duplicateColumns"
  | "duplicateItems"
  | "duplicateRadius"
  | "fieldErrors"
  | "form"
  | "korTravelGeoCandidates"
  | "korTravelGeoPending"
  | "mapRef"
  | "nearby"
  | "runGeocode"
  | "runReverseGeocode"
  | "selectedKorTravelGeoKey"
  | "updateCoord"
  | "updateForm"
>) {
  // 진행 중(pending)은 native disabled가 아니라 Button `loading`이 표현한다 — disabled는
  // "좌표 없음" 같은 진짜 상태 비활성만 남긴다.
  const reverseGeocodeDisabledReason = !coord
    ? "경도·위도를 먼저 입력하거나 지도를 클릭하세요"
    : undefined;
  const nearbyDisabledReason = !coord
    ? "좌표가 있어야 중복 후보를 조회할 수 있습니다"
    : undefined;
  return (
    <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
      <FeatureLocationPreviewSection
        apiKey={VWORLD_KEY}
        coord={coord}
        heightClassName="h-[28rem]"
        markerColor={form.markerColor}
        markerIcon={form.markerIcon}
        testId="feature-create-location-map"
        title={form.name || "new feature"}
        actions={
          <>
            <Button size="sm" type="button" variant="outline" onClick={applyMapCenter}>
              <LocateFixedIcon data-icon="inline-start" />
              중심 사용
            </Button>
            <Button
              disabled={!coord}
              disabledReason={reverseGeocodeDisabledReason}
              loading={korTravelGeoPending && Boolean(coord)}
              size="sm"
              type="button"
              variant="outline"
              onClick={() => void runReverseGeocode()}
            >
              <MapPinIcon data-icon="inline-start" />
              역지오코딩
            </Button>
          </>
        }
        onLoad={(map) => {
          mapRef.current = map;
        }}
        onMapClick={({ lon, lat }) => updateCoord(lon, lat)}
      />

      <div className="flex min-w-0 flex-col gap-4">
        <SectionCard
          actions={
            <span className="text-xs text-text-secondary tabular-nums">
              {korTravelGeoPending ? "조회 중" : `${korTravelGeoCandidates.length}건`}
            </span>
          }
          contentClassName="space-y-3"
          title="kor-travel-geo"
        >
          <FormField
            error={fieldErrors.geocodeQuery}
            hint="주소·지명을 입력해 좌표 후보를 조회합니다."
            label="주소 검색"
            size="sm"
            value={form.geocodeQuery}
            onChange={(event) =>
              updateForm("geocodeQuery", event.target.value)
            }
          />
          <div className="grid gap-x-2 gap-y-1 sm:grid-cols-[9rem_1fr]">
            <FormSelect
              hint="도로명(road)/지번(parcel) 기준"
              label="주소 타입"
              size="sm"
              value={form.geocodeType}
              onChange={(event) =>
                updateForm(
                  "geocodeType",
                  event.target
                    .value as FeatureCreateFormState["geocodeType"],
                )
              }
            >
              <NativeSelectOption value="road">도로명(road)</NativeSelectOption>
              <NativeSelectOption value="parcel">지번(parcel)</NativeSelectOption>
            </FormSelect>
            <div className="flex flex-col gap-1">
              {/* 라벨 높이 스페이서 — 버튼을 왼쪽 select의 컨트롤 baseline에 맞춘다. */}
              <span aria-hidden="true" className="invisible text-xs leading-snug font-medium">
                조회
              </span>
              <Button
                loading={korTravelGeoPending}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => void runGeocode()}
              >
                <SearchIcon data-icon="inline-start" />
                정지오코딩
              </Button>
            </div>
          </div>
          {korTravelGeoCandidates.length > 0 ? (
            <div
              aria-label="지오코딩 후보"
              className="-mx-3 flex flex-col divide-y divide-border border-t border-border pt-1"
              role="group"
            >
              {korTravelGeoCandidates.slice(0, 4).map((candidate) => {
                const candidateCoord =
                  korTravelGeoCandidateToCoord(candidate);
                const address = candidate.address;
                const candidateKey = korTravelGeoCandidateKey(candidate);
                const selected = candidateKey === selectedKorTravelGeoKey;
                return (
                  <button
                    aria-pressed={selected}
                    className={candidateRowClass}
                    key={candidateKey}
                    type="button"
                    onClick={() => applyCandidate(candidate)}
                  >
                    <span className="font-medium">
                      {address?.road_address ??
                        address?.parcel_address ??
                        address?.full ??
                        candidate.match_kind ??
                        "candidate"}
                    </span>
                    <span className="font-mono text-2xs text-text-secondary tabular-nums slashed-zero">
                      {candidateCoord
                        ? `${candidateCoord.lon.toFixed(6)}, ${candidateCoord.lat.toFixed(6)}`
                        : `좌표 ${NULL_GLYPH}`}
                      {typeof candidate.confidence === "number"
                        ? ` · ${candidate.confidence.toFixed(2)}`
                        : ""}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : null}
        </SectionCard>

        <SectionCard
          actions={
            <Button
              disabled={!coord}
              disabledReason={nearbyDisabledReason}
              loading={nearby.isFetching}
              size="sm"
              type="button"
              variant="outline"
              onClick={() => void nearby.refetch()}
            >
              <RefreshCwIcon data-icon="inline-start" />
              재조회
            </Button>
          }
          contentClassName="space-y-3"
          title="중복 후보"
        >
          <FormField
            error={
              duplicateRadius === null
                ? "1 이상 100000 이하 숫자여야 합니다."
                : undefined
            }
            hint="이 반경(m) 안의 기존 feature를 중복 후보로 조회합니다."
            inputMode="numeric"
            label="radius_m"
            size="sm"
            value={form.duplicateRadiusM}
            onChange={(event) =>
              updateForm("duplicateRadiusM", event.target.value)
            }
          />
          {nearby.isError ? (
            <Alert variant="destructive">
              <AlertTitle>중복 후보 조회 실패</AlertTitle>
              <AlertDescription>{nearby.error.message}</AlertDescription>
            </Alert>
          ) : null}
          <DataTable
            columns={duplicateColumns}
            data={duplicateItems}
            emptyState={{
              title: "후보 없음",
              description: coord
                ? "반경 안에 기존 feature가 없습니다."
                : "좌표를 입력하면 자동으로 조회합니다.",
            }}
            getRowId={(row) => row.feature_id}
            isLoading={nearby.isLoading}
            manualSorting={false}
            skeletonRowCount={3}
          />
        </SectionCard>
      </div>
    </section>
  );
}

function FeatureCreateIdentityFields({
  categories,
  categoryItems,
  coordError,
  fieldErrors,
  form,
  formMarkerIconOptions,
  updateForm,
}: Pick<
  ReturnType<typeof useFeatureCreateClientController>,
  | "categories"
  | "categoryItems"
  | "coordError"
  | "fieldErrors"
  | "form"
  | "formMarkerIconOptions"
  | "updateForm"
>) {
  return (
    <>
      <FeatureBasicInfoSection
        category={form.category}
        categoryError={fieldErrors.category}
        categoryItems={categoryItems}
        idPrefix="create"
        kind={form.kind}
        name={form.name}
        nameError={fieldErrors.name}
        placeKind={form.placeKind}
        required
        lifecycleState="active"
        publicationState="published"
        qualityState="valid"
        showStateControls={false}
        onCategoryChange={(value) => updateForm("category", value)}
        onKindChange={(value) =>
          updateForm("kind", value as AdminFeatureCreateKind)
        }
        onNameChange={(value) => updateForm("name", value)}
        onPlaceKindChange={(value) => updateForm("placeKind", value)}
        onLifecycleStateChange={() => undefined}
        onPublicationStateChange={() => undefined}
        onQualityStateChange={() => undefined}
      />
      {categories.isError ? (
        <Alert variant="destructive">
          <AlertTitle>카테고리 목록을 불러오지 못했습니다</AlertTitle>
          <AlertDescription>
            {categories.error.message} — 카테고리 코드를 직접 입력해도 제출할 수 있습니다.
          </AlertDescription>
        </Alert>
      ) : null}

      <SectionCard title="위치/요청">
        <div className="grid gap-x-3 gap-y-1 lg:grid-cols-4">
          <FormField
            error={fieldErrors.lon ?? coordError}
            inputMode="decimal"
            label="경도"
            placeholder="예: 126.978400"
            required
            value={form.lon}
            onChange={(event) => updateForm("lon", event.target.value)}
          />
          <FormField
            error={fieldErrors.lat ?? coordError}
            inputMode="decimal"
            label="위도"
            placeholder="예: 37.566500"
            required
            value={form.lat}
            onChange={(event) => updateForm("lat", event.target.value)}
          />
          <FormSelect
            error={fieldErrors.markerIcon}
            label="마커 아이콘"
            value={form.markerIcon}
            onChange={(event) => updateForm("markerIcon", event.target.value)}
          >
            {formMarkerIconOptions.map((item) => (
              <NativeSelectOption key={item} value={item}>
                {markerIconLabel(item)}
              </NativeSelectOption>
            ))}
          </FormSelect>
          <FormSelect
            error={fieldErrors.markerColor}
            label="마커 색상"
            style={markerColorSelectStyle(form.markerColor)}
            value={form.markerColor}
            onChange={(event) => updateForm("markerColor", event.target.value)}
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
        <div className="grid gap-x-3 gap-y-1 lg:grid-cols-4">
          <FormField
            error={fieldErrors.reason}
            hint="변경 요청 감사 로그에 남는 문장"
            label="사유"
            required
            value={form.reason}
            onChange={(event) => updateForm("reason", event.target.value)}
          />
        </div>
      </SectionCard>
    </>
  );
}

function FeatureCreateDetailFields({
  applyCandidate,
  fieldErrors,
  form,
  updateForm,
}: Pick<
  ReturnType<typeof useFeatureCreateClientController>,
  "applyCandidate" | "fieldErrors" | "form" | "updateForm"
>) {
  return (
    <>
      <FeatureAddressSection
        idPrefix="create"
        values={{
          addressAdmin: form.addressAdmin,
          addressExtraJson: form.addressExtraJson,
          addressLegal: form.addressLegal,
          addressRoad: form.addressRoad,
          adminDongCode: form.adminDongCode,
          legalDongCode: form.legalDongCode,
          roadAddressManagementNo: form.roadAddressManagementNo,
          roadNameCode: form.roadNameCode,
          sidoCode: form.sidoCode,
          sigunguCode: form.sigunguCode,
        }}
        onSelectRegionCandidate={applyCandidate}
        onChange={(field, value) => updateForm(field, value)}
      />
      <FeatureDetailSection
        errors={{
          homepageUrl: fieldErrors.homepageUrl,
          phone: fieldErrors.phone,
          sourceUrl: fieldErrors.sourceUrl,
        }}
        idPrefix="create"
        kind={form.kind}
        values={{
          detailExtraJson: form.detailExtraJson,
          endDate: form.endDate,
          eventStatus: form.eventStatus,
          homepageUrl: form.homepageUrl,
          organizer: form.organizer,
          phone: form.phone,
          sourceUrl: form.sourceUrl,
          startDate: form.startDate,
          urlsExtraJson: form.urlsExtraJson,
          venue: form.venue,
        }}
        onChange={(field, value) => updateForm(field, value)}
      />
    </>
  );
}

function FeatureCreateClientView({
  applyCandidate,
  applyMapCenter,
  categories,
  categoryItems,
  coord,
  coordError,
  createFeature,
  createdFeatureId,
  duplicateColumns,
  duplicateItems,
  duplicateRadius,
  fieldErrors,
  form,
  formError,
  formMarkerIconOptions,
  korTravelGeoCandidates,
  korTravelGeoError,
  korTravelGeoPending,
  mapRef,
  nearby,
  resetForm,
  runGeocode,
  runReverseGeocode,
  selectedKorTravelGeoKey,
  submitCreate,
  updateCoord,
  updateForm,
}: ReturnType<typeof useFeatureCreateClientController>) {
  return (
    <AdminShell
      actions={
        <>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features"
          >
            <ArrowLeftIcon data-icon="inline-start" />
            목록
          </Link>
        </>
      }
      description="새 Feature를 수동으로 생성합니다. 좌표를 먼저 정하고, 기본 정보·주소·상세를 채운 뒤 맨 아래에서 생성합니다."
      title="새 Feature"
    >
      <form className="flex flex-col gap-4" onSubmit={submitCreate}>
        <FeatureCreateLocationWorkspace
          applyCandidate={applyCandidate}
          applyMapCenter={applyMapCenter}
          coord={coord}
          duplicateColumns={duplicateColumns}
          duplicateItems={duplicateItems}
          duplicateRadius={duplicateRadius}
          fieldErrors={fieldErrors}
          form={form}
          korTravelGeoCandidates={korTravelGeoCandidates}
          korTravelGeoPending={korTravelGeoPending}
          mapRef={mapRef}
          nearby={nearby}
          runGeocode={runGeocode}
          runReverseGeocode={runReverseGeocode}
          selectedKorTravelGeoKey={selectedKorTravelGeoKey}
          updateCoord={updateCoord}
          updateForm={updateForm}
        />

        <FeatureCreateIdentityFields
          categories={categories}
          categoryItems={categoryItems}
          coordError={coordError}
          fieldErrors={fieldErrors}
          form={form}
          formMarkerIconOptions={formMarkerIconOptions}
          updateForm={updateForm}
        />

        <FeatureCreateDetailFields
          applyCandidate={applyCandidate}
          fieldErrors={fieldErrors}
          form={form}
          updateForm={updateForm}
        />

        <FeatureCreateFeedback
          createFeature={createFeature}
          createdFeatureId={createdFeatureId}
          formError={formError}
          korTravelGeoError={korTravelGeoError}
        />

        {/* 저장 행 — 폼 맨 끝에 하나(design.md form 변형). primary 1 + secondary 1. */}
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
          <Button type="button" variant="outline" onClick={resetForm}>
            <RotateCcwIcon data-icon="inline-start" />
            초기화
          </Button>
          <Button loading={createFeature.isPending} type="submit">
            <CheckCircle2Icon data-icon="inline-start" />
            Feature 생성
          </Button>
        </div>
      </form>
    </AdminShell>
  );
}

export function FeatureCreateClient() {
  const controller = useFeatureCreateClientController();
  return <FeatureCreateClientView {...controller} />;
}
