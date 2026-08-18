"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import { RefreshCwIcon, Trash2Icon } from "lucide-react";
import { useMemo, useRef, useState, type FormEvent } from "react";

import {
  useDeletePoiCacheTargetMutation,
  useNearbyFeaturesByTarget,
  usePoiCacheTargets,
  useUpsertPoiCacheTargetMutation,
} from "@/api/poiCacheTargets";
import { AdminShell } from "@/components/admin-shell";
import { useConfirm } from "@/components/confirm-dialog";
import { EntityLink } from "@/components/entity-link";
import { SectionCard } from "@/components/section-card";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
import { FormField, FormSelect } from "@/components/ui/form-field";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import {
  combine,
  koreaLatitude,
  koreaLongitude,
  numberInRange,
  required,
  validateForm,
} from "@/lib/form-validation";

// enum → 한글 라벨(design.md §Copy — enum 값을 raw로 렌더하지 않는다). 값 정본은 API 스키마.
const SCOPE_MODE_LABELS: Record<string, string> = {
  center_radius: "중심점 반경",
  sigungu_by_radius: "시군구 반경",
};
const REFRESH_POLICY_LABELS: Record<string, string> = {
  provider_default: "provider 기본",
  follow_system: "시스템 추종",
  allow_targeted: "대상 갱신 허용",
  disabled: "비활성화",
};
const FEATURE_KIND_LABELS: Record<string, string> = {
  place: "장소",
  event: "행사",
  notice: "공지",
  price: "가격",
  weather: "날씨",
  route: "경로",
  area: "구역",
};

function usePoiCacheTargetsClientController() {
  const [externalSystem, setExternalSystem] = useState("external-app");
  const [targetKey, setTargetKey] = useState("");
  const [name, setName] = useState("");
  const [lon, setLon] = useState("126.9780");
  const [lat, setLat] = useState("37.5665");
  const [radiusKm, setRadiusKm] = useState("5");
  const [scopeMode, setScopeMode] = useState<"center_radius" | "sigungu_by_radius">(
    "center_radius",
  );
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const [errors, setErrors] = useState<
    Partial<Record<"externalSystem" | "targetKey" | "lon" | "lat" | "radiusKm", string>>
  >({});
  const externalSystemRef = useRef<HTMLInputElement>(null);
  const targetKeyRef = useRef<HTMLInputElement>(null);
  const lonRef = useRef<HTMLInputElement>(null);
  const latRef = useRef<HTMLInputElement>(null);
  const radiusKmRef = useRef<HTMLInputElement>(null);
  const currentCursor =
    cursorStack.length > 0 ? cursorStack[cursorStack.length - 1] : undefined;

  const targets = usePoiCacheTargets({ page_size: 100, cursor: currentCursor });
  const targetItems = targets.data?.data.items ?? [];
  const selectedTarget =
    targetItems.find((target) => target.target_id === selectedTargetId) ?? null;
  const upsert = useUpsertPoiCacheTargetMutation();
  const remove = useDeletePoiCacheTargetMutation();
  const confirm = useConfirm();
  const nearby = useNearbyFeaturesByTarget(
    selectedTarget
      ? {
          external_system: selectedTarget.external_system,
          target_key: selectedTarget.target_key,
          page_size: 100,
        }
      : null,
  );

  const nearbyItems = nearby.data?.data.items ?? [];
  type TargetRow = NonNullable<
    typeof targets.data
  >["data"]["items"][number];
  type NearbyRow = NonNullable<typeof nearby.data>["data"]["items"][number];

  const targetColumns = useMemo<ColumnDef<TargetRow, unknown>[]>(
    () => [
      {
        id: "target",
        header: "대상",
        enableSorting: false,
        cell: ({ row }) => {
          const target = row.original;
          return (
            <>
              <div className="font-medium">
                {target.name ?? target.target_key}
              </div>
              <div className="font-mono text-xs text-text-secondary">
                {target.external_system}/{shortId(target.target_key, 18)}
              </div>
            </>
          );
        },
      },
      {
        id: "coord",
        header: "좌표",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.coord.lon.toFixed(5)},{" "}
            {row.original.coord.lat.toFixed(5)}
          </span>
        ),
      },
      // keyset cursor 목록(next_cursor 페이징) — 서버가 정렬을 소유하므로 컬럼 정렬을
      // 끈다(#502: manual 기본에서 client 정렬은 현재 페이지만 재배열해 오해를 줌).
      {
        accessorKey: "scope_mode",
        header: "스코프",
        enableSorting: false,
        cell: ({ row }) =>
          SCOPE_MODE_LABELS[row.original.scope_mode] ?? row.original.scope_mode,
      },
      {
        accessorKey: "update_enabled",
        header: "사용",
        enableSorting: false,
        cell: ({ row }) => (
          <StatusBadge
            status={row.original.update_enabled ? "active" : "disabled"}
          />
        ),
      },
      {
        accessorKey: "refresh_policy",
        header: "갱신",
        enableSorting: false,
        cell: ({ row }) =>
          REFRESH_POLICY_LABELS[row.original.refresh_policy] ??
          row.original.refresh_policy,
      },
      {
        accessorKey: "updated_at",
        header: "수정",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.updated_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => {
          const target = row.original;
          const removing =
            remove.isPending && remove.variables?.targetKey === target.target_key;
          return (
            <Button
              disabled={remove.isPending || targets.isFetching}
              disabledReason={
                remove.isPending ? "다른 대상을 삭제하는 중입니다" : "목록을 불러오는 중입니다"
              }
              loading={removing}
              size="sm"
              type="button"
              variant="destructive"
              onClick={(event) => {
                event.stopPropagation();
                void (async () => {
                  const ok = await confirm({
                    title: `'${target.target_key}' 대상을 삭제할까요?`,
                    description:
                      "등록된 POI 캐시 대상이 제거되며 이후 갱신 대상에서 빠집니다.",
                    confirmLabel: "삭제",
                    destructive: true,
                  });
                  if (!ok) return;
                  remove.mutate(
                    {
                      externalSystem: target.external_system,
                      targetKey: target.target_key,
                      entityTag: target.entity_tag,
                    },
                    {
                      onSuccess: () => {
                        setSelectedTargetId((selectedId) =>
                          selectedId === target.target_id ? null : selectedId,
                        );
                      },
                    },
                  );
                })();
              }}
            >
              <Trash2Icon data-icon="inline-start" />
              삭제
            </Button>
          );
        },
      },
    ],
    [confirm, remove, targets.isFetching],
  );

  const nearbyColumns = useMemo<ColumnDef<NearbyRow, unknown>[]>(
    () => [
      {
        id: "feature",
        header: "feature",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.name}</div>
            <EntityLink
              className="text-xs"
              id={row.original.feature_id}
              kind="feature"
            >
              {shortId(row.original.feature_id)}
            </EntityLink>
          </>
        ),
      },
      // nearby는 서버가 거리순(또는 지정 sort)으로 반환 — client 재정렬을 끈다(#502).
      {
        accessorKey: "kind",
        header: "종류",
        enableSorting: false,
        cell: ({ row }) => FEATURE_KIND_LABELS[row.original.kind] ?? row.original.kind,
      },
      {
        accessorKey: "distance_m",
        header: "거리",
        enableSorting: false,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => `${row.original.distance_m.toFixed(1)} m`,
      },
    ],
    [],
  );

  const submit = () => {
    const values = { externalSystem, targetKey, lon, lat, radiusKm };
    const result = validateForm(values, [
      { field: "externalSystem", validate: required("외부 시스템을 입력하세요.") },
      { field: "targetKey", validate: required("대상 키를 입력하세요.") },
      {
        field: "lon",
        validate: combine(
          required("경도를 입력하세요."),
          koreaLongitude(),
        ),
      },
      {
        field: "lat",
        validate: combine(
          required("위도를 입력하세요."),
          koreaLatitude(),
        ),
      },
      {
        field: "radiusKm",
        validate: combine(
          required("반경을 입력하세요."),
          numberInRange({ min: 0.1, message: "반경은 0.1 이상이어야 합니다." }),
        ),
      },
    ]);
    setErrors(result.errors);
    if (!result.isValid) {
      const refByField = {
        externalSystem: externalSystemRef,
        targetKey: targetKeyRef,
        lon: lonRef,
        lat: latRef,
        radiusKm: radiusKmRef,
      };
      if (result.firstErrorField) {
        refByField[result.firstErrorField].current?.focus();
      }
      return;
    }
    upsert.mutate(
      {
        externalSystem: externalSystem.trim(),
        targetKey: targetKey.trim(),
        body: {
          coord: { lon: Number(lon), lat: Number(lat) },
          name: name.trim() || null,
          radius_km: Number(radiusKm),
          scope_mode: scopeMode,
          on_conflict: "move",
        },
      },
      {
        onSuccess: () => setCursorStack([]),
      },
    );
  };

  const goToNextPage = () => {
    const nextCursor = targets.data?.meta.page?.next_cursor;
    if (nextCursor) {
      setCursorStack((value) => [...value, nextCursor]);
    }
  };

  const goToPreviousPage = () => {
    setCursorStack((value) => value.slice(0, -1));
  };

  return {
    cursorStack,
    errors,
    externalSystem,
    externalSystemRef,
    goToNextPage,
    goToPreviousPage,
    lat,
    latRef,
    lon,
    lonRef,
    name,
    nearby,
    nearbyColumns,
    nearbyItems,
    radiusKm,
    radiusKmRef,
    remove,
    scopeMode,
    selectedTarget,
    selectedTargetId,
    setExternalSystem,
    setLat,
    setLon,
    setName,
    setRadiusKm,
    setScopeMode,
    setSelectedTargetId,
    setTargetKey,
    submit,
    targetColumns,
    targetItems,
    targetKey,
    targetKeyRef,
    targets,
    upsert,
  };
}

/**
 * keyset cursor 스택 pager(이전으로 돌아갈 수 있는 목록) — 공용 CursorPager는 `첫 페이지/다음`만
 * 제공하므로, 같은 PagerShell 형태(flat 행 · 요약 · sm outline 버튼)로 `이전/다음`을 렌더한다.
 */
function TargetsPager({
  page,
  rowCount,
  hasPrevious,
  hasNext,
  isFetching,
  onPrevious,
  onNext,
}: {
  page: number;
  rowCount: number | null;
  hasPrevious: boolean;
  hasNext: boolean;
  isFetching: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <nav
      aria-busy={isFetching || undefined}
      aria-label="targets pagination"
      className="flex flex-col gap-2 py-1 sm:flex-row sm:items-center sm:justify-between"
      data-slot="pager"
    >
      <span className="text-xs text-text-secondary tabular-nums">
        page {page} · {formatCount(rowCount)} rows
      </span>
      <div className="flex flex-wrap items-center gap-1">
        <Button
          disabled={!hasPrevious || isFetching}
          size="sm"
          type="button"
          variant="outline"
          onClick={onPrevious}
        >
          이전
        </Button>
        <Button
          disabled={!hasNext || isFetching}
          size="sm"
          type="button"
          variant="outline"
          onClick={onNext}
        >
          다음
        </Button>
      </div>
    </nav>
  );
}

function PoiCacheTargetsClientView({
  cursorStack,
  errors,
  externalSystem,
  externalSystemRef,
  goToNextPage,
  goToPreviousPage,
  lat,
  latRef,
  lon,
  lonRef,
  name,
  nearby,
  nearbyColumns,
  nearbyItems,
  radiusKm,
  radiusKmRef,
  remove,
  scopeMode,
  selectedTarget,
  selectedTargetId,
  setExternalSystem,
  setLat,
  setLon,
  setName,
  setRadiusKm,
  setScopeMode,
  setSelectedTargetId,
  setTargetKey,
  submit,
  targetColumns,
  targetItems,
  targetKey,
  targetKeyRef,
  targets,
  upsert,
}: ReturnType<typeof usePoiCacheTargetsClientController>) {
  const errorLines = [
    targets.error ? `목록: ${targets.error.message}` : null,
    upsert.error ? `저장: ${upsert.error.message}` : null,
    remove.error ? `삭제: ${remove.error.message}` : null,
  ].filter((line): line is string => line !== null);
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submit();
  };
  return (
    <AdminShell
      actions={
        <Button
          loading={targets.isFetching}
          type="button"
          variant="outline"
          onClick={() => void targets.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="외부 시스템 POI/cache target을 등록하고 target key 기준 주변 feature를 확인합니다."
      title="POI 캐시 대상"
    >
      <div className="flex flex-col gap-6">
        {errorLines.length > 0 ? (
          <Alert variant="destructive">
            <AlertTitle>target 처리 실패</AlertTitle>
            <AlertDescription>
              {errorLines.map((line) => (
                <p key={line}>{line}</p>
              ))}
              <p>입력값을 확인하고 다시 시도하세요.</p>
            </AlertDescription>
            {targets.error ? (
              <AlertActions>
                <Button
                  loading={targets.isFetching}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => void targets.refetch()}
                >
                  다시 시도
                </Button>
              </AlertActions>
            ) : null}
          </Alert>
        ) : null}

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
          <SectionCard
            description="행을 선택하면 우측에 주변 feature가 열립니다."
            title="Targets"
          >
            <DataTable
              columns={targetColumns}
              containerClassName="overflow-auto"
              data={targetItems}
              emptyState={{
                title: "데이터가 없습니다.",
                description: "우측 폼에서 대상을 저장하면 목록에 나타납니다.",
              }}
              getRowId={(row) => row.target_id}
              isLoading={targets.isLoading}
              isRowActive={(target) => target.target_id === selectedTargetId}
              onRowClick={(target) => setSelectedTargetId(target.target_id)}
            />
            <TargetsPager
              hasNext={Boolean(targets.data?.meta.page?.next_cursor)}
              hasPrevious={cursorStack.length > 0}
              isFetching={targets.isFetching}
              page={cursorStack.length + 1}
              rowCount={targets.data ? targets.data.data.items.length : null}
              onNext={goToNextPage}
              onPrevious={goToPreviousPage}
            />
          </SectionCard>

          <div className="flex flex-col gap-6">
            <SectionCard
              description="같은 외부 시스템·대상 키가 있으면 위치를 옮겨 갱신합니다."
              headingLevel={2}
              title="Target upsert"
            >
              <form className="flex flex-col gap-1" onSubmit={onSubmit}>
                <FormField
                  error={errors.externalSystem}
                  hint="예: external-app"
                  label="외부 시스템"
                  ref={externalSystemRef}
                  required
                  value={externalSystem}
                  onChange={(event) => setExternalSystem(event.target.value)}
                />
                <FormField
                  error={errors.targetKey}
                  hint="외부 시스템 안에서 고유한 키"
                  label="대상 키"
                  ref={targetKeyRef}
                  required
                  value={targetKey}
                  onChange={(event) => setTargetKey(event.target.value)}
                />
                <FormField
                  hint="비워 두면 대상 키를 이름으로 씁니다."
                  label="이름"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
                <div className="grid grid-cols-2 gap-x-3">
                  <FormField
                    error={errors.lon}
                    inputMode="decimal"
                    label="경도"
                    ref={lonRef}
                    required
                    value={lon}
                    onChange={(e) => setLon(e.target.value)}
                  />
                  <FormField
                    error={errors.lat}
                    inputMode="decimal"
                    label="위도"
                    ref={latRef}
                    required
                    value={lat}
                    onChange={(e) => setLat(e.target.value)}
                  />
                </div>
                <FormField
                  error={errors.radiusKm}
                  hint="0.1 이상"
                  inputMode="decimal"
                  label="반경(km)"
                  ref={radiusKmRef}
                  required
                  value={radiusKm}
                  onChange={(e) => setRadiusKm(e.target.value)}
                />
                <FormSelect
                  label="대상 범위"
                  value={scopeMode}
                  onChange={(event) =>
                    setScopeMode(event.target.value as "center_radius" | "sigungu_by_radius")
                  }
                >
                  <NativeSelectOption value="center_radius">
                    {SCOPE_MODE_LABELS.center_radius}
                  </NativeSelectOption>
                  <NativeSelectOption value="sigungu_by_radius">
                    {SCOPE_MODE_LABELS.sigungu_by_radius}
                  </NativeSelectOption>
                </FormSelect>
                <div className="flex items-center justify-end border-t border-border pt-4">
                  <Button loading={upsert.isPending} type="submit">
                    저장
                  </Button>
                </div>
              </form>
            </SectionCard>

            <SectionCard
              description={
                selectedTarget ? (
                  <span className="font-mono">
                    {selectedTarget.external_system}/{selectedTarget.target_key}
                  </span>
                ) : (
                  "target을 선택하세요"
                )
              }
              headingLevel={2}
              title="Nearby features"
            >
              {nearby.isError ? (
                <Alert variant="destructive">
                  <AlertTitle>주변 feature 조회 실패</AlertTitle>
                  <AlertDescription>{nearby.error.message}</AlertDescription>
                  <AlertActions>
                    <Button
                      loading={nearby.isFetching}
                      size="sm"
                      type="button"
                      variant="outline"
                      onClick={() => void nearby.refetch()}
                    >
                      다시 시도
                    </Button>
                  </AlertActions>
                </Alert>
              ) : null}
              <DataTable
                columns={nearbyColumns}
                containerClassName="max-h-[34rem] overflow-auto"
                data={nearbyItems}
                emptyState={{
                  title: "데이터가 없습니다.",
                  description: selectedTarget
                    ? "이 대상의 반경 안에 feature가 없습니다."
                    : "목록에서 대상을 선택하면 주변 feature를 조회합니다.",
                }}
                getRowId={(row) => row.feature_id}
                isLoading={nearby.isLoading}
              />
            </SectionCard>
          </div>
        </div>
      </div>
    </AdminShell>
  );
}

export function PoiCacheTargetsClient() {
  const controller = usePoiCacheTargetsClientController();
  return <PoiCacheTargetsClientView {...controller} />;
}
