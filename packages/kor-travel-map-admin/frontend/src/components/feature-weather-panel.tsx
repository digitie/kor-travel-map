"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { CloudSunIcon } from "lucide-react";
import { useMemo } from "react";

import {
  useAdminFeatureWeather,
  type WeatherMetric,
} from "@/api/features";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { formatDateTime } from "@/lib/format";

function weatherMetricIdentity(metric: WeatherMetric): string {
  return JSON.stringify([
    metric.provider_dataset_id,
    metric.dataset_key,
    metric.weather_domain ?? null,
    metric.forecast_style,
    metric.metric_key,
    metric.valid_at ?? metric.observed_at ?? null,
    metric.known_at,
  ]);
}

function metricValue(metric: WeatherMetric): string {
  if (typeof metric.value_number === "number") {
    return `${metric.value_number}${metric.unit ? ` ${metric.unit}` : ""}`;
  }
  return metric.value_text ?? "-";
}

export function FeatureWeatherPanel({
  featureId,
  compact = false,
}: {
  featureId: string | null;
  compact?: boolean;
}) {
  const weather = useAdminFeatureWeather(featureId);
  const data = weather.data?.data;
  const metrics = data?.metrics ?? [];

  const columns = useMemo<ColumnDef<WeatherMetric, unknown>[]>(() => {
    const cols: ColumnDef<WeatherMetric, unknown>[] = [
      {
        id: "metric",
        header: "metric",
        // 두 줄 composite(name + key) — 정렬 비활성.
        enableSorting: false,
        cell: ({ row }) => {
          const metric = row.original;
          return (
            <>
              <div className="font-medium">
                {metric.metric_name ?? metric.metric_key}
              </div>
              <div className="font-mono text-xs text-muted-foreground">
                {metric.metric_key}
              </div>
            </>
          );
        },
      },
      {
        id: "value",
        header: "value",
        accessorFn: (metric) => metricValue(metric),
        cell: ({ row }) => (
          <span className="font-mono">{metricValue(row.original)}</span>
        ),
      },
    ];

    if (!compact) {
      cols.push({
        id: "dataset",
        header: "dataset",
        accessorFn: weatherMetricIdentity,
        cell: ({ row }) => {
          return (
            <>
              <div className="font-medium">{row.original.dataset_display_name}</div>
              <div className="font-mono text-xs text-muted-foreground">
                {row.original.dataset_key} · #{row.original.provider_dataset_id}
              </div>
            </>
          );
        },
      });
      cols.push({
        id: "provider",
        header: "provider",
        accessorFn: (metric) => metric.provider ?? "",
        cell: ({ row }) => (
          <Badge variant="outline">{row.original.provider ?? "-"}</Badge>
        ),
      });
      cols.push({
        id: "style",
        header: "style",
        accessorKey: "forecast_style",
        cell: ({ row }) => (
          <Badge variant="outline">{row.original.forecast_style}</Badge>
        ),
      });
    }

    cols.push({
      id: "severity",
      header: "severity",
      accessorFn: (metric) => metric.severity ?? "normal",
      cell: ({ row }) => (
        <StatusBadge status={row.original.severity ?? "normal"} />
      ),
    });

    if (!compact) {
      cols.push({
        id: "valid",
        header: "valid",
        accessorFn: (metric) => metric.valid_at ?? metric.observed_at ?? "",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.valid_at ?? row.original.observed_at)}
          </span>
        ),
      });
      cols.push({
        id: "known",
        header: "known",
        accessorFn: (metric) => metric.known_at,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.known_at)}
          </span>
        ),
      });
    }

    return cols;
  }, [compact]);

  return (
    <section
      className="rounded-lg border bg-background"
      data-testid="feature-weather-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 font-medium">
            <CloudSunIcon className="size-4 text-muted-foreground" />
            Weather
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            날씨 정보와 최근 업데이트 시간
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={data?.is_stale ? "destructive" : "outline"}>
            {data?.is_stale ? "stale" : "fresh"}
          </Badge>
          <Badge variant="secondary">{data?.metrics.length ?? 0}</Badge>
        </div>
      </div>

      {weather.isError ? (
        <Alert className="m-4" variant="destructive">
          <AlertTitle>weather 호출 실패</AlertTitle>
          <AlertDescription>{weather.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {data || weather.isLoading ? (
        <div className="flex flex-col gap-3 p-4">
          {data ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="text-muted-foreground">최근 업데이트</dt>
              <dd>{formatDateTime(data.latest_at)}</dd>
              <dt className="text-muted-foreground">선정 시각</dt>
              <dd>{formatDateTime(data.selected_at)}</dd>
              <dt className="text-muted-foreground">다음 갱신</dt>
              <dd>{formatDateTime(data.refresh_after)}</dd>
              <dt className="text-muted-foreground">styles</dt>
              <dd className="flex flex-wrap gap-1">
                {data.source_styles.length > 0
                  ? data.source_styles.map((style) => (
                      <Badge key={style} variant="outline">
                        {style}
                      </Badge>
                    ))
                  : "-"}
              </dd>
            </dl>
          ) : null}

          <div className="overflow-auto">
            <DataTable
              columns={columns}
              data={metrics}
              getRowId={(metric) =>
                weatherMetricIdentity(metric)
              }
              isLoading={weather.isLoading}
              emptyMessage="weather metric이 없습니다."
              manualSorting={false}
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}
