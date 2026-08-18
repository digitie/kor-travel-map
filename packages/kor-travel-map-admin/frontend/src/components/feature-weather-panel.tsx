"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (detail) · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import {
  useAdminFeatureWeather,
  type WeatherMetric,
} from "@/api/features";
import { DetailList } from "@/components/detail-list";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DataTable,
  type DataTableColumnMeta,
} from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { NULL_GLYPH, formatCount, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

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
  return metric.value_text ?? NULL_GLYPH;
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
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate font-medium">
                {metric.metric_name ?? metric.metric_key}
              </span>
              <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
                {metric.metric_key}
              </span>
            </div>
          );
        },
      },
      {
        id: "value",
        header: "value",
        accessorFn: (metric) => metricValue(metric),
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => {
          const value = metricValue(row.original);
          return (
            <span className={cn("tabular-nums", value === NULL_GLYPH && "text-text-tertiary")}>
              {value}
            </span>
          );
        },
      },
    ];

    if (!compact) {
      cols.push({
        id: "dataset",
        header: "dataset",
        accessorFn: weatherMetricIdentity,
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate font-medium">{row.original.dataset_display_name}</span>
            <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
              {row.original.dataset_key} · #{row.original.provider_dataset_id}
            </span>
          </div>
        ),
      });
      cols.push({
        id: "provider",
        header: "provider",
        accessorFn: (metric) => metric.provider ?? "",
        cell: ({ row }) => (
          <span
            className={cn(
              "font-mono text-xs",
              row.original.provider ? "text-text-secondary" : "text-text-tertiary",
            )}
          >
            {row.original.provider ?? NULL_GLYPH}
          </span>
        ),
      });
      cols.push({
        id: "style",
        header: "style",
        accessorKey: "forecast_style",
        cell: ({ row }) => (
          <span className="font-mono text-xs text-text-secondary">
            {row.original.forecast_style}
          </span>
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
          <span className="text-text-secondary">
            {formatDateTime(row.original.valid_at ?? row.original.observed_at)}
          </span>
        ),
      });
      cols.push({
        id: "known",
        header: "known",
        accessorFn: (metric) => metric.known_at,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.known_at)}
          </span>
        ),
      });
    }

    return cols;
  }, [compact]);

  return (
    <section
      className="flex min-w-0 flex-col gap-3"
      data-testid="feature-weather-panel"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <div className="flex min-w-0 items-baseline gap-2">
          <h3 className="text-sm leading-snug font-semibold text-text-primary">Weather</h3>
          {data ? (
            <span
              aria-label={`weather metric ${formatCount(data.metrics.length)}건`}
              className="text-xs text-text-secondary tabular-nums"
            >
              {formatCount(data.metrics.length)}
            </span>
          ) : null}
        </div>
        {data ? (
          <StatusBadge
            label={data.is_stale ? "stale" : "fresh"}
            status={data.is_stale ? "stale" : "fresh"}
          />
        ) : null}
        <p className="basis-full text-xs text-text-secondary">날씨 정보와 최근 업데이트 시간</p>
      </div>

      {weather.isError ? (
        <Alert variant="destructive">
          <AlertTitle>weather 호출 실패</AlertTitle>
          <AlertDescription>{weather.error.message}</AlertDescription>
          <AlertActions>
            <Button
              loading={weather.isFetching}
              size="sm"
              type="button"
              variant="outline"
              onClick={() => void weather.refetch()}
            >
              다시 시도
            </Button>
          </AlertActions>
        </Alert>
      ) : null}
      {weather.isLoading ? (
        <div aria-busy="true" className="flex flex-col gap-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : null}
      {data ? (
        <div className="flex flex-col gap-4">
          <DetailList
            items={[
              { label: "최근 업데이트", value: formatDateTime(data.latest_at) },
              { label: "선정 시각", value: formatDateTime(data.selected_at) },
              { label: "다음 갱신", value: formatDateTime(data.refresh_after) },
              {
                label: "styles",
                value:
                  data.source_styles.length > 0 ? (
                    <span className="flex flex-wrap gap-x-2 gap-y-0.5 font-mono text-xs">
                      {data.source_styles.map((style) => (
                        <span key={style}>{style}</span>
                      ))}
                    </span>
                  ) : null,
              },
            ]}
            layout="inline"
          />

          <DataTable
            columns={columns}
            data={metrics}
            emptyState={{
              title: "weather metric이 없습니다.",
              description: "예보/실황 metric이 적재되면 style·severity와 함께 표시됩니다.",
            }}
            getRowId={(metric) => weatherMetricIdentity(metric)}
            isLoading={weather.isLoading}
            manualSorting={false}
          />
        </div>
      ) : null}
    </section>
  );
}
