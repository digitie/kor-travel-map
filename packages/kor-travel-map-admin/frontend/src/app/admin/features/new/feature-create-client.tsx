"use client";

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
import {
  useCreateAdminFeatureMutation,
  useNearbyFeatures,
  type AdminFeatureCreateRequest,
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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { FormField } from "@/components/ui/form-field-input";
import { FormSelect } from "@/components/ui/form-select";
import { DataTable } from "@/components/ui/data-table";
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
  featureId: string;
  geocodeQuery: string;
  geocodeType: "parcel" | "road";
  homepageUrl: string;
  idempotencyKey: string;
  kind: AdminFeatureCreateRequest["kind"];
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
  lifecycleState: AdminFeatureCreateRequest["lifecycle_state"];
  publicationState: AdminFeatureCreateRequest["publication_state"];
  qualityState: AdminFeatureCreateRequest["quality_state"];
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
    featureId: "",
    geocodeQuery: "",
    geocodeType: "road",
    homepageUrl: "",
    idempotencyKey: "",
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
    lifecycleState: "active",
    publicationState: "published",
    qualityState: "valid",
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
    lifecycle_state: form.lifecycleState,
    publication_state: form.publicationState,
    quality_state: form.qualityState,
    reason: form.reason.trim(),
    feature_id: optionalString(form.featureId),
    idempotency_key: optionalString(form.idempotencyKey),
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
            <>
              <Link
                className="font-medium text-primary underline-offset-4 hover:underline"
                href={featureDetailHref(item.feature_id)}
                onClick={(event) => event.stopPropagation()}
              >
                {item.name}
              </Link>
              <div className="mt-1 flex flex-wrap gap-1">
                <Badge variant="outline">{item.kind}</Badge>
                <Badge variant="outline">{item.category}</Badge>
              </div>
            </>
          );
        },
      },
      {
        accessorKey: "distance_m",
        header: "거리",
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.distance_m.toFixed(1)}m
          </span>
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
        ...(addressAdmin !== null ? { addressAdmin } : {}),
        ...(addressLegal !== null ? { addressLegal } : {}),
        ...(addressRoad !== null ? { addressRoad } : {}),
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
      const message = error instanceof Error ? error.message : String(error);
      dispatch({ type: "create-error", message });
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

function FeatureCreateFeedback({
  createFeature,
  createdFeatureId,
  formError,
  korTravelGeoError,
}: Pick<
  ReturnType<typeof useFeatureCreateClientController>,
  "createFeature" | "createdFeatureId" | "formError" | "korTravelGeoError"
>) {
  return (
    <>
      {(formError || korTravelGeoError || createFeature.isError) && (
        <Alert variant="destructive">
          <AlertTitle>Feature 작성 실패</AlertTitle>
          <AlertDescription>
            {formError ?? korTravelGeoError ?? createFeature.error?.message}
          </AlertDescription>
        </Alert>
      )}

      {createdFeatureId ? (
        <Alert>
          <CheckCircle2Icon data-icon="inline-start" />
          <AlertTitle>Feature 생성됨</AlertTitle>
          <AlertDescription>
            <Link
              className="underline underline-offset-4"
              href={featureDetailHref(createdFeatureId)}
            >
              {createdFeatureId}
            </Link>
          </AlertDescription>
        </Alert>
      ) : null}
    </>
  );
}

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
  return (
    <>
      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_28rem]">
        <FeatureLocationPreviewSection
          apiKey={VWORLD_KEY}
          className="h-full"
          coord={coord}
          heightClassName="min-h-[28rem] flex-1"
          markerColor={form.markerColor}
          markerIcon={form.markerIcon}
          testId="feature-create-location-map"
          title={form.name || "new feature"}
          actions={
            <>
              <Button type="button" variant="outline" onClick={applyMapCenter}>
                <LocateFixedIcon data-icon="inline-start" />
                중심 사용
              </Button>
              <Button
                disabled={!coord || korTravelGeoPending}
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
          <section className="rounded-lg border bg-background p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="font-medium">kor-travel-geo</h2>
              {korTravelGeoPending ? (
                <Badge variant="outline">조회 중</Badge>
              ) : (
                <Badge variant="secondary">
                  {korTravelGeoCandidates.length}건
                </Badge>
              )}
            </div>
            <div className="grid gap-2">
              <FormField
                error={fieldErrors.geocodeQuery}
                label="주소 검색"
                hint="주소·지명을 입력해 좌표 후보를 조회합니다."
                value={form.geocodeQuery}
                onChange={(event) =>
                  updateForm("geocodeQuery", event.target.value)
                }
              />
              <div className="grid gap-2 sm:grid-cols-[9rem_1fr]">
                <FormSelect
                  label="주소 타입"
                  hint="도로명(road)/지번(parcel) 지오코딩 기준입니다."
                  value={form.geocodeType}
                  onChange={(event) =>
                    updateForm(
                      "geocodeType",
                      event.target
                        .value as FeatureCreateFormState["geocodeType"],
                    )
                  }
                >
                  <NativeSelectOption value="road">road</NativeSelectOption>
                  <NativeSelectOption value="parcel">parcel</NativeSelectOption>
                </FormSelect>
                <Button
                  className="self-end"
                  disabled={korTravelGeoPending}
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
              <div className="mt-4 flex flex-col gap-2">
                {korTravelGeoCandidates.slice(0, 4).map((candidate) => {
                  const candidateCoord =
                    korTravelGeoCandidateToCoord(candidate);
                  const address = candidate.address;
                  const candidateKey = korTravelGeoCandidateKey(candidate);
                  const selected = candidateKey === selectedKorTravelGeoKey;
                  return (
                    <button
                      className={cn(
                        "rounded-md border px-3 py-2 text-left text-sm hover:bg-muted",
                        selected
                          ? "border-primary bg-primary/10 text-primary"
                          : null,
                      )}
                      key={candidateKey}
                      type="button"
                      onClick={() => applyCandidate(candidate)}
                    >
                      <div className="font-medium">
                        {address?.road_address ??
                          address?.parcel_address ??
                          address?.full ??
                          candidate.match_kind ??
                          "candidate"}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {candidateCoord
                          ? `${candidateCoord.lon.toFixed(6)}, ${candidateCoord.lat.toFixed(6)}`
                          : "coord 없음"}
                        {typeof candidate.confidence === "number"
                          ? ` · ${candidate.confidence.toFixed(2)}`
                          : ""}
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </section>

          <section className="rounded-lg border bg-background p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="font-medium">중복 후보</h2>
              <Button
                disabled={!coord || nearby.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => void nearby.refetch()}
              >
                <RefreshCwIcon data-icon="inline-start" />
                재조회
              </Button>
            </div>
            <FormField
              error={
                duplicateRadius === null
                  ? "1 이상 100000 이하 숫자여야 합니다."
                  : undefined
              }
              inputMode="numeric"
              label="radius_m"
              hint="이 반경(m) 내 기존 feature를 중복 후보로 조회합니다."
              value={form.duplicateRadiusM}
              onChange={(event) =>
                updateForm("duplicateRadiusM", event.target.value)
              }
            />
            {nearby.isError ? (
              <Alert className="mt-4" variant="destructive">
                <AlertTitle>중복 후보 조회 실패</AlertTitle>
                <AlertDescription>{nearby.error.message}</AlertDescription>
              </Alert>
            ) : null}
            <div className="mt-4">
              <DataTable
                columns={duplicateColumns}
                data={duplicateItems}
                getRowId={(row) => row.feature_id}
                isLoading={nearby.isLoading}
                emptyMessage="후보 없음"
                manualSorting={false}
                containerClassName="overflow-auto rounded-md border"
              />
            </div>
          </section>
        </div>
      </section>
    </>
  );
}

function FeatureCreateIdentityFields({
  categories,
  categoryItems,
  coordError,
  createFeature,
  fieldErrors,
  form,
  formMarkerIconOptions,
  resetForm,
  updateForm,
}: Pick<
  ReturnType<typeof useFeatureCreateClientController>,
  | "categories"
  | "categoryItems"
  | "coordError"
  | "createFeature"
  | "fieldErrors"
  | "form"
  | "formMarkerIconOptions"
  | "resetForm"
  | "updateForm"
>) {
  return (
    <>
      <FeatureBasicInfoSection
        actions={
          <>
            <Button type="button" variant="outline" onClick={resetForm}>
              <RotateCcwIcon data-icon="inline-start" />
              초기화
            </Button>
            <Button disabled={createFeature.isPending} type="submit">
              <CheckCircle2Icon data-icon="inline-start" />
              요청 생성
            </Button>
          </>
        }
        category={form.category}
        categoryError={fieldErrors.category}
        categoryItems={categoryItems}
        idPrefix="create"
        kind={form.kind}
        name={form.name}
        nameError={fieldErrors.name}
        placeKind={form.placeKind}
        required
        lifecycleState={form.lifecycleState}
        publicationState={form.publicationState}
        qualityState={form.qualityState}
        onCategoryChange={(value) => updateForm("category", value)}
        onKindChange={(value) =>
          updateForm("kind", value as AdminFeatureCreateRequest["kind"])
        }
        onNameChange={(value) => updateForm("name", value)}
        onPlaceKindChange={(value) => updateForm("placeKind", value)}
        onLifecycleStateChange={(value) => updateForm("lifecycleState", value)}
        onPublicationStateChange={(value) =>
          updateForm("publicationState", value)
        }
        onQualityStateChange={(value) => updateForm("qualityState", value)}
      />
      {categories.isError ? (
        <div className="text-sm text-destructive">
          {categories.error.message}
        </div>
      ) : null}

      <section className="rounded-lg border bg-background p-4">
        <h2 className="mb-4 font-medium">위치/요청</h2>
        <div className="grid gap-3 lg:grid-cols-4">
          <FormField
            error={fieldErrors.lon ?? coordError}
            inputMode="decimal"
            label="경도"
            required
            value={form.lon}
            onChange={(event) => updateForm("lon", event.target.value)}
          />
          <FormField
            error={fieldErrors.lat ?? coordError}
            inputMode="decimal"
            label="위도"
            required
            value={form.lat}
            onChange={(event) => updateForm("lat", event.target.value)}
          />
          <FormSelect
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
        <div className="mt-3 grid gap-3 lg:grid-cols-4">
          <FormField
            error={fieldErrors.reason}
            label="사유"
            required
            value={form.reason}
            onChange={(event) => updateForm("reason", event.target.value)}
          />
          <FormField
            label="Feature ID"
            hint="비우면 자동 생성됩니다."
            value={form.featureId}
            onChange={(event) => updateForm("featureId", event.target.value)}
          />
          <FormField
            label="중복 방지 키"
            value={form.idempotencyKey}
            onChange={(event) =>
              updateForm("idempotencyKey", event.target.value)
            }
          />
        </div>
      </section>
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
      <section className="grid gap-4 xl:grid-cols-2">
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
      </section>
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
      description="새 Feature를 등록합니다."
      title="새 Feature"
    >
      <form className="flex flex-col gap-4" onSubmit={submitCreate}>
        <FeatureCreateFeedback
          createFeature={createFeature}
          createdFeatureId={createdFeatureId}
          formError={formError}
          korTravelGeoError={korTravelGeoError}
        />

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
          createFeature={createFeature}
          fieldErrors={fieldErrors}
          form={form}
          formMarkerIconOptions={formMarkerIconOptions}
          resetForm={resetForm}
          updateForm={updateForm}
        />

        <FeatureCreateDetailFields
          applyCandidate={applyCandidate}
          fieldErrors={fieldErrors}
          form={form}
          updateForm={updateForm}
        />
      </form>
    </AdminShell>
  );
}

export function FeatureCreateClient() {
  const controller = useFeatureCreateClientController();
  return <FeatureCreateClientView {...controller} />;
}
