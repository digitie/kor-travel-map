"use client";

import { useQuery } from "@tanstack/react-query";
import { DagsterOperations } from "@kor-travel/ui/dagster-operations";
import type { DagsterSnapshot } from "@kor-travel/ui/dagster-model";

import { getJson } from "@/api/client";
import type { components } from "@/api/types";

type Summary = components["schemas"]["DagsterSummaryResponse"];

export function toDagsterSnapshot(data: Summary["data"]): DagsterSnapshot {
  return {
    checkedAt: data.checked_at,
    repositories: data.repositories.map(repository => ({
      name: repository.name, locationName: repository.location_name,
      jobs: repository.jobs.map(job => job.name),
      assets: repository.asset_groups.flatMap(group => group.assets), assetCount: repository.asset_count,
      schedules: repository.schedules.map(schedule => ({
        name: schedule.name, status: schedule.status ?? null, cron: schedule.effective_cron_schedule,
        jobName: schedule.pipeline_name ?? null, timezone: schedule.execution_timezone,
        lastTick: schedule.recent_ticks?.[0] ? {
          status: schedule.recent_ticks?.[0].status, timestamp: schedule.recent_ticks?.[0].timestamp,
        } : null,
      })),
      sensors: repository.sensors.map(sensor => ({ name: sensor.name, status: sensor.status ?? null,
        lastTick: sensor.recent_ticks?.[0] ? {
          status: sensor.recent_ticks?.[0].status, timestamp: sensor.recent_ticks?.[0].timestamp,
        } : null,
      })),
    })),
    runs: data.recent_runs.map(run => {
      const cap = Number(run.tags["dagster/max_runtime"]);
      return { runId: run.run_id, status: run.status, jobName: run.job_name ?? "작업 미확인",
        startTime: run.start_time ?? null, endTime: run.end_time ?? null, errorMessage: null,
        maxRuntimeSeconds: Number.isFinite(cap) && cap > 0 ? cap : null };
    }),
  };
}

export function CommonDagsterPanel() {
  const query = useQuery({
    queryKey: ["pipeline", "common-dagster-summary"],
    queryFn: async ({ signal }) => {
      const response = await getJson<Summary>("/v1/ops/pipeline/dagster-summary", { signal });
      // HTTP 200 degraded 응답도 실패로 취급해 마지막 정상 snapshot을 보존한다.
      if (response.data.status !== "ok") throw new Error("Dagster 상태를 확인하지 못했습니다. 마지막 정상 조회를 표시합니다.");
      return response;
    },
    refetchInterval: 30_000, staleTime: 5_000, gcTime: 60_000, retry: 1,
  });
  const data = query.data?.data;
  const base = data?.dagster_url.replace(/\/$/, "") ?? "";
  return <section className="map-common-surface min-w-0" aria-label="Dagster 운영 상태" data-testid="pipeline-dagster-runs-panel">
    <DagsterOperations snapshot={data ? toDagsterSnapshot(data) : null}
      error={query.isError ? "Dagster 연결을 확인하지 못했습니다. 마지막 정상 조회를 표시합니다." : undefined}
      loading={query.isFetching} onRefresh={() => { void query.refetch(); }}
      runUrl={id => `${base}/runs/${encodeURIComponent(id)}`}
      scheduleUrl={(name, repository) => `${base}/locations/${encodeURIComponent(`${repository.name}@${repository.locationName}`)}/schedules/${encodeURIComponent(name)}`}
      locationUrl={data?.repositories[0] ? `${base}/locations/${encodeURIComponent(`${data.repositories[0].name}@${data.repositories[0].location_name}`)}` : undefined}
      testId="map-common-dagster" />
  </section>;
}
