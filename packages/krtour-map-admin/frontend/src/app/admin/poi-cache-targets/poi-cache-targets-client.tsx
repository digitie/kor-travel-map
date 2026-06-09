"use client";

import {
  ChevronLeftIcon,
  ChevronRightIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react";
import { useState } from "react";

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
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, shortId } from "@/lib/format";

export function PoiCacheTargetsClient() {
  const [externalSystem, setExternalSystem] = useState("tripmate");
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

  const submit = () => {
    const normalizedExternalSystem = externalSystem.trim();
    const normalizedTargetKey = targetKey.trim();
    upsert.mutate(
      {
        externalSystem: normalizedExternalSystem,
        targetKey: normalizedTargetKey,
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
      section="Admin"
      title="POI cache targets"
    >
      <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
        <div className="rounded-lg border bg-background p-4">
          <div className="mb-4">
            <div className="font-medium">Target upsert</div>
            <div className="text-sm text-muted-foreground">
              external_system + target_key
            </div>
          </div>
          <div className="flex flex-col gap-3">
            <Input
              aria-label="external system"
              value={externalSystem}
              onChange={(event) => setExternalSystem(event.target.value)}
            />
            <Input
              aria-label="target key"
              placeholder="target_key"
              value={targetKey}
              onChange={(event) => setTargetKey(event.target.value)}
            />
            <Input
              aria-label="target name"
              placeholder="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <Input aria-label="lon" value={lon} onChange={(e) => setLon(e.target.value)} />
            <Input aria-label="lat" value={lat} onChange={(e) => setLat(e.target.value)} />
            <Input
              aria-label="radius km"
              value={radiusKm}
              onChange={(e) => setRadiusKm(e.target.value)}
            />
            <NativeSelect
              aria-label="scope mode"
              value={scopeMode}
              onChange={(event) =>
                setScopeMode(event.target.value as "center_radius" | "sigungu_by_radius")
              }
            >
              <NativeSelectOption value="center_radius">
                center_radius
              </NativeSelectOption>
              <NativeSelectOption value="sigungu_by_radius">
                sigungu_by_radius
              </NativeSelectOption>
            </NativeSelect>
            <Button
              disabled={
                upsert.isPending ||
                externalSystem.trim().length === 0 ||
                targetKey.trim().length === 0
              }
              type="button"
              onClick={submit}
            >
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
            {targets.isLoading ? <Skeleton className="m-4 h-96" /> : null}
            <div className="overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>target</TableHead>
                    <TableHead>coord</TableHead>
                    <TableHead>scope</TableHead>
                    <TableHead>enabled</TableHead>
                    <TableHead>refresh</TableHead>
                    <TableHead>updated</TableHead>
                    <TableHead>actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(targets.data?.data.items ?? []).map((target) => (
                    <TableRow
                      className="cursor-pointer"
                      key={target.target_id}
                      onClick={() => setSelectedTarget(target)}
                    >
                      <TableCell>
                        <div className="font-medium">
                          {target.name ?? target.target_key}
                        </div>
                        <div className="font-mono text-xs text-muted-foreground">
                          {target.external_system}/{shortId(target.target_key, 18)}
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {target.coord.lon.toFixed(5)}, {target.coord.lat.toFixed(5)}
                      </TableCell>
                      <TableCell>{target.scope_mode}</TableCell>
                      <TableCell>
                        <StatusBadge
                          status={target.update_enabled ? "active" : "disabled"}
                        />
                      </TableCell>
                      <TableCell>{target.refresh_policy}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(target.updated_at)}
                      </TableCell>
                      <TableCell>
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
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
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
            {nearby.isLoading ? <Skeleton className="m-4 h-72" /> : null}
            {nearby.isError ? (
              <Alert className="m-4" variant="destructive">
                <AlertTitle>주변 feature 조회 실패</AlertTitle>
                <AlertDescription>{nearby.error.message}</AlertDescription>
              </Alert>
            ) : null}
            <div className="max-h-[34rem] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>feature</TableHead>
                    <TableHead>kind</TableHead>
                    <TableHead>distance</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(nearby.data?.data.items ?? []).map((feature) => (
                    <TableRow key={feature.feature_id}>
                      <TableCell>
                        <div className="font-medium">{feature.name}</div>
                        <div className="font-mono text-xs text-muted-foreground">
                          {shortId(feature.feature_id)}
                        </div>
                      </TableCell>
                      <TableCell>{feature.kind}</TableCell>
                      <TableCell className="font-mono">
                        {feature.distance_m.toFixed(1)}m
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </div>
      </div>
    </AdminShell>
  );
}
