"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";

import {
  type PoiCacheTargetRecord,
  useDeletePoiCacheTargetMutation,
  useNearbyFeaturesByTarget,
  usePoiCacheTargets,
  useUpsertPoiCacheTargetMutation,
} from "@/api/poiCacheTargets";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { FormField, FormSelect } from "@/components/ui/form-field";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { formatDateTime, shortId } from "@/lib/format";
import {
  combine,
  koreaLatitude,
  koreaLongitude,
  numberInRange,
  required,
  validateForm,
} from "@/lib/form-validation";

export function PoiCacheTargetsClient() {
  const [externalSystem, setExternalSystem] = useState("external-app");
  const [targetKey, setTargetKey] = useState("");
  const [name, setName] = useState("");
  const [lon, setLon] = useState("126.9780");
  const [lat, setLat] = useState("37.5665");
  const [radiusKm, setRadiusKm] = useState("5");
  const [scopeMode, setScopeMode] = useState<"center_radius" | "sigungu_by_radius">(
    "center_radius",
  );
  const [selectedTarget, setSelectedTarget] = useState<PoiCacheTargetRecord | null>(
    null,
  );
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
  const upsert = useUpsertPoiCacheTargetMutation();
  const remove = useDeletePoiCacheTargetMutation();
  const nearby = useNearbyFeaturesByTarget(
    selectedTarget
      ? {
          external_system: selectedTarget.external_system,
          target_key: selectedTarget.target_key,
          page_size: 100,
        }
      : null,
  );

  const targetItems = targets.data?.data.items ?? [];
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
              <div className="font-mono text-xs text-muted-foreground">
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
      { accessorKey: "scope_mode", header: "스코프", enableSorting: false },
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
      { accessorKey: "refresh_policy", header: "갱신", enableSorting: false },
      {
        accessorKey: "updated_at",
        header: "수정",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.updated_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        cell: ({ row }) => {
          const target = row.original;
          return (
            <Button
              size="sm"
              type="button"
              variant="ghost"
              onClick={(event) => {
                event.stopPropagation();
                remove.mutate({
                  externalSystem: target.external_system,
                  targetKey: target.target_key,
                });
              }}
            >
              <Trash2Icon data-icon="inline-start" />
              삭제
            </Button>
          );
        },
      },
    ],
    [remove],
  );

  const nearbyColumns = useMemo<ColumnDef<NearbyRow, unknown>[]>(
    () => [
      {
        id: "feature",
        header: "feature",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.name}</div>
            <div className="font-mono text-xs text-muted-foreground">
              {shortId(row.original.feature_id)}
            </div>
          </>
        ),
      },
      // nearby는 서버가 거리순(또는 지정 sort)으로 반환 — client 재정렬을 끈다(#502).
      { accessorKey: "kind", header: "종류", enableSorting: false },
      {
        accessorKey: "distance_m",
        header: "거리",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono">
            {row.original.distance_m.toFixed(1)}m
          </span>
        ),
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

  return (
    <AdminShell
      actions={
        <Button
          disabled={targets.isFetching}
          type="button"
          variant="outline"
          onClick={() => void targets.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="외부 시스템 POI/cache target을 등록하고 target key 기준 주변 feature를 확인합니다."
      section="관리"
      title="POI 캐시 대상"
    >
      <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
        <div className="rounded-lg border bg-background p-4">
          <div className="mb-4">
            <div className="font-medium">Target upsert</div>
          </div>
          <div className="flex flex-col gap-3">
            <FormField
              error={errors.externalSystem}
              label="외부 시스템"
              ref={externalSystemRef}
              required
              value={externalSystem}
              onChange={(event) => setExternalSystem(event.target.value)}
            />
            <FormField
              error={errors.targetKey}
              label="대상 키"
              ref={targetKeyRef}
              required
              value={targetKey}
              onChange={(event) => setTargetKey(event.target.value)}
            />
            <FormField
              label="이름"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <FormField
              error={errors.lon}
              label="경도"
              ref={lonRef}
              required
              value={lon}
              onChange={(e) => setLon(e.target.value)}
            />
            <FormField
              error={errors.lat}
              label="위도"
              ref={latRef}
              required
              value={lat}
              onChange={(e) => setLat(e.target.value)}
            />
            <FormField
              error={errors.radiusKm}
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
                중심점 반경
              </NativeSelectOption>
              <NativeSelectOption value="sigungu_by_radius">
                시군구 반경
              </NativeSelectOption>
            </FormSelect>
            <Button disabled={upsert.isPending} type="button" onClick={submit}>
              저장
            </Button>
            {(targets.isError || upsert.isError || remove.isError) && (
              <Alert variant="destructive">
                <AlertTitle>target 처리 실패</AlertTitle>
                <AlertDescription>
                  {targets.error?.message ??
                    upsert.error?.message ??
                    remove.error?.message}
                </AlertDescription>
              </Alert>
            )}
          </div>
        </div>

        <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_minmax(28rem,0.8fr)]">
          <div className="rounded-lg border bg-background">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
              <div>
                <div className="font-medium">Targets</div>
                <div className="text-sm text-muted-foreground">
                  page {cursorStack.length + 1} ·{" "}
                  {targets.data?.data.items.length ?? 0} rows
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  disabled={cursorStack.length === 0 || targets.isFetching}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={goToPreviousPage}
                >
                  <ChevronLeftIcon data-icon="inline-start" />
                  이전
                </Button>
                <Button
                  disabled={!targets.data?.meta.page?.next_cursor || targets.isFetching}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={goToNextPage}
                >
                  다음
                  <ChevronRightIcon data-icon="inline-end" />
                </Button>
              </div>
            </div>
            <DataTable
              columns={targetColumns}
              data={targetItems}
              getRowId={(row) => row.target_id}
              isLoading={targets.isLoading}
              emptyMessage="데이터가 없습니다."
              onRowClick={(target) => setSelectedTarget(target)}
              isRowActive={(target) =>
                target.target_id === selectedTarget?.target_id
              }
              containerClassName="overflow-auto"
            />
          </div>

          <div className="rounded-lg border bg-background">
            <div className="border-b px-4 py-3">
              <div className="font-medium">Nearby features</div>
              <div className="text-sm text-muted-foreground">
                {selectedTarget
                  ? `${selectedTarget.external_system}/${selectedTarget.target_key}`
                  : "target을 선택하세요"}
              </div>
            </div>
            {nearby.isError ? (
              <Alert className="m-4" variant="destructive">
                <AlertTitle>주변 feature 조회 실패</AlertTitle>
                <AlertDescription>{nearby.error.message}</AlertDescription>
              </Alert>
            ) : null}
            <DataTable
              columns={nearbyColumns}
              data={nearbyItems}
              getRowId={(row) => row.feature_id}
              isLoading={nearby.isLoading}
              emptyMessage="데이터가 없습니다."
              containerClassName="max-h-[34rem] overflow-auto"
            />
          </div>
        </div>
      </div>
    </AdminShell>
  );
}
