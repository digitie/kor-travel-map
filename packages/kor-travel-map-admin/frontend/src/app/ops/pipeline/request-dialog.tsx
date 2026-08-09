"use client";

import { PlayIcon } from "lucide-react";
import { memo, useCallback, useMemo, useRef, useState } from "react";

import { ApiClientError, getJson } from "@/api/client";
import {
  type ExecutionKind,
  type FeatureUpdateScope,
  type PipelineDatasetsCatalogResponse,
  type PipelineJobPrecheckResponse,
  useCreateUpdateRequestMutation,
  useMoisSourceSyncPrecheck,
  usePipelineDatasetsCatalog,
  usePreviewUpdateRequestMutation,
} from "@/api/pipeline";
import { statusLabel } from "@/lib/status-label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FormField, FormSelect } from "@/components/ui/form-field";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { formatDateTime, shortId } from "@/lib/format";

type CatalogRow = PipelineDatasetsCatalogResponse["data"]["items"][number];
type CanonicalCatalogRow = CatalogRow & { provider_dataset_id: number };

type ScopeType = FeatureUpdateScope["type"];

type ProviderDatasetScope = {
  type: "provider_dataset";
  provider_dataset_id: number;
  // membership identity는 triple이다(ADR-088) — 서버 스키마가 셋을 모두 요구한다.
  sync_scope: string;
  operation_key: string;
};

type RequestScope =
  | Exclude<FeatureUpdateScope, { type: "provider_dataset" }>
  | ProviderDatasetScope;

const SCOPE_TYPE_LABELS: Record<ScopeType, string> = {
  provider_dataset: "provider/dataset 전체",
  center_radius: "좌표 중심 반경",
  feature_ids: "feature id 목록",
  sigungu_by_radius: "반경 교차 시군구",
  bbox: "bbox 범위",
  cache_target_keys: "캐시 대상 키 목록",
};

// 기본 노출은 provider_dataset·center_radius(설계 §1) — 전체 6-type 선택 가능.
const SCOPE_TYPE_ORDER: readonly ScopeType[] = [
  "provider_dataset",
  "center_radius",
  "feature_ids",
  "sigungu_by_radius",
  "bbox",
  "cache_target_keys",
];

function isMoisProvider(value: string): boolean {
  return value.toLowerCase().includes("mois");
}

function MoisPrecheckNotice({
  data,
  isError,
  isLoading,
}: {
  data: PipelineJobPrecheckResponse["data"] | undefined;
  isError: boolean;
  isLoading: boolean;
}) {
  const sourceReady = data?.ready === true;
  const latestRun = data?.latest_run;
  const completedAt = latestRun?.end_time ?? latestRun?.update_time ?? null;

  return (
    <Alert
      data-testid="mois-precheck-notice"
      variant={sourceReady ? "default" : "destructive"}
    >
      <AlertTitle>MOIS 선행 동기화 확인</AlertTitle>
      <AlertDescription>
        <p>
          MOIS 적재는 Dagster 선행 작업{" "}
          <code className="font-mono">mois_localdata_source_sync</code>가 먼저
          실행되어 있어야 합니다.
        </p>
        <p className="mt-1">
          선행 sync 상태:{" "}
          {isLoading
            ? "확인 중…"
            : isError
              ? "Dagster run 조회 실패 — 요청을 진행할 수 없습니다."
              : sourceReady
                ? `정상 · ${formatDateTime(completedAt)} · ${data.max_age_hours}시간 이내`
                : `${latestRun?.status ?? "이력 없음"} · ${
                    data?.disabled_reason ?? "소스 동기화를 먼저 실행하세요."
                  }`}
        </p>
      </AlertDescription>
    </Alert>
  );
}

function splitList(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function canonicalCatalogRows(
  response: PipelineDatasetsCatalogResponse | undefined,
): CanonicalCatalogRow[] {
  const rows: CanonicalCatalogRow[] = [];
  for (const row of response?.data.items ?? []) {
    const providerDatasetId = (
      row as CatalogRow & { provider_dataset_id?: unknown }
    ).provider_dataset_id;
    if (
      row.catalog_state !== "canonical" ||
      !row.mutable ||
      row.catalog?.is_refreshable !== true ||
      typeof providerDatasetId !== "number" ||
      !Number.isInteger(providerDatasetId) ||
      providerDatasetId < 1
    ) {
      continue;
    }
    rows.push({ ...row, provider_dataset_id: providerDatasetId });
  }
  // **membership마다 한 행**이다. 예전에는 `Map<number, row>`로 dataset당 하나만
  // 남겼는데, 그러면 (a) 남는 행의 `sync_scope`가 임의로 정해지고 (b) 운영자가
  // 기본이 아닌 allowed scope를 고르면 membership 조회가 실패해 "실행 가능한
  // refresh operation이 없습니다"라는 **거짓 사유**로 요청이 막혔다.
  return rows.sort(
    (left, right) =>
      left.provider_dataset_id - right.provider_dataset_id ||
      left.sync_scope.localeCompare(right.sync_scope) ||
      (left.operation_key ?? "").localeCompare(right.operation_key ?? ""),
  );
}

function validateCatalogSelection(
  scope: RequestScope,
  rows: CanonicalCatalogRow[],
): string | null {
  if (scope.type !== "provider_dataset") {
    return null;
  }
  const row = rows.find(
    (item) => item.provider_dataset_id === scope.provider_dataset_id,
  );
  if (!row) {
    return "현재 canonical catalog에 없는 데이터셋입니다.";
  }
  const capability = row.catalog?.scope_refresh;
  if (
    capability?.default_sync_scope !== scope.sync_scope &&
    !capability?.allowed_sync_scopes.includes(scope.sync_scope)
  ) {
    return "현재 catalog capability가 허용하지 않는 sync_scope입니다.";
  }
  return null;
}

function activeConflictRequestId(error: Error | null): string | null {
  if (!(error instanceof ApiClientError) || error.status !== 409) {
    return null;
  }
  const details = error.problem?.details;
  if (typeof details !== "object" || details === null) {
    return null;
  }
  const requestId = (details as Record<string, unknown>).request_id;
  return typeof requestId === "string" ? requestId : null;
}

function useRequestScopeForm(catalogRows: CanonicalCatalogRow[]) {
  const [scopeType, setScopeType] = useState<ScopeType>("provider_dataset");
  const [scopeProviderDatasetId, setScopeProviderDatasetId] = useState("");
  const [scopeSyncScope, setScopeSyncScope] = useState("");
  // identity의 세 번째 축. 후보가 하나면 비워 둔 채로 그것이 쓰이고, 형제
  // operation이 둘 이상일 때만 운영자가 명시한다 — 임의로 고르지 않는다.
  const [scopeOperationKey, setScopeOperationKey] = useState("");
  const [lon, setLon] = useState("126.9780");
  const [lat, setLat] = useState("37.5665");
  const [radiusKm, setRadiusKm] = useState("5");
  const [minLon, setMinLon] = useState("126.7");
  const [minLat, setMinLat] = useState("37.3");
  const [maxLon, setMaxLon] = useState("127.2");
  const [maxLat, setMaxLat] = useState("37.8");
  const [featureIdsText, setFeatureIdsText] = useState("");

  const selectedCatalogRow = useMemo(
    () =>
      catalogRows.find(
        (row) => row.provider_dataset_id === Number(scopeProviderDatasetId),
      ) ?? null,
    [catalogRows, scopeProviderDatasetId],
  );
  // T-VN-33 전에는 provider 이름 입력으로 MOIS 여부를 봤다. 그 입력이 사라져
  // 사전점검 경고가 통째로 없어졌었다(react-doctor가 죽은 export로 잡아냈다).
  // 이제 선택된 catalog 행의 provider로 판정한다 — 같은 사실을 triple 선택에서 읽는다.
  // `scopeType` 가드가 필요하다: `scopeProviderDatasetId` state는 scope 타입을
  // 바꿔도 남으므로, MOIS dataset을 고른 뒤 bbox/center_radius/feature_ids로
  // 전환하면 **provider가 실려 나가지도 않는 요청에** MOIS 경고가 뜬다.
  const moisSelected = useMemo(
    () =>
      scopeType === "provider_dataset" &&
      selectedCatalogRow !== null &&
      isMoisProvider(selectedCatalogRow.provider)
        ? selectedCatalogRow.provider
        : null,
    [scopeType, selectedCatalogRow],
  );
  const selectedScopeCapability =
    selectedCatalogRow?.catalog?.scope_refresh ?? null;
  // `?? []`는 매 렌더 새 배열을 만들어 이 값을 의존성으로 쓰는 훅이 항상 재실행된다.
  const syncScopeOptions = useMemo(
    () => selectedScopeCapability?.allowed_sync_scopes ?? [],
    [selectedScopeCapability],
  );
  const effectiveScopeSyncScope =
    scopeSyncScope.trim() || selectedScopeCapability?.default_sync_scope || "";
  // 고른 (dataset, scope)에 걸린 membership 전부. 형제 operation은 여기서 갈린다 —
  // `.find()`로 하나를 집으면 운영자가 고르지 않은 operation에 canonical write가
  // 나간다(그 위험이 이 목록이 존재하는 이유다).
  const membershipCandidates = useMemo(
    () =>
      catalogRows.filter(
        (row) =>
          row.provider_dataset_id === Number(scopeProviderDatasetId) &&
          row.sync_scope === effectiveScopeSyncScope &&
          typeof row.operation_key === "string" &&
          row.operation_key.length > 0,
      ),
    [catalogRows, effectiveScopeSyncScope, scopeProviderDatasetId],
  );
  const effectiveOperationKey =
    scopeOperationKey.trim() ||
    (membershipCandidates.length === 1
      ? (membershipCandidates[0].operation_key ?? "")
      : "");

  const buildScope = useCallback((): RequestScope | string => {
    if (scopeType === "provider_dataset") {
      const providerDatasetId = Number(scopeProviderDatasetId);
      if (
        !Number.isInteger(providerDatasetId) ||
        providerDatasetId < 1 ||
        selectedCatalogRow === null
      ) {
        return "canonical 데이터셋을 선택하세요.";
      }
      if (!effectiveScopeSyncScope) {
        return "sync_scope를 선택하세요.";
      }
      // grid 행은 membership 단위다(ADR-088 triple) — dataset만으로 고르면 형제
      // operation 중 아무거나 집는다. 고른 scope에 해당하는 행에서 operation을 읽는다.
      if (membershipCandidates.length === 0) {
        return "이 dataset/scope에는 실행 가능한 refresh operation이 없습니다.";
      }
      if (!effectiveOperationKey) {
        return "이 dataset/scope에 refresh operation이 둘 이상입니다. operation을 선택하세요.";
      }
      return {
        type: "provider_dataset",
        provider_dataset_id: providerDatasetId,
        sync_scope: effectiveScopeSyncScope,
        operation_key: effectiveOperationKey,
      };
    }
    if (scopeType === "center_radius" || scopeType === "sigungu_by_radius") {
      const lonValue = Number(lon);
      const latValue = Number(lat);
      const radiusValue = Number(radiusKm);
      if (
        !Number.isFinite(lonValue) ||
        !Number.isFinite(latValue) ||
        !Number.isFinite(radiusValue) ||
        radiusValue <= 0
      ) {
        return "경도/위도/반경(km)을 숫자로 입력하세요.";
      }
      if (scopeType === "center_radius") {
        return {
          type: "center_radius",
          center: { lon: lonValue, lat: latValue },
          radius_km: radiusValue,
        };
      }
      return {
        type: "sigungu_by_radius",
        center: { lon: lonValue, lat: latValue },
        radius_km: radiusValue,
        match: "intersects",
      };
    }
    if (scopeType === "bbox") {
      const values = [minLon, minLat, maxLon, maxLat].map(Number);
      if (values.some((value) => !Number.isFinite(value))) {
        return "bbox 좌표 4개를 숫자로 입력하세요.";
      }
      return {
        type: "bbox",
        min_lon: values[0],
        min_lat: values[1],
        max_lon: values[2],
        max_lat: values[3],
      };
    }
    if (scopeType === "feature_ids") {
      const ids = splitList(featureIdsText);
      if (ids.length === 0) {
        return "feature id를 1개 이상 입력하세요.";
      }
      return { type: "feature_ids", feature_ids: ids };
    }
    return "cache target scope 입력을 확인하세요.";
  }, [
    // `buildScope`가 membership을 고를 때 읽는다(triple의 세 번째 축).
    effectiveOperationKey,
    membershipCandidates,
    effectiveScopeSyncScope,
    featureIdsText,
    lat,
    lon,
    maxLat,
    maxLon,
    minLat,
    minLon,
    radiusKm,
    scopeProviderDatasetId,
    scopeType,
    selectedCatalogRow,
  ]);

  return useMemo(
    () => ({
      buildScope,
      effectiveOperationKey,
      effectiveScopeSyncScope,
      featureIdsText,
      lat,
      lon,
      maxLat,
      maxLon,
      membershipCandidates,
      minLat,
      minLon,
      radiusKm,
      scopeOperationKey,
      scopeProviderDatasetId,
      scopeType,
      moisSelected,
      selectedCatalogRow,
      selectedScopeCapability,
      syncScopeOptions,
      setFeatureIdsText,
      setScopeOperationKey,
      setLat,
      setLon,
      setMaxLat,
      setMaxLon,
      setMinLat,
      setMinLon,
      setRadiusKm,
      setScopeProviderDatasetId,
      setScopeSyncScope,
      setScopeType,
    }),
    [
      buildScope,
      effectiveOperationKey,
      effectiveScopeSyncScope,
      featureIdsText,
      lat,
      moisSelected,
      lon,
      maxLat,
      maxLon,
      membershipCandidates,
      minLat,
      minLon,
      radiusKm,
      scopeOperationKey,
      scopeProviderDatasetId,
      scopeType,
      selectedCatalogRow,
      selectedScopeCapability,
      syncScopeOptions,
    ],
  );
}

function useRequestTargetForm() {
  const [externalSystem, setExternalSystem] = useState("");
  const [targetKeysText, setTargetKeysText] = useState("");
  const [cacheScopeMode, setCacheScopeMode] = useState<
    "center_radius" | "sigungu_by_radius"
  >("center_radius");
  const [cacheRadiusKm, setCacheRadiusKm] = useState("");

  const buildCacheTargetScope = useCallback((): FeatureUpdateScope | string => {
    const keys = splitList(targetKeysText);
    if (!externalSystem.trim() || keys.length === 0) {
      return "external_system과 target key를 입력하세요.";
    }
    const cacheRadius = cacheRadiusKm.trim() ? Number(cacheRadiusKm) : null;
    if (
      cacheRadius !== null &&
      (!Number.isFinite(cacheRadius) || cacheRadius <= 0)
    ) {
      return "cache 반경(km)은 양수여야 합니다.";
    }
    return {
      type: "cache_target_keys",
      external_system: externalSystem.trim(),
      target_keys: keys,
      scope_mode: cacheScopeMode,
      ...(cacheRadius !== null ? { radius_km: cacheRadius } : {}),
    };
  }, [cacheRadiusKm, cacheScopeMode, externalSystem, targetKeysText]);

  return useMemo(
    () => ({
      buildCacheTargetScope,
      cacheRadiusKm,
      cacheScopeMode,
      externalSystem,
      setCacheRadiusKm,
      setCacheScopeMode,
      setExternalSystem,
      setTargetKeysText,
      targetKeysText,
    }),
    [
      buildCacheTargetScope,
      cacheRadiusKm,
      cacheScopeMode,
      externalSystem,
      targetKeysText,
    ],
  );
}

function useRequestExecutionForm() {
  const [runMode, setRunMode] = useState<"queued" | "now">("queued");
  const [priority, setPriority] = useState("50");
  const [dryRun, setDryRun] = useState(true);
  const [reason, setReason] = useState("");

  return useMemo(
    () => ({
      dryRun,
      priority,
      reason,
      runMode,
      setDryRun,
      setPriority,
      setReason,
      setRunMode,
    }),
    [dryRun, priority, reason, runMode],
  );
}

function useRequestCreateDialogController() {
  const [open, setOpen] = useState(false);
  const dialogSessionRef = useRef(0);
  const createPendingRef = useRef(false);
  const submitPendingSessionRef = useRef<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [submittingSession, setSubmittingSession] = useState<number | null>(
    null,
  );
  const [previewInputKey, setPreviewInputKey] = useState<string | null>(null);
  const [createInputKey, setCreateInputKey] = useState<string | null>(null);
  const submittingPrecheck = submittingSession !== null;

  const catalogQuery = usePipelineDatasetsCatalog();
  const catalogRows = useMemo(
    () => canonicalCatalogRows(catalogQuery.data),
    [catalogQuery.data],
  );
  const scopeForm = useRequestScopeForm(catalogRows);
  const moisSelected = scopeForm.moisSelected;
  const moisPrecheck = useMoisSourceSyncPrecheck(moisSelected !== null);
  const targetForm = useRequestTargetForm();
  const executionForm = useRequestExecutionForm();
  const {
    buildScope: buildNonCacheScope,
    effectiveScopeSyncScope,
    scopeProviderDatasetId,
    scopeType,
  } = scopeForm;
  const {
    buildCacheTargetScope,
    cacheRadiusKm,
    cacheScopeMode,
    externalSystem,
    targetKeysText,
  } = targetForm;
  const { dryRun, priority, reason, runMode } = executionForm;

  const createRequest = useCreateUpdateRequestMutation();
  const previewRequest = usePreviewUpdateRequestMutation();
  const formInputKey = JSON.stringify([
    scopeType,
    scopeProviderDatasetId,
    effectiveScopeSyncScope,
    scopeForm.lon,
    scopeForm.lat,
    scopeForm.radiusKm,
    scopeForm.minLon,
    scopeForm.minLat,
    scopeForm.maxLon,
    scopeForm.maxLat,
    scopeForm.featureIdsText,
    externalSystem,
    targetKeysText,
    cacheScopeMode,
    cacheRadiusKm,
    runMode,
    priority,
    dryRun,
    reason,
  ]);

  const resetDialogResult = () => {
    previewRequest.reset();
    createRequest.reset();
    setPreviewInputKey(null);
    setCreateInputKey(null);
    setFormError(null);
    setSubmittingSession(null);
  };

  const openDialog = () => {
    dialogSessionRef.current += 1;
    resetDialogResult();
    setOpen(true);
  };

  const closeDialog = () => {
    if (createPendingRef.current) {
      return;
    }
    dialogSessionRef.current += 1;
    resetDialogResult();
    setOpen(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) {
      openDialog();
    } else {
      closeDialog();
    }
  };

  const submit = async () => {
    const dialogSession = dialogSessionRef.current;
    if (submitPendingSessionRef.current === dialogSession) return;
    const isCurrentDialogSession = () =>
      dialogSessionRef.current === dialogSession;
    previewRequest.reset();
    createRequest.reset();
    setPreviewInputKey(null);
    setCreateInputKey(null);
    const scope: RequestScope | string =
      scopeType === "cache_target_keys"
        ? buildCacheTargetScope()
        : buildNonCacheScope();
    if (typeof scope === "string") {
      setFormError(scope);
      return;
    }
    if (!priority.trim()) {
      setFormError("priority는 비울 수 없습니다.");
      return;
    }
    const priorityValue = Number(priority);
    if (
      !Number.isFinite(priorityValue) ||
      !Number.isInteger(priorityValue) ||
      priorityValue < 0 ||
      priorityValue > 1000
    ) {
      setFormError("priority는 0~1000 사이 정수여야 합니다.");
      return;
    }
    submitPendingSessionRef.current = dialogSession;
    setSubmittingSession(dialogSession);
    setFormError(null);
    try {
      const refreshedCatalog = await catalogQuery.refetch();
      if (!isCurrentDialogSession()) {
        return;
      }
      if (refreshedCatalog.isError || !refreshedCatalog.data) {
        setFormError(
          "provider/dataset 카탈로그 최신 상태를 확인할 수 없어 요청을 진행할 수 없습니다.",
        );
        return;
      }
      const freshRows = canonicalCatalogRows(refreshedCatalog.data);
      const catalogError = validateCatalogSelection(scope, freshRows);
      if (catalogError) {
        setFormError(catalogError);
        return;
      }
      // MOIS 적재는 Dagster 선행 sync가 최근에 성공해 있어야 한다. 화면의 경고만으로는
      // 부족하다 — **제출 직전에 다시 확인**해야 dialog를 연 뒤 상태가 뒤집힌 경우를
      // 막는다. T-VN-33이 provider 이름 입력을 없애면서 이 가드가 통째로 사라졌고,
      // 표시용 경고만 복구돼 있었다(적대 리뷰 8라운드 B4). 조회 실패도 차단이다
      // (fail-closed) — 모르는 상태로 canonical write를 내보내지 않는다.
      if (moisSelected !== null) {
        let precheck: PipelineJobPrecheckResponse;
        try {
          precheck = await getJson<PipelineJobPrecheckResponse>(
            "/v1/ops/pipeline/prechecks/mois-source-sync",
          );
        } catch {
          if (isCurrentDialogSession()) {
            setFormError(
              "MOIS 선행 source sync 최신 상태를 조회할 수 없어 요청을 진행할 수 없습니다.",
            );
          }
          return;
        }
        if (!isCurrentDialogSession()) {
          return;
        }
        if (!precheck.data.ready) {
          setFormError(
            precheck.data.disabled_reason ??
              "MOIS 선행 source sync가 유효한 최근 성공으로 확인되지 않아 요청을 진행할 수 없습니다.",
          );
          return;
        }
      }

      const plan = {
        scope,
        run_mode: runMode,
        priority: priorityValue,
      };
      if (dryRun) {
        try {
          await previewRequest.mutateAsync(plan);
        } catch {
          // mutation error state는 현재 dialog session에서 alert로 표시한다.
        }
        if (isCurrentDialogSession()) {
          setPreviewInputKey(formInputKey);
        }
        return;
      }
      const body = {
        ...plan,
        reason: reason.trim() || null,
      };
      createPendingRef.current = true;
      try {
        await createRequest.mutateAsync(body);
      } catch {
        // mutation error state는 현재 dialog session에서 alert로 표시한다.
      } finally {
        createPendingRef.current = false;
      }
      if (isCurrentDialogSession()) {
        setCreateInputKey(formInputKey);
      }
    } finally {
      if (submitPendingSessionRef.current === dialogSession) {
        submitPendingSessionRef.current = null;
      }
      setSubmittingSession((current) =>
        current === dialogSession ? null : current,
      );
    }
  };

  const matchingPreview = previewInputKey === formInputKey;
  const matchingCreate = createInputKey === formInputKey;
  const requestError = dryRun
    ? matchingPreview
      ? previewRequest.error
      : null
    : matchingCreate
      ? createRequest.error
      : null;
  const retryAfterSeconds =
    requestError instanceof ApiClientError && requestError.status === 409
      ? (requestError.retryAfterSeconds ?? null)
      : null;
  const conflictRequestId = activeConflictRequestId(requestError);
  const created = matchingCreate ? createRequest.data?.data : undefined;
  const preview = matchingPreview ? previewRequest.data?.data : undefined;

  return {
    catalogRows,
    catalogQuery,
    closeDialog,
    conflictRequestId,
    createRequest,
    created,
    executionForm,
    formError,
    handleOpenChange,
    open,
    openDialog,
    preview,
    previewRequest,
    requestError,
    retryAfterSeconds,
    moisPrecheck,
    moisSelected,
    scopeForm,
    setFormError,
    submit,
    submittingPrecheck,
    targetForm,
  };
}

const RequestIdentityFields = memo(function RequestIdentityFields({
  catalogRows,
  clearFormError,
  scopeForm,
}: {
  catalogRows: CanonicalCatalogRow[];
  clearFormError: () => void;
  scopeForm: ReturnType<typeof useRequestScopeForm>;
}) {
  const {
    effectiveScopeSyncScope: scopeSyncScope,
    featureIdsText,
    lat,
    lon,
    maxLat,
    maxLon,
    minLat,
    minLon,
    radiusKm,
    scopeProviderDatasetId,
    scopeType,
    selectedCatalogRow,
    selectedScopeCapability,
    setFeatureIdsText,
    setLat,
    setLon,
    setMaxLat,
    setMaxLon,
    setMinLat,
    setMinLon,
    setRadiusKm,
    setScopeOperationKey,
    setScopeProviderDatasetId,
    setScopeSyncScope,
    setScopeType,
    syncScopeOptions,
    membershipCandidates,
    scopeOperationKey,
  } = scopeForm;
  // 선택 목록은 dataset 단위다 — `catalogRows`는 membership마다 한 행이라 그대로
  // 쓰면 같은 dataset이 여러 번 나오고 React key가 중복된다.
  const datasetOptions = catalogRows.filter(
    (row, index) =>
      catalogRows.findIndex(
        (other) => other.provider_dataset_id === row.provider_dataset_id,
      ) === index,
  );
  const availableSyncScopes = [
    ...syncScopeOptions,
    ...(selectedScopeCapability?.default_sync_scope
      ? [selectedScopeCapability.default_sync_scope]
      : []),
  ].filter((value, index, values) => values.indexOf(value) === index);
  return (
    <>
      <FormSelect
        label="scope 유형"
        value={scopeType}
        onChange={(event) => {
          setScopeType(event.target.value as ScopeType);
          clearFormError();
        }}
      >
        {SCOPE_TYPE_ORDER.map((value) => (
          <NativeSelectOption key={value} value={value}>
            {SCOPE_TYPE_LABELS[value]} ({value})
          </NativeSelectOption>
        ))}
      </FormSelect>

      {scopeType === "provider_dataset" ? (
        <>
          <FormSelect
            label="대상 데이터셋"
            value={scopeProviderDatasetId}
            onChange={(event) => {
              setScopeProviderDatasetId(event.target.value);
              setScopeSyncScope("");
              setScopeOperationKey("");
            }}
          >
            <NativeSelectOption value="">
              canonical 데이터셋 선택
            </NativeSelectOption>
            {datasetOptions.map((row) => (
              <NativeSelectOption
                key={row.provider_dataset_id}
                value={String(row.provider_dataset_id)}
              >
                {row.catalog?.label ?? `데이터셋 #${row.provider_dataset_id}`}
              </NativeSelectOption>
            ))}
          </FormSelect>
          <FormSelect
            disabled={availableSyncScopes.length <= 1}
            hint={
              selectedScopeCapability?.effect === "dataset_wide"
                ? "dataset-wide 정본 scope로 고정됩니다."
                : "catalog가 허용한 canonical sync scope만 선택할 수 있습니다."
            }
            label="sync_scope"
            value={scopeSyncScope}
            onChange={(event) => {
              setScopeSyncScope(event.target.value);
              setScopeOperationKey("");
            }}
          >
            {availableSyncScopes.length === 0 ? (
              <NativeSelectOption value="">
                데이터셋을 먼저 선택하세요.
              </NativeSelectOption>
            ) : (
              availableSyncScopes.map((syncScope) => (
                <NativeSelectOption key={syncScope} value={syncScope}>
                  {syncScope}
                </NativeSelectOption>
              ))
            )}
          </FormSelect>
          {membershipCandidates.length > 1 ? (
            // 형제 operation이 있을 때만 뜬다. 평소에는 축이 하나로 결정되므로
            // 화면을 늘리지 않고, 갈릴 때는 **운영자가 고르게** 한다.
            <FormSelect
              hint="이 dataset/scope에 refresh operation이 둘 이상입니다. 어느 operation에 요청할지 고르세요."
              label="operation_key"
              value={scopeOperationKey}
              onChange={(event) => setScopeOperationKey(event.target.value)}
            >
              <NativeSelectOption value="">operation 선택</NativeSelectOption>
              {membershipCandidates.map((row) => (
                <NativeSelectOption
                  key={row.operation_key ?? ""}
                  value={row.operation_key ?? ""}
                >
                  {row.operation_key}
                </NativeSelectOption>
              ))}
            </FormSelect>
          ) : null}
          {selectedCatalogRow ? (
            <p className="text-xs text-muted-foreground">
              canonical membership: {selectedCatalogRow.provider_dataset_id}
            </p>
          ) : null}
        </>
      ) : null}

      {scopeType === "center_radius" || scopeType === "sigungu_by_radius" ? (
        <>
          <div className="grid grid-cols-3 gap-2">
            <FormField
              label="경도"
              required
              value={lon}
              onChange={(event) => setLon(event.target.value)}
            />
            <FormField
              label="위도"
              required
              value={lat}
              onChange={(event) => setLat(event.target.value)}
            />
            <FormField
              label="반경(km)"
              required
              value={radiusKm}
              onChange={(event) => setRadiusKm(event.target.value)}
            />
          </div>
          {scopeType === "sigungu_by_radius" ? (
            <p className="text-xs text-muted-foreground">
              시군구 매칭은 canonical intersects 방식으로 계산됩니다.
            </p>
          ) : null}
        </>
      ) : null}

      {scopeType === "bbox" ? (
        <div className="grid grid-cols-2 gap-2">
          <FormField
            label="min_lon"
            required
            value={minLon}
            onChange={(event) => setMinLon(event.target.value)}
          />
          <FormField
            label="min_lat"
            required
            value={minLat}
            onChange={(event) => setMinLat(event.target.value)}
          />
          <FormField
            label="max_lon"
            required
            value={maxLon}
            onChange={(event) => setMaxLon(event.target.value)}
          />
          <FormField
            label="max_lat"
            required
            value={maxLat}
            onChange={(event) => setMaxLat(event.target.value)}
          />
        </div>
      ) : null}

      {scopeType === "feature_ids" ? (
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-muted-foreground">
            feature id 목록 (줄바꿈/쉼표 구분, 최대 1000)
          </span>
          <textarea
            aria-label="feature id 목록"
            className="min-h-24 rounded-md border bg-background p-2 font-mono text-xs"
            value={featureIdsText}
            onChange={(event) => setFeatureIdsText(event.target.value)}
          />
        </label>
      ) : null}
    </>
  );
});

const RequestTargetFields = memo(function RequestTargetFields({
  scopeType,
  targetForm,
}: {
  scopeType: ScopeType;
  targetForm: ReturnType<typeof useRequestTargetForm>;
}) {
  const {
    cacheRadiusKm,
    cacheScopeMode,
    externalSystem,
    setCacheRadiusKm,
    setCacheScopeMode,
    setExternalSystem,
    setTargetKeysText,
    targetKeysText,
  } = targetForm;
  return (
    <>
      {scopeType === "cache_target_keys" ? (
        <>
          <FormField
            label="external_system"
            placeholder="예: pinvi"
            required
            value={externalSystem}
            onChange={(event) => setExternalSystem(event.target.value)}
          />
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-medium text-muted-foreground">
              target key 목록 (줄바꿈/쉼표 구분, 최대 500)
            </span>
            <textarea
              aria-label="target key 목록"
              className="min-h-24 rounded-md border bg-background p-2 font-mono text-xs"
              value={targetKeysText}
              onChange={(event) => setTargetKeysText(event.target.value)}
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <FormSelect
              label="scope 모드"
              value={cacheScopeMode}
              onChange={(event) =>
                setCacheScopeMode(
                  event.target.value as "center_radius" | "sigungu_by_radius",
                )
              }
            >
              <NativeSelectOption value="center_radius">
                좌표 반경(center_radius)
              </NativeSelectOption>
              <NativeSelectOption value="sigungu_by_radius">
                시군구 반경(sigungu_by_radius)
              </NativeSelectOption>
            </FormSelect>
            <FormField
              hint="비우면 기본 반경."
              label="반경(km, 선택)"
              value={cacheRadiusKm}
              onChange={(event) => setCacheRadiusKm(event.target.value)}
            />
          </div>
        </>
      ) : null}
    </>
  );
});

const RequestExecutionSettings = memo(function RequestExecutionSettings({
  executionForm,
}: {
  executionForm: ReturnType<typeof useRequestExecutionForm>;
}) {
  const {
    dryRun,
    priority,
    reason,
    runMode,
    setDryRun,
    setPriority,
    setReason,
    setRunMode,
  } = executionForm;
  return (
    <>
      <div className="grid grid-cols-2 gap-2">
        <FormSelect
          label="실행 모드"
          value={runMode}
          onChange={(event) =>
            setRunMode(event.target.value as "queued" | "now")
          }
        >
          <NativeSelectOption value="queued">예약(queued)</NativeSelectOption>
          <NativeSelectOption value="now">즉시(now)</NativeSelectOption>
        </FormSelect>
        <FormField
          hint="0~1000 정수, 높을수록 먼저 실행. 소수는 허용하지 않습니다."
          label="priority"
          max={1000}
          min={0}
          step={1}
          type="number"
          value={priority}
          onChange={(event) => setPriority(event.target.value)}
        />
      </div>
      {!dryRun ? (
        <FormField
          hint="operator는 로그인한 admin actor로 서버에서 기록됩니다."
          label="사유"
          placeholder="감사 로그에 남는 요청 사유"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      ) : null}
      <label className="flex items-center gap-2 text-sm">
        <input
          checked={dryRun}
          type="checkbox"
          onChange={(event) => setDryRun(event.target.checked)}
        />
        dry-run(행을 만들지 않고 대상 수만 확인)
      </label>
    </>
  );
});

function RequestResultFeedback({
  catalogQuery,
  closeDialog,
  conflictRequestId,
  createRequest,
  created,
  formError,
  moisPrecheck,
  moisSelected,
  onCreated,
  preview,
  requestError,
  retryAfterSeconds,
}: Pick<
  ReturnType<typeof useRequestCreateDialogController>,
  | "catalogQuery"
  | "closeDialog"
  | "conflictRequestId"
  | "createRequest"
  | "created"
  | "formError"
  | "moisPrecheck"
  | "moisSelected"
  | "preview"
  | "requestError"
  | "retryAfterSeconds"
> & {
  onCreated: (kind: ExecutionKind, id: string) => void;
}) {
  return (
    <>
      {catalogQuery.isError ? (
        <Alert variant="destructive">
          <AlertTitle>canonical catalog 조회 실패</AlertTitle>
          <AlertDescription>
            provider/dataset 조합을 검증할 수 없어 요청 생성과 dry-run을
            차단합니다. {catalogQuery.error.message}
          </AlertDescription>
        </Alert>
      ) : null}

      {moisSelected ? (
        <MoisPrecheckNotice
          isError={moisPrecheck.isError}
          isLoading={moisPrecheck.isLoading}
          data={moisPrecheck.data?.data}
        />
      ) : null}

      {formError ? (
        <Alert variant="destructive">
          <AlertTitle>입력 확인</AlertTitle>
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      ) : null}
      {requestError ? (
        <Alert variant="destructive">
          <AlertTitle>요청 생성 실패</AlertTitle>
          <AlertDescription className="space-y-2">
            {retryAfterSeconds !== null
              ? `동일 scope 요청이 이미 실행 중입니다 — 약 ${retryAfterSeconds}초 후 다시 시도하세요.`
              : requestError.message}
            {conflictRequestId ? (
              <Button
                size="sm"
                type="button"
                variant="outline"
                onClick={() => {
                  closeDialog();
                  onCreated("update_request", conflictRequestId);
                }}
              >
                기존 활성 요청 열기
              </Button>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}
      {preview ? (
        <Alert data-testid="request-preview-result">
          <AlertTitle>미리보기 결과</AlertTitle>
          <AlertDescription className="space-y-1">
            <p>실행 membership: {preview.dataset_memberships.length}개</p>
            <ul className="font-mono text-xs">
              {preview.dataset_memberships.map((membership) => (
                <li
                  key={`${membership.provider_dataset_id}:${membership.sync_scope}`}
                >
                  {membership.provider_dataset_id} · {membership.sync_scope}
                </li>
              ))}
            </ul>
            <p>매칭 대상: {JSON.stringify(preview.matched_scope)}</p>
          </AlertDescription>
        </Alert>
      ) : null}
      {created ? (
        <Alert data-testid="request-create-result">
          <AlertTitle>
            {createRequest.data?.idempotent_replay
              ? "동일 요청 결과 재생"
              : createRequest.data?.reused_active_request
                ? "기존 활성 요청 재사용"
                : "요청 생성됨"}
          </AlertTitle>
          <AlertDescription className="space-y-1">
            <p>
              상태: {statusLabel(created.status)}
              {" · "}
              <span className="font-mono">{shortId(created.request_id)}</span>
            </p>
            <p>실행 membership: {created.dataset_memberships.length}개</p>
            <ul className="font-mono text-xs">
              {created.dataset_memberships.map((membership) => (
                <li
                  key={`${membership.provider_dataset_id}:${membership.sync_scope}`}
                >
                  {membership.provider_dataset_id} · {membership.sync_scope}
                </li>
              ))}
            </ul>
            <Button
              size="sm"
              type="button"
              variant="outline"
              onClick={() => {
                closeDialog();
                onCreated("update_request", created.request_id);
              }}
            >
              타임라인에서 보기
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}
    </>
  );
}

export function RequestCreateDialog({
  onCreated,
}: {
  onCreated: (kind: ExecutionKind, id: string) => void;
}) {
  const {
    catalogQuery,
    catalogRows,
    closeDialog,
    conflictRequestId,
    createRequest,
    created,
    executionForm,
    formError,
    handleOpenChange,
    moisPrecheck,
    moisSelected,
    open,
    openDialog,
    preview,
    previewRequest,
    requestError,
    retryAfterSeconds,
    scopeForm,
    setFormError,
    submit,
    submittingPrecheck,
    targetForm,
  } = useRequestCreateDialogController();
  const clearFormError = useCallback(() => setFormError(null), [setFormError]);

  return (
    <>
      <Button type="button" onClick={openDialog}>
        <PlayIcon data-icon="inline-start" />
        갱신 요청 생성
      </Button>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>갱신 요청 생성</DialogTitle>
            <DialogDescription>
              6종 scope 전부 선택 가능 — dry-run으로 대상 수를 먼저 확인하세요.
            </DialogDescription>
          </DialogHeader>
          <fieldset
            className="m-0 flex min-w-0 max-h-[65vh] flex-col gap-3 overflow-y-auto border-0 p-0 pr-1"
            disabled={createRequest.isPending || submittingPrecheck}
          >
            <RequestIdentityFields
              catalogRows={catalogRows}
              clearFormError={clearFormError}
              scopeForm={scopeForm}
            />

            <RequestTargetFields
              scopeType={scopeForm.scopeType}
              targetForm={targetForm}
            />

            <RequestExecutionSettings executionForm={executionForm} />

            <RequestResultFeedback
              catalogQuery={catalogQuery}
              closeDialog={closeDialog}
              conflictRequestId={conflictRequestId}
              createRequest={createRequest}
              created={created}
              formError={formError}
              moisPrecheck={moisPrecheck}
              moisSelected={moisSelected}
              onCreated={onCreated}
              preview={preview}
              requestError={requestError}
              retryAfterSeconds={retryAfterSeconds}
            />
          </fieldset>
          <DialogFooter>
            <Button
              disabled={createRequest.isPending}
              type="button"
              variant="outline"
              onClick={closeDialog}
            >
              닫기
            </Button>
            <Button
              disabled={
                createRequest.isPending ||
                previewRequest.isPending ||
                submittingPrecheck ||
                catalogQuery.isLoading ||
                catalogQuery.isError
              }
              type="button"
              onClick={() => void submit()}
            >
              {executionForm.dryRun ? "dry-run 실행" : "요청 생성"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
