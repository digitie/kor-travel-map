"use client";

import { CloudSunIcon } from "lucide-react";

import { useFeatureWeather, type WeatherMetric } from "@/api/features";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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

      {weather.isLoading ? <Skeleton className="m-4 h-28" /> : null}
      {weather.isError ? (
        <Alert className="m-4" variant="destructive">
          <AlertTitle>weather 호출 실패</AlertTitle>
          <AlertDescription>{weather.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {data ? (
        <div className="flex flex-col gap-3 p-4">
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

          <div className="overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>metric</TableHead>
                  <TableHead>value</TableHead>
                  {!compact ? <TableHead>style</TableHead> : null}
                  <TableHead>severity</TableHead>
                  {!compact ? <TableHead>valid</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.metrics.map((metric) => (
                  <TableRow
                    key={`${metric.forecast_style}:${metric.metric_key}:${metric.valid_at ?? ""}`}
                  >
                    <TableCell>
                      <div className="font-medium">
                        {metric.metric_name ?? metric.metric_key}
                      </div>
                      <div className="font-mono text-xs text-muted-foreground">
                        {metric.metric_key}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono">{metricValue(metric)}</TableCell>
                    {!compact ? (
                      <TableCell>
                        <Badge variant="outline">{metric.forecast_style}</Badge>
                      </TableCell>
                    ) : null}
                    <TableCell>
                      <StatusBadge status={metric.severity ?? "normal"} />
                    </TableCell>
                    {!compact ? (
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(metric.valid_at ?? metric.observed_at)}
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
                {data.metrics.length === 0 ? (
                  <TableRow>
                    <TableCell
                      className="h-20 text-center text-muted-foreground"
                      colSpan={compact ? 3 : 5}
                    >
                      weather metric이 없습니다.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
        </div>
      ) : null}
    </section>
  );
}
