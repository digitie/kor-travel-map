"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { CloudSunIcon } from "lucide-react";
import { useMemo } from "react";

import { useFeatureWeather, type WeatherMetric } from "@/api/features";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { formatDateTime } from "@/lib/format";

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
  const weather = useFeatureWeather(featureId);
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
            최신 forecast_style별 metric
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
              <dt className="text-muted-foreground">latest</dt>
              <dd>{formatDateTime(data.latest_at)}</dd>
              <dt className="text-muted-foreground">asof</dt>
              <dd>{formatDateTime(data.asof)}</dd>
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
                `${metric.forecast_style}:${metric.metric_key}:${metric.valid_at ?? ""}`
              }
              isLoading={weather.isLoading}
              emptyMessage="weather metric이 없습니다."
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}
