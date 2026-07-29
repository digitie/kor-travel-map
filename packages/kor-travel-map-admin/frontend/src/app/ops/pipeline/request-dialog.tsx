"use client";

import { PlayIcon } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { ApiClientError, getJson } from "@/api/client";
import {
  type ExecutionKind,
  type FeatureUpdateRequestCreateRequest,
  type FeatureUpdateRequestPreviewRequest,
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
import { ComboboxMultiple } from "@/components/ui/combobox-multiple";
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

type ScopeType = FeatureUpdateScope["type"];

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

function splitList(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function isMoisProvider(value: string): boolean {
  return value.toLowerCase().includes("mois");
}

function canonicalCatalogRows(
  response: PipelineDatasetsCatalogResponse | undefined,
): CatalogRow[] {
  return (response?.data.items ?? []).filter(
    (row) =>
      row.catalog_state === "canonical" &&
      row.mutable &&
      row.catalog?.is_refreshable === true,
  );
}

function selectedMoisProvider(
  rows: CatalogRow[],
  scope: FeatureUpdateScope,
  providers: string[],
  datasetKeys: string[],
): string | null {
  const candidates = [...providers];
  if (scope.type === "provider_dataset") {
    candidates.push(scope.provider);
  }
  const datasetKeySet = new Set(datasetKeys);
  for (const row of rows) {
    if (datasetKeySet.has(row.dataset_key) && isMoisProvider(row.provider)) {
      candidates.push(row.provider);
    }
  }
  return candidates.find(isMoisProvider) ?? null;
}

function catalogPair(
  rows: CatalogRow[],
  provider: string,
  datasetKey: string,
): CatalogRow[] {
  return rows.filter(
    (row) => row.provider === provider && row.dataset_key === datasetKey,
  );
}

function validateCatalogSelection(
  scope: FeatureUpdateScope,
  effectiveProviders: string[],
  effectiveDatasetKeys: string[],
  rows: CatalogRow[],
): string | null {
  if (scope.type === "provider_dataset") {
    const pairRows = catalogPair(rows, scope.provider, scope.dataset_key);
    const requestedSyncScope = scope.sync_scope;
    if (pairRows.length === 0) {
      return "현재 canonical catalog에 없는 provider/dataset 조합입니다.";
    }
    if (
      requestedSyncScope &&
      !pairRows.some((row) => {
        const capability = row.catalog?.scope_refresh;
        return Boolean(
          capability?.effect === "sync_scope" &&
            capability.supported &&
            capability.selector !== "none" &&
            capability.allowed_sync_scopes.some(
              (value) => value === requestedSyncScope,
            ),
        );
      })
    ) {
      return pairRows.some(
        (row) => row.catalog?.scope_refresh.effect === "dataset_wide",
      )
        ? "dataset-wide 갱신은 sync_scope를 비워 서버가 범위를 정규화하게 해야 합니다."
        : "현재 catalog capability가 허용하지 않는 sync_scope입니다.";
    }
    return null;
  }
  for (const provider of effectiveProviders) {
    if (!rows.some((row) => row.provider === provider)) {
      return `현재 canonical catalog에 없는 provider입니다: ${provider}`;
    }
  }
  for (const datasetKey of effectiveDatasetKeys) {
    if (!rows.some((row) => row.dataset_key === datasetKey)) {
      return `현재 canonical catalog에 없는 dataset입니다: ${datasetKey}`;
    }
  }
  if (effectiveProviders.length > 0 && effectiveDatasetKeys.length > 0) {
    for (const provider of effectiveProviders) {
      for (const datasetKey of effectiveDatasetKeys) {
        if (catalogPair(rows, provider, datasetKey).length === 0) {
          return `canonical catalog에 없는 exact pair입니다: ${provider}/${datasetKey}`;
        }
      }
    }
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

/** MOIS 계열 선택 시 조건부 경고 — 구 하드코딩 배너(적재 작업 화면) 이전 (설계 §1). */
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

function useRequestCreateDialogController({
  onCreated,
}: {
  onCreated: (kind: ExecutionKind, id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const dialogSessionRef = useRef(0);
  const createPendingRef = useRef(false);
  const submitPendingSessionRef = useRef<number | null>(null);
  const [scopeType, setScopeType] = useState<ScopeType>("provider_dataset");
  // provider_dataset scope
  const [scopeProvider, setScopeProvider] = useState("");
  const [scopeDataset, setScopeDataset] = useState("");
  const [scopeSyncScope, setScopeSyncScope] = useState("");
  // 좌표 계열 scope
  const [lon, setLon] = useState("126.9780");
  const [lat, setLat] = useState("37.5665");
  const [radiusKm, setRadiusKm] = useState("5");
  // bbox scope
  const [minLon, setMinLon] = useState("126.7");
  const [minLat, setMinLat] = useState("37.3");
  const [maxLon, setMaxLon] = useState("127.2");
  const [maxLat, setMaxLat] = useState("37.8");
  // 목록 계열 scope
  const [featureIdsText, setFeatureIdsText] = useState("");
  const [externalSystem, setExternalSystem] = useState("");
  const [targetKeysText, setTargetKeysText] = useState("");
  const [cacheScopeMode, setCacheScopeMode] = useState<
    "center_radius" | "sigungu_by_radius"
  >("center_radius");
  const [cacheRadiusKm, setCacheRadiusKm] = useState("");
  // 공통 필드
  const [providers, setProviders] = useState<string[]>([]);
  const [datasetKeys, setDatasetKeys] = useState("");
  const [runMode, setRunMode] = useState<"queued" | "now">("queued");
  const [priority, setPriority] = useState("50");
  const [dryRun, setDryRun] = useState(true);
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submittingSession, setSubmittingSession] = useState<number | null>(null);
  const [previewInputKey, setPreviewInputKey] = useState<string | null>(null);
  const [createInputKey, setCreateInputKey] = useState<string | null>(null);
  const submittingPrecheck = submittingSession !== null;

  const catalogQuery = usePipelineDatasetsCatalog();
  const catalogRows = useMemo(
    () => canonicalCatalogRows(catalogQuery.data),
    [catalogQuery.data],
  );
  const providerOptions = useMemo(
    () =>
      [...new Set(catalogRows.map((row) => row.provider))]
        .sort()
        .map((provider) => ({ value: provider, label: provider })),
    [catalogRows],
  );
  const providerDatasetOptions = useMemo(() => {
    const selectedProvider = scopeProvider.trim();
    const options = new Set<string>();
    for (const row of catalogRows) {
      if (row.provider === selectedProvider) options.add(row.dataset_key);
    }
    return [...options].sort();
  }, [catalogRows, scopeProvider]);
  const selectedScopeCapability = useMemo(
    () =>
      catalogRows.find(
        (row) =>
          row.provider === scopeProvider.trim() &&
          row.dataset_key === scopeDataset.trim(),
      )?.catalog?.scope_refresh ?? null,
    [catalogRows, scopeDataset, scopeProvider],
  );
  const explicitScopeSupported = Boolean(
    selectedScopeCapability?.effect === "sync_scope" &&
      selectedScopeCapability.supported &&
      selectedScopeCapability.selector !== "none",
  );
  if (
    scopeSyncScope &&
    selectedScopeCapability &&
    !explicitScopeSupported
  ) {
    setScopeSyncScope("");
  }

  const createRequest = useCreateUpdateRequestMutation();
  const previewRequest = usePreviewUpdateRequestMutation();
  const formInputKey = JSON.stringify([
    scopeType,
    scopeProvider,
    scopeDataset,
    scopeSyncScope,
    lon,
    lat,
    radiusKm,
    minLon,
    minLat,
    maxLon,
    maxLat,
    featureIdsText,
    externalSystem,
    targetKeysText,
    cacheScopeMode,
    cacheRadiusKm,
    providers,
    datasetKeys,
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

  const moisSelected = useMemo(() => {
    const candidates = [...providers];
    if (scopeType === "provider_dataset" && scopeProvider.trim()) {
      candidates.push(scopeProvider.trim());
    }
    const selectedDatasets = new Set(
      scopeType === "provider_dataset"
        ? [scopeDataset.trim()]
        : splitList(datasetKeys),
    );
    for (const row of catalogRows) {
      if (selectedDatasets.has(row.dataset_key) && isMoisProvider(row.provider)) {
        candidates.push(row.provider);
      }
    }
    return candidates.find(isMoisProvider) ?? null;
  }, [
    catalogRows,
    datasetKeys,
    providers,
    scopeDataset,
    scopeProvider,
    scopeType,
  ]);
  const moisPrecheck = useMoisSourceSyncPrecheck(moisSelected !== null);

  const buildScope = (): FeatureUpdateScope | string => {
    if (scopeType === "provider_dataset") {
      if (!scopeProvider.trim() || !scopeDataset.trim()) {
        return "provider와 dataset_key를 입력하세요.";
      }
      return {
        type: "provider_dataset",
        provider: scopeProvider.trim(),
        dataset_key: scopeDataset.trim(),
        ...(scopeSyncScope.trim() ? { sync_scope: scopeSyncScope.trim() } : {}),
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
    const scope = buildScope();
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
    const effectiveProviders =
      scopeType === "provider_dataset" ? [] : providers;
    const effectiveDatasetKeys =
      scopeType === "provider_dataset" ? [] : splitList(datasetKeys);
    if (
      scopeType !== "provider_dataset" &&
      effectiveProviders.length === 0 &&
      effectiveDatasetKeys.length === 0
    ) {
      setFormError(
        "provider_dataset 이외 scope는 제공자 또는 데이터셋 필터가 1개 이상 필요합니다.",
      );
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
      const catalogError = validateCatalogSelection(
        scope,
        effectiveProviders,
        effectiveDatasetKeys,
        freshRows,
      );
      if (catalogError) {
        setFormError(catalogError);
        return;
      }

      const selectedMois = selectedMoisProvider(
        freshRows,
        scope,
        effectiveProviders,
        scope.type === "provider_dataset"
          ? [scope.dataset_key]
          : effectiveDatasetKeys,
      );
      if (selectedMois !== null) {
        let precheck: PipelineJobPrecheckResponse;
        try {
          precheck = await getJson<PipelineJobPrecheckResponse>(
            "/v1/ops/pipeline/prechecks/mois-source-sync",
          );
        } catch {
          if (!isCurrentDialogSession()) {
            return;
          }
          setFormError(
            "MOIS 선행 source sync 최신 상태를 조회할 수 없어 요청을 진행할 수 없습니다.",
          );
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

      const plan: FeatureUpdateRequestPreviewRequest = {
        scope,
        providers: effectiveProviders,
        dataset_keys: effectiveDatasetKeys,
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
      const body: FeatureUpdateRequestCreateRequest = {
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
    cacheRadiusKm,
    cacheScopeMode,
    catalogQuery,
    closeDialog,
    conflictRequestId,
    createRequest,
    created,
    datasetKeys,
    dryRun,
    explicitScopeSupported,
    externalSystem,
    featureIdsText,
    formError,
    handleOpenChange,
    lat,
    lon,
    maxLat,
    maxLon,
    minLat,
    minLon,
    moisPrecheck,
    moisSelected,
    onCreated,
    open,
    openDialog,
    preview,
    previewRequest,
    priority,
    providerDatasetOptions,
    providerOptions,
    providers,
    radiusKm,
    reason,
    requestError,
    retryAfterSeconds,
    runMode,
    scopeDataset,
    scopeProvider,
    scopeSyncScope,
    scopeType,
    selectedScopeCapability,
    setCacheRadiusKm,
    setCacheScopeMode,
    setDatasetKeys,
    setDryRun,
    setExternalSystem,
    setFeatureIdsText,
    setFormError,
    setLat,
    setLon,
    setMaxLat,
    setMaxLon,
    setMinLat,
    setMinLon,
    setPriority,
    setProviders,
    setRadiusKm,
    setReason,
    setRunMode,
    setScopeDataset,
    setScopeProvider,
    setScopeSyncScope,
    setScopeType,
    setTargetKeysText,
    submit,
    submittingPrecheck,
    targetKeysText,
  };
}

function RequestIdentityFields({
  explicitScopeSupported,
  featureIdsText,
  lat,
  lon,
  maxLat,
  maxLon,
  minLat,
  minLon,
  providerDatasetOptions,
  providerOptions,
  radiusKm,
  scopeDataset,
  scopeProvider,
  scopeSyncScope,
  scopeType,
  selectedScopeCapability,
  setFeatureIdsText,
  setFormError,
  setLat,
  setLon,
  setMaxLat,
  setMaxLon,
  setMinLat,
  setMinLon,
  setRadiusKm,
  setScopeDataset,
  setScopeProvider,
  setScopeSyncScope,
  setScopeType,
}: Pick<ReturnType<typeof useRequestCreateDialogController>, "explicitScopeSupported" | "featureIdsText" | "lat" | "lon" | "maxLat" | "maxLon" | "minLat" | "minLon" | "providerDatasetOptions" | "providerOptions" | "radiusKm" | "scopeDataset" | "scopeProvider" | "scopeSyncScope" | "scopeType" | "selectedScopeCapability" | "setFeatureIdsText" | "setFormError" | "setLat" | "setLon" | "setMaxLat" | "setMaxLon" | "setMinLat" | "setMinLon" | "setRadiusKm" | "setScopeDataset" | "setScopeProvider" | "setScopeSyncScope" | "setScopeType">) {
  return (
    <>
<FormSelect
              label="scope 유형"
              value={scopeType}
              onChange={(event) => {
                setScopeType(event.target.value as ScopeType);
                setFormError(null);
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
                <FormField
                  list="pipeline-provider-catalog"
                  label="provider"
                  placeholder="예: python-kma-api"
                  required
                  value={scopeProvider}
                  onChange={(event) => {
                    setScopeProvider(event.target.value);
                    setScopeDataset("");
                    setScopeSyncScope("");
                  }}
                />
                <FormField
                  list="pipeline-provider-dataset-catalog"
                  label="dataset_key"
                  placeholder="예: kma_short_forecast"
                  required
                  value={scopeDataset}
                  onChange={(event) => {
                    setScopeDataset(event.target.value);
                    setScopeSyncScope("");
                  }}
                />
                <datalist id="pipeline-provider-catalog">
                  {providerOptions.map((option) => (
                    <option key={option.value} value={option.value} />
                  ))}
                </datalist>
                <datalist id="pipeline-provider-dataset-catalog">
                  {providerDatasetOptions.map((datasetKey) => (
                    <option key={datasetKey} value={datasetKey} />
                  ))}
                </datalist>
                <FormField
                  disabled={
                    selectedScopeCapability !== null && !explicitScopeSupported
                  }
                  hint={
                    selectedScopeCapability?.effect === "dataset_wide"
                      ? "dataset-wide 갱신은 비워 두며 서버가 정규화합니다."
                      : "비우면 서버가 기본 sync scope를 선택합니다."
                  }
                  label="sync_scope (선택)"
                  value={scopeSyncScope}
                  onChange={(event) => setScopeSyncScope(event.target.value)}
                />
              </>
            ) : null}

            {scopeType === "center_radius" ||
            scopeType === "sigungu_by_radius" ? (
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
}

function RequestTargetFields({
  cacheRadiusKm,
  cacheScopeMode,
  catalogQuery,
  datasetKeys,
  dryRun,
  externalSystem,
  priority,
  providerOptions,
  providers,
  reason,
  runMode,
  scopeType,
  setCacheRadiusKm,
  setCacheScopeMode,
  setDatasetKeys,
  setDryRun,
  setExternalSystem,
  setPriority,
  setProviders,
  setReason,
  setRunMode,
  setTargetKeysText,
  targetKeysText,
}: Pick<ReturnType<typeof useRequestCreateDialogController>, "cacheRadiusKm" | "cacheScopeMode" | "catalogQuery" | "datasetKeys" | "dryRun" | "externalSystem" | "priority" | "providerOptions" | "providers" | "reason" | "runMode" | "scopeType" | "setCacheRadiusKm" | "setCacheScopeMode" | "setDatasetKeys" | "setDryRun" | "setExternalSystem" | "setPriority" | "setProviders" | "setReason" | "setRunMode" | "setTargetKeysText" | "targetKeysText">) {
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
                        event.target.value as
                          "center_radius" | "sigungu_by_radius",
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

            {scopeType !== "provider_dataset" ? (
              <>
                <ComboboxMultiple
                  disabled={catalogQuery.isLoading || catalogQuery.isError}
                  emptyMessage="일치하는 제공자가 없습니다."
                  label="제공자 필터"
                  options={providerOptions}
                  placeholder={
                    catalogQuery.isLoading
                      ? "canonical catalog 불러오는 중"
                      : "제공자 선택"
                  }
                  searchPlaceholder="제공자 검색"
                  value={providers}
                  onChange={setProviders}
                />
                <FormField
                  hint="제공자 또는 데이터셋 필터가 1개 이상 필요합니다. 둘 다 지정하면 exact pair 조합으로 검증됩니다."
                  label="데이터셋 키 필터"
                  value={datasetKeys}
                  onChange={(event) => setDatasetKeys(event.target.value)}
                />
              </>
            ) : null}
            <div className="grid grid-cols-2 gap-2">
              <FormSelect
                label="실행 모드"
                value={runMode}
                onChange={(event) =>
                  setRunMode(event.target.value as "queued" | "now")
                }
              >
                <NativeSelectOption value="queued">
                  예약(queued)
                </NativeSelectOption>
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
}

function RequestExecutionFields({
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
}: Pick<ReturnType<typeof useRequestCreateDialogController>, "catalogQuery" | "closeDialog" | "conflictRequestId" | "createRequest" | "created" | "formError" | "moisPrecheck" | "moisSelected" | "onCreated" | "preview" | "requestError" | "retryAfterSeconds">) {
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
                  <p>
                    {preview.providers.length}개 provider ·{" "}
                    {preview.dataset_keys.length}개 dataset
                  </p>
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
                    <span className="font-mono">
                      {shortId(created.request_id)}
                    </span>
                  </p>
                  <p>
                    effective scope:{" "}
                    {created.effective_sync_scope ?? "해당 없음"}
                  </p>
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

function RequestCreateDialogView({
  cacheRadiusKm,
  cacheScopeMode,
  catalogQuery,
  closeDialog,
  conflictRequestId,
  createRequest,
  created,
  datasetKeys,
  dryRun,
  explicitScopeSupported,
  externalSystem,
  featureIdsText,
  formError,
  handleOpenChange,
  lat,
  lon,
  maxLat,
  maxLon,
  minLat,
  minLon,
  moisPrecheck,
  moisSelected,
  onCreated,
  open,
  openDialog,
  preview,
  previewRequest,
  priority,
  providerDatasetOptions,
  providerOptions,
  providers,
  radiusKm,
  reason,
  requestError,
  retryAfterSeconds,
  runMode,
  scopeDataset,
  scopeProvider,
  scopeSyncScope,
  scopeType,
  selectedScopeCapability,
  setCacheRadiusKm,
  setCacheScopeMode,
  setDatasetKeys,
  setDryRun,
  setExternalSystem,
  setFeatureIdsText,
  setFormError,
  setLat,
  setLon,
  setMaxLat,
  setMaxLon,
  setMinLat,
  setMinLon,
  setPriority,
  setProviders,
  setRadiusKm,
  setReason,
  setRunMode,
  setScopeDataset,
  setScopeProvider,
  setScopeSyncScope,
  setScopeType,
  setTargetKeysText,
  submit,
  submittingPrecheck,
  targetKeysText,
}: ReturnType<typeof useRequestCreateDialogController>) {
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
            <RequestIdentityFields explicitScopeSupported={explicitScopeSupported} featureIdsText={featureIdsText} lat={lat} lon={lon} maxLat={maxLat} maxLon={maxLon} minLat={minLat} minLon={minLon} providerDatasetOptions={providerDatasetOptions} providerOptions={providerOptions} radiusKm={radiusKm} scopeDataset={scopeDataset} scopeProvider={scopeProvider} scopeSyncScope={scopeSyncScope} scopeType={scopeType} selectedScopeCapability={selectedScopeCapability} setFeatureIdsText={setFeatureIdsText} setFormError={setFormError} setLat={setLat} setLon={setLon} setMaxLat={setMaxLat} setMaxLon={setMaxLon} setMinLat={setMinLat} setMinLon={setMinLon} setRadiusKm={setRadiusKm} setScopeDataset={setScopeDataset} setScopeProvider={setScopeProvider} setScopeSyncScope={setScopeSyncScope} setScopeType={setScopeType} />

            <RequestTargetFields cacheRadiusKm={cacheRadiusKm} cacheScopeMode={cacheScopeMode} catalogQuery={catalogQuery} datasetKeys={datasetKeys} dryRun={dryRun} externalSystem={externalSystem} priority={priority} providerOptions={providerOptions} providers={providers} reason={reason} runMode={runMode} scopeType={scopeType} setCacheRadiusKm={setCacheRadiusKm} setCacheScopeMode={setCacheScopeMode} setDatasetKeys={setDatasetKeys} setDryRun={setDryRun} setExternalSystem={setExternalSystem} setPriority={setPriority} setProviders={setProviders} setReason={setReason} setRunMode={setRunMode} setTargetKeysText={setTargetKeysText} targetKeysText={targetKeysText} />

            <RequestExecutionFields catalogQuery={catalogQuery} closeDialog={closeDialog} conflictRequestId={conflictRequestId} createRequest={createRequest} created={created} formError={formError} moisPrecheck={moisPrecheck} moisSelected={moisSelected} onCreated={onCreated} preview={preview} requestError={requestError} retryAfterSeconds={retryAfterSeconds} />
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
              {dryRun ? "dry-run 실행" : "요청 생성"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export function RequestCreateDialog({
  onCreated,
}: {
  onCreated: (kind: ExecutionKind, id: string) => void;
}) {
  const controller = useRequestCreateDialogController({ onCreated });
  return <RequestCreateDialogView {...controller} />;
}
