"use client";

import { createMarkerElement } from "@kor-travel-map/map-marker-react";
import { type ColumnDef } from "@tanstack/react-table";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  ArrowLeftIcon,
  CheckCircle2Icon,
  ExternalLinkIcon,
  LocateFixedIcon,
  MapPinIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SearchIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import {
  useCreateAdminFeatureMutation,
  useNearbyFeatures,
  type AdminFeatureChangeRecord,
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
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { FormField } from "@/components/ui/form-field-input";
import { FormSelect } from "@/components/ui/form-select";
import { FormTextArea } from "@/components/ui/form-textarea";
import { DataTable } from "@/components/ui/data-table";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";
import { buildVWorldStyle, isVWorldApiKeyConfigured } from "@/lib/vworld-style";
import { DEFAULT_VIEWPORT } from "@/state/map";

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
const CREATE_STATUSES: AdminFeatureCreateRequest["status"][] = [
  "draft",
  "active",
  "inactive",
  "hidden",
];
const CREATE_KINDS: AdminFeatureCreateRequest["kind"][] = ["place", "event"];

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
  operator: string;
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
  status: AdminFeatureCreateRequest["status"];
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
    operator: "local-admin",
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
    status: "active",
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
  if (value.trim().length === 0) {
    return {};
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

function parseCoord(form: FeatureCreateFormState): { lon: number; lat: number } {
  const lon = Number(form.lon);
  const lat = Number(form.lat);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    throw new Error("lon과 lat은 숫자여야 합니다.");
  }
  if (lon < 124 || lon > 132 || lat < 33 || lat > 39.5) {
    throw new Error("좌표는 한국 본토 기준 범위 안이어야 합니다.");
  }
  return { lon, lat };
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
    status: form.status,
    reason: form.reason.trim(),
    operator: optionalString(form.operator),
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

function requestLabel(request: AdminFeatureChangeRecord): string {
  return `${request.action}/${request.status}`;
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

export function FeatureCreateClient() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);

  const [form, setForm] = useState<FeatureCreateFormState>(() => initialForm());
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FeatureCreateField, string>>>({});
  const [korTravelGeoError, setKorTravelGeoError] = useState<string | null>(null);
  const [korTravelGeoCandidates, setKorTravelGeoCandidates] = useState<KorTravelGeoCandidate[]>([]);
  const [korTravelGeoPending, setKorTravelGeoPending] = useState(false);
  const [createdRequest, setCreatedRequest] =
    useState<AdminFeatureChangeRecord | null>(null);

  const createFeature = useCreateAdminFeatureMutation();
  const coord = useMemo(() => coordOrNull(form), [form]);
  const duplicateRadius = radiusOrNull(form.duplicateRadiusM);
  const nearby = useNearbyFeatures(
    coord && duplicateRadius
      ? {
          lon: coord.lon,
          lat: coord.lat,
          radius_m: duplicateRadius,
          page_size: 8,
          sort: "distance",
          status: ["active", "inactive", "hidden"],
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
        header: "distance",
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.distance_m.toFixed(1)}m
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
    ],
    [],
  );

  const updateForm = <K extends FeatureCreateField>(
    key: K,
    value: FeatureCreateFormState[K],
  ) => {
    setForm((current) => ({ ...current, [key]: value }));
    setFieldErrors((current) => ({ ...current, [key]: undefined }));
  };

  const updateCoord = useCallback((lon: number, lat: number, fly = false) => {
    setForm((current) => ({
      ...current,
      lon: lon.toFixed(6),
      lat: lat.toFixed(6),
    }));
    setFieldErrors((current) => ({ ...current, lon: undefined, lat: undefined }));
    if (fly && mapRef.current) {
      mapRef.current.easeTo({
        center: [lon, lat],
        zoom: Math.max(mapRef.current.getZoom(), 14),
        duration: 400,
      });
    }
  }, []);

  useEffect(() => {
    if (containerRef.current === null) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildVWorldStyle(VWORLD_KEY),
      center: [DEFAULT_VIEWPORT.lon, DEFAULT_VIEWPORT.lat],
      zoom: DEFAULT_VIEWPORT.zoom,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right",
    );
    const resizeMap = () => map.resize();
    const resizeFrame = window.requestAnimationFrame(resizeMap);
    const handleClick = (event: maplibregl.MapMouseEvent) => {
      updateCoord(event.lngLat.lng, event.lngLat.lat);
    };
    map.on("load", resizeMap);
    map.on("click", handleClick);
    window.addEventListener("resize", resizeMap);
    return () => {
      window.cancelAnimationFrame(resizeFrame);
      window.removeEventListener("resize", resizeMap);
      map.off("load", resizeMap);
      map.off("click", handleClick);
      markerRef.current?.remove();
      markerRef.current = null;
      map.remove();
      mapRef.current = null;
    };
  }, [updateCoord]);

  useEffect(() => {
    const map = mapRef.current;
    markerRef.current?.remove();
    markerRef.current = null;
    if (!map || !coord) {
      return;
    }
    const marker = new maplibregl.Marker({
      element: createMarkerElement({
        markerColor: form.markerColor,
        markerIcon: form.markerIcon,
        size: 30,
        title: form.name || "new feature",
      }),
    })
      .setLngLat([coord.lon, coord.lat])
      .addTo(map);
    markerRef.current = marker;
  }, [coord, form.markerColor, form.markerIcon, form.name]);

  const applyCandidate = (candidate: KorTravelGeoCandidate) => {
    const nextCoord = korTravelGeoCandidateToCoord(candidate);
    const address = korTravelGeoCandidateToAddressRecord(candidate);
    const codes = korTravelGeoCodesFromCandidate(candidate);
    setForm((current) => ({
      ...current,
      addressAdmin: fieldText(address.admin) ?? current.addressAdmin,
      addressLegal: fieldText(address.legal) ?? current.addressLegal,
      addressRoad: fieldText(address.road) ?? current.addressRoad,
      adminDongCode: codes.admin_dong_code ?? current.adminDongCode,
      legalDongCode: codes.legal_dong_code ?? current.legalDongCode,
      roadNameCode: codes.road_name_code ?? current.roadNameCode,
      sidoCode: codes.sido_code ?? current.sidoCode,
      sigunguCode: codes.sigungu_code ?? current.sigunguCode,
      ...(nextCoord
        ? {
            lon: nextCoord.lon.toFixed(6),
            lat: nextCoord.lat.toFixed(6),
          }
        : {}),
    }));
    if (nextCoord) {
      updateCoord(nextCoord.lon, nextCoord.lat, true);
    }
  };

  const runReverseGeocode = async () => {
    setKorTravelGeoError(null);
    setKorTravelGeoPending(true);
    try {
      const selectedCoord = parseCoord(form);
      const response = await reverseGeocode(selectedCoord);
      setKorTravelGeoCandidates(response.candidates);
      if (response.candidates[0]) {
        applyCandidate(response.candidates[0]);
      }
    } catch (error) {
      setKorTravelGeoError(error instanceof Error ? error.message : String(error));
    } finally {
      setKorTravelGeoPending(false);
    }
  };

  const runGeocode = async () => {
    const query = form.geocodeQuery.trim();
    if (query.length === 0) {
      setKorTravelGeoError("주소 검색어를 입력하세요.");
      return;
    }
    setKorTravelGeoError(null);
    setKorTravelGeoPending(true);
    try {
      const response = await geocodeAddress(query, form.geocodeType);
      setKorTravelGeoCandidates(response.candidates);
      if (response.candidates[0]) {
        applyCandidate(response.candidates[0]);
      }
    } catch (error) {
      setKorTravelGeoError(error instanceof Error ? error.message : String(error));
    } finally {
      setKorTravelGeoPending(false);
    }
  };

  const useMapCenter = () => {
    const center = mapRef.current?.getCenter();
    if (!center) return;
    updateCoord(center.lng, center.lat);
  };

  const resetForm = () => {
    setForm(initialForm());
    setFormError(null);
    setFieldErrors({});
    setKorTravelGeoError(null);
    setKorTravelGeoCandidates([]);
    setCreatedRequest(null);
    markerRef.current?.remove();
    markerRef.current = null;
  };

  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    setFieldErrors({});
    try {
      const payload = buildCreatePayload(form);
      const response = await createFeature.mutateAsync(payload);
      setCreatedRequest(response.data.request);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setFormError(message);
      if (message.includes("name")) {
        setFieldErrors({ name: message });
      } else if (message.includes("category")) {
        setFieldErrors({ category: message });
      } else if (message.includes("reason")) {
        setFieldErrors({ reason: message });
      } else if (message.includes("lon") || message.includes("좌표")) {
        setFieldErrors({ lon: message, lat: message });
      }
    }
  };

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
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features/change-requests"
          >
            변경 요청
          </Link>
        </>
      }
      description="좌표·주소·중복 후보를 함께 검토하는 수동 feature 작성 표면입니다."
      section="Admin"
      title="New feature"
    >
      <form className="flex flex-col gap-4" onSubmit={submitCreate}>
        {(formError || korTravelGeoError || createFeature.isError) && (
          <Alert variant="destructive">
            <AlertTitle>feature 작성 실패</AlertTitle>
            <AlertDescription>
              {formError ?? korTravelGeoError ?? createFeature.error?.message}
            </AlertDescription>
          </Alert>
        )}

        {createdRequest ? (
          <Alert>
            <CheckCircle2Icon data-icon="inline-start" />
            <AlertTitle>change request 생성됨</AlertTitle>
            <AlertDescription>
              {requestLabel(createdRequest)} ·{" "}
              <Link
                className="underline underline-offset-4"
                href="/admin/features/change-requests"
              >
                {shortId(createdRequest.request_id, 18)}
              </Link>
            </AlertDescription>
          </Alert>
        ) : null}

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_28rem]">
          <div className="min-w-0 rounded-lg border bg-background">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <h2 className="font-medium">좌표</h2>
                <p className="text-sm text-muted-foreground">
                  {coord
                    ? `${coord.lon.toFixed(6)}, ${coord.lat.toFixed(6)}`
                    : "좌표 없음"}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" onClick={useMapCenter}>
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
              </div>
            </div>
            <div className="relative h-[28rem]">
              <div
                ref={containerRef}
                className="absolute inset-0 h-full w-full"
                style={{
                  height: "100%",
                  inset: 0,
                  position: "absolute",
                  width: "100%",
                }}
              />
            </div>
            {!isVWorldApiKeyConfigured(VWORLD_KEY) ? (
              <div className="border-t px-4 py-3 text-sm text-muted-foreground">
                VWorld key 미설정 상태라 회색 배경으로 표시합니다.
              </div>
            ) : null}
          </div>

          <div className="flex min-w-0 flex-col gap-4">
            <section className="rounded-lg border bg-background p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 className="font-medium">kor-travel-geo</h2>
                {korTravelGeoPending ? (
                  <Badge variant="outline">조회 중</Badge>
                ) : (
                  <Badge variant="secondary">{korTravelGeoCandidates.length}건</Badge>
                )}
              </div>
              <div className="grid gap-2">
                <FormField
                  error={fieldErrors.geocodeQuery}
                  label="주소 검색"
                  value={form.geocodeQuery}
                  onChange={(event) =>
                    updateForm("geocodeQuery", event.target.value)
                  }
                />
                <div className="grid gap-2 sm:grid-cols-[9rem_1fr]">
                  <FormSelect
                    label="주소 타입"
                    value={form.geocodeType}
                    onChange={(event) =>
                      updateForm(
                        "geocodeType",
                        event.target.value as FeatureCreateFormState["geocodeType"],
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
                    const candidateCoord = korTravelGeoCandidateToCoord(candidate);
                    const address = candidate.address;
                    return (
                      <button
                        className="rounded-md border px-3 py-2 text-left text-sm hover:bg-muted"
                        key={korTravelGeoCandidateKey(candidate)}
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
                  containerClassName="overflow-auto rounded-md border"
                />
              </div>
            </section>
          </div>
        </section>

        <section className="rounded-lg border bg-background p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-medium">기본 정보</h2>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={resetForm}>
                <RotateCcwIcon data-icon="inline-start" />
                초기화
              </Button>
              <Button disabled={createFeature.isPending} type="submit">
                <CheckCircle2Icon data-icon="inline-start" />
                요청 생성
              </Button>
            </div>
          </div>
          <div className="grid gap-3 lg:grid-cols-4">
            <FormSelect
              label="kind"
              value={form.kind}
              onChange={(event) =>
                updateForm(
                  "kind",
                  event.target.value as AdminFeatureCreateRequest["kind"],
                )
              }
            >
              {CREATE_KINDS.map((kind) => (
                <NativeSelectOption key={kind} value={kind}>
                  {kind}
                </NativeSelectOption>
              ))}
            </FormSelect>
            <FormSelect
              label="status"
              value={form.status}
              onChange={(event) =>
                updateForm(
                  "status",
                  event.target.value as AdminFeatureCreateRequest["status"],
                )
              }
            >
              {CREATE_STATUSES.map((status) => (
                <NativeSelectOption key={status} value={status}>
                  {status}
                </NativeSelectOption>
              ))}
            </FormSelect>
            <FormField
              error={fieldErrors.name}
              label="name"
              required
              value={form.name}
              onChange={(event) => updateForm("name", event.target.value)}
            />
            <FormField
              error={fieldErrors.category}
              label="category"
              required
              value={form.category}
              onChange={(event) => updateForm("category", event.target.value)}
            />
          </div>
          <div className="mt-3 grid gap-3 lg:grid-cols-4">
            <FormField
              error={fieldErrors.lon}
              inputMode="decimal"
              label="lon"
              required
              value={form.lon}
              onChange={(event) => updateForm("lon", event.target.value)}
            />
            <FormField
              error={fieldErrors.lat}
              inputMode="decimal"
              label="lat"
              required
              value={form.lat}
              onChange={(event) => updateForm("lat", event.target.value)}
            />
            <FormField
              label="marker_icon"
              value={form.markerIcon}
              onChange={(event) => updateForm("markerIcon", event.target.value)}
            />
            <FormField
              label="marker_color"
              value={form.markerColor}
              onChange={(event) => updateForm("markerColor", event.target.value)}
            />
          </div>
          <div className="mt-3 grid gap-3 lg:grid-cols-4">
            <FormField
              error={fieldErrors.reason}
              label="reason"
              required
              value={form.reason}
              onChange={(event) => updateForm("reason", event.target.value)}
            />
            <FormField
              label="operator"
              value={form.operator}
              onChange={(event) => updateForm("operator", event.target.value)}
            />
            <FormField
              label="feature_id"
              value={form.featureId}
              onChange={(event) => updateForm("featureId", event.target.value)}
            />
            <FormField
              label="idempotency_key"
              value={form.idempotencyKey}
              onChange={(event) =>
                updateForm("idempotencyKey", event.target.value)
              }
            />
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-lg border bg-background p-4">
            <h2 className="mb-4 font-medium">주소</h2>
            <div className="grid gap-3 md:grid-cols-2">
              <FormField
                label="road"
                value={form.addressRoad}
                onChange={(event) => updateForm("addressRoad", event.target.value)}
              />
              <FormField
                label="legal"
                value={form.addressLegal}
                onChange={(event) =>
                  updateForm("addressLegal", event.target.value)
                }
              />
              <FormField
                label="admin"
                value={form.addressAdmin}
                onChange={(event) =>
                  updateForm("addressAdmin", event.target.value)
                }
              />
              <FormField
                label="sigungu_code"
                value={form.sigunguCode}
                onChange={(event) =>
                  updateForm("sigunguCode", event.target.value)
                }
              />
              <FormField
                label="sido_code"
                value={form.sidoCode}
                onChange={(event) => updateForm("sidoCode", event.target.value)}
              />
              <FormField
                label="legal_dong_code"
                value={form.legalDongCode}
                onChange={(event) =>
                  updateForm("legalDongCode", event.target.value)
                }
              />
              <FormField
                label="admin_dong_code"
                value={form.adminDongCode}
                onChange={(event) =>
                  updateForm("adminDongCode", event.target.value)
                }
              />
              <FormField
                label="road_name_code"
                value={form.roadNameCode}
                onChange={(event) =>
                  updateForm("roadNameCode", event.target.value)
                }
              />
              <FormField
                className="md:col-span-2"
                label="road_address_management_no"
                value={form.roadAddressManagementNo}
                onChange={(event) =>
                  updateForm("roadAddressManagementNo", event.target.value)
                }
              />
            </div>
            <FormTextArea
              className="mt-3"
              label="address extra JSON"
              value={form.addressExtraJson}
              onChange={(event) =>
                updateForm("addressExtraJson", event.target.value)
              }
            />
          </div>

          <div className="rounded-lg border bg-background p-4">
            <h2 className="mb-4 font-medium">상세</h2>
            {form.kind === "event" ? (
              <div className="grid gap-3 md:grid-cols-2">
                <FormField
                  label="starts_at"
                  type="datetime-local"
                  value={form.startDate}
                  onChange={(event) => updateForm("startDate", event.target.value)}
                />
                <FormField
                  label="ends_at"
                  type="datetime-local"
                  value={form.endDate}
                  onChange={(event) => updateForm("endDate", event.target.value)}
                />
                <FormField
                  label="event_status"
                  value={form.eventStatus}
                  onChange={(event) =>
                    updateForm("eventStatus", event.target.value)
                  }
                />
                <FormField
                  label="organizer"
                  value={form.organizer}
                  onChange={(event) => updateForm("organizer", event.target.value)}
                />
                <FormField
                  className="md:col-span-2"
                  label="venue"
                  value={form.venue}
                  onChange={(event) => updateForm("venue", event.target.value)}
                />
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                <FormField
                  label="place_kind"
                  value={form.placeKind}
                  onChange={(event) => updateForm("placeKind", event.target.value)}
                />
                <FormField
                  label="phone"
                  value={form.phone}
                  onChange={(event) => updateForm("phone", event.target.value)}
                />
              </div>
            )}
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <FormField
                label="homepage"
                value={form.homepageUrl}
                onChange={(event) => updateForm("homepageUrl", event.target.value)}
              />
              <FormField
                label="source"
                value={form.sourceUrl}
                onChange={(event) => updateForm("sourceUrl", event.target.value)}
              />
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <FormTextArea
                label="detail extra JSON"
                value={form.detailExtraJson}
                onChange={(event) =>
                  updateForm("detailExtraJson", event.target.value)
                }
              />
              <FormTextArea
                label="urls extra JSON"
                value={form.urlsExtraJson}
                onChange={(event) =>
                  updateForm("urlsExtraJson", event.target.value)
                }
              />
            </div>
          </div>
        </section>

        {createdRequest ? (
          <section className="rounded-lg border bg-background p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-medium">생성 요청</h2>
                <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
                  {createdRequest.request_id}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <StatusBadge status={createdRequest.status} />
                <Badge variant="outline">
                  {formatDateTime(createdRequest.created_at)}
                </Badge>
                {createdRequest.status === "applied" ? (
                  <Link
                    className={cn(
                      buttonVariants({ variant: "outline", size: "sm" }),
                    )}
                    href={featureDetailHref(createdRequest.feature_id)}
                  >
                    <ExternalLinkIcon data-icon="inline-start" />
                    상세
                  </Link>
                ) : null}
              </div>
            </div>
          </section>
        ) : null}
      </form>
    </AdminShell>
  );
}
