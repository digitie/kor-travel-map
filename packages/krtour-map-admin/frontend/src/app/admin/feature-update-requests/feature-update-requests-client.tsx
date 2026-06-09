"use client";

import { PlayIcon, RefreshCwIcon, XIcon } from "lucide-react";
import { useState } from "react";

import {
  type FeatureUpdateStatus,
  useCancelFeatureUpdateRequestMutation,
  useCreateFeatureUpdateRequestMutation,
  useFeatureUpdateRequests,
  useRunFeatureUpdateRequestNowMutation,
} from "@/api/updateRequests";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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

const statuses: Array<FeatureUpdateStatus | "all"> = [
  "queued",
  "running",
  "done",
  "failed",
  "cancelled",
  "all",
];

function commaSeparatedValues(value: string): string[] {
  return value.split(",").flatMap((item) => {
    const trimmed = item.trim();
    return trimmed ? [trimmed] : [];
  });
}

export function FeatureUpdateRequestsClient() {
  const [status, setStatus] = useState<FeatureUpdateStatus | "all">("queued");
  const [lon, setLon] = useState("126.9780");
  const [lat, setLat] = useState("37.5665");
  const [radiusKm, setRadiusKm] = useState("5");
  const [providers, setProviders] = useState("");
  const [datasets, setDatasets] = useState("");
  const [dryRun, setDryRun] = useState(true);
  const [runMode, setRunMode] = useState<"queued" | "now">("queued");

  const requests = useFeatureUpdateRequests({
    status: status === "all" ? undefined : status,
    page_size: 100,
  });
  const createRequest = useCreateFeatureUpdateRequestMutation();
  const cancelRequest = useCancelFeatureUpdateRequestMutation();
  const runNow = useRunFeatureUpdateRequestNowMutation();

  const submit = () => {
    createRequest.mutate({
      scope: {
        type: "center_radius",
        center: {
          lon: Number(lon),
          lat: Number(lat),
        },
        radius_km: Number(radiusKm),
      },
      providers: commaSeparatedValues(providers),
      dataset_keys: commaSeparatedValues(datasets),
      dry_run: dryRun,
      run_mode: runMode,
      operator: "local-admin",
      reason: dryRun ? "admin ui dry-run" : "admin ui request",
    });
  };

  return (
    <AdminShell
      actions={
        <Button
          disabled={requests.isFetching}
          type="button"
          variant="outline"
          onClick={() => void requests.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="좌표/반경/provider 기준 targeted feature update request를 생성하고 상태를 추적합니다."
      section="Admin"
      title="Feature update requests"
    >
      <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
        <div className="rounded-lg border bg-background p-4">
          <div className="mb-4">
            <div className="font-medium">새 요청</div>
            <div className="text-sm text-muted-foreground">
              center_radius scope payload
            </div>
          </div>
          <div className="flex flex-col gap-3">
            <Input aria-label="lon" value={lon} onChange={(e) => setLon(e.target.value)} />
            <Input aria-label="lat" value={lat} onChange={(e) => setLat(e.target.value)} />
            <Input
              aria-label="radius km"
              value={radiusKm}
              onChange={(e) => setRadiusKm(e.target.value)}
            />
            <Input
              aria-label="providers"
              placeholder="providers comma separated"
              value={providers}
              onChange={(e) => setProviders(e.target.value)}
            />
            <Input
              aria-label="dataset keys"
              placeholder="dataset_keys comma separated"
              value={datasets}
              onChange={(e) => setDatasets(e.target.value)}
            />
            <NativeSelect
              aria-label="run mode"
              value={runMode}
              onChange={(event) => setRunMode(event.target.value as "queued" | "now")}
            >
              <NativeSelectOption value="queued">queued</NativeSelectOption>
              <NativeSelectOption value="now">now</NativeSelectOption>
            </NativeSelect>
            <label className="flex items-center gap-2 text-sm">
              <input
                checked={dryRun}
                type="checkbox"
                onChange={(event) => setDryRun(event.target.checked)}
              />
              dry-run
            </label>
            <Button
              disabled={createRequest.isPending}
              type="button"
              onClick={submit}
            >
              <PlayIcon data-icon="inline-start" />
              요청 생성
            </Button>
            {createRequest.data ? (
              <Alert>
                <AlertTitle>요청 처리 완료</AlertTitle>
                <AlertDescription>
                  {createRequest.data.data.request_id ?? "dry-run"} ·{" "}
                  {createRequest.data.data.status}
                </AlertDescription>
              </Alert>
            ) : null}
            {createRequest.isError ? (
              <Alert variant="destructive">
                <AlertTitle>요청 생성 실패</AlertTitle>
                <AlertDescription>{createRequest.error.message}</AlertDescription>
              </Alert>
            ) : null}
          </div>
        </div>

        <div className="flex flex-col gap-4">
          {(requests.isError || cancelRequest.isError || runNow.isError) && (
            <Alert variant="destructive">
              <AlertTitle>request 처리 실패</AlertTitle>
              <AlertDescription>
                {requests.error?.message ??
                  cancelRequest.error?.message ??
                  runNow.error?.message}
              </AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect
              aria-label="request status"
              value={status}
              onChange={(event) =>
                setStatus(event.target.value as FeatureUpdateStatus | "all")
              }
            >
              {statuses.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Badge variant="outline">
              {requests.data?.data.items.length ?? 0} rows
            </Badge>
          </div>
          {requests.isLoading ? <Skeleton className="h-96" /> : null}
          <div className="overflow-auto rounded-lg border bg-background">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>request</TableHead>
                  <TableHead>scope</TableHead>
                  <TableHead>status</TableHead>
                  <TableHead>mode</TableHead>
                  <TableHead>providers</TableHead>
                  <TableHead>job</TableHead>
                  <TableHead>created</TableHead>
                  <TableHead>actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(requests.data?.data.items ?? []).map((request) => (
                  <TableRow key={request.request_id ?? JSON.stringify(request.scope)}>
                    <TableCell className="font-mono text-xs">
                      {shortId(request.request_id)}
                    </TableCell>
                    <TableCell>{request.scope_type}</TableCell>
                    <TableCell>
                      <StatusBadge status={request.status} />
                    </TableCell>
                    <TableCell>{request.run_mode}</TableCell>
                    <TableCell className="max-w-56 truncate">
                      {request.providers.join(", ") || "-"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {shortId(request.job_id)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(request.created_at)}
                    </TableCell>
                    <TableCell>
                      {request.request_id ? (
                        <div className="flex flex-wrap gap-1">
                          {["queued", "running"].includes(request.status) ? (
                            <Button
                              disabled={cancelRequest.isPending}
                              size="sm"
                              type="button"
                              variant="outline"
                              onClick={() =>
                                cancelRequest.mutate({
                                  requestId: request.request_id as string,
                                  body: { error_message: "cancelled from admin ui" },
                                })
                              }
                            >
                              <XIcon data-icon="inline-start" />
                              cancel
                            </Button>
                          ) : null}
                          {request.status !== "running" ? (
                            <Button
                              disabled={runNow.isPending}
                              size="sm"
                              type="button"
                              variant="ghost"
                              onClick={() =>
                                runNow.mutate({
                                  requestId: request.request_id as string,
                                  body: { reason: "run-now from admin ui" },
                                })
                              }
                            >
                              run-now
                            </Button>
                          ) : null}
                        </div>
                      ) : (
                        <span className="text-sm text-muted-foreground">dry-run</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
    </AdminShell>
  );
}
