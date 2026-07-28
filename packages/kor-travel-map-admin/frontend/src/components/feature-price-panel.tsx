"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { FuelIcon, HistoryIcon } from "lucide-react";
import { useMemo } from "react";

import { useAdminFeaturePrice, type PricePoint } from "@/api/features";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { formatDateTime } from "@/lib/format";
import { withOccurrenceKeys } from "@/lib/occurrence-key";

const priceFormatter = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 1,
});

const chartPriceFormatter = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 0,
});

function productLabel(point: PricePoint): string {
  return point.product_name ?? point.product_key;
}

function priceSeriesIdentity(point: PricePoint): string {
  return JSON.stringify([point.provider, point.price_domain, point.product_key]);
}

function priceLabel(point: PricePoint): string {
  return `${priceFormatter.format(point.value_number)}${point.unit ? ` ${point.unit}` : ""}`;
}

function seriesColor(index: number): string {
  const goldenAngle = 137.508;
  return `hsl(${(index * goldenAngle) % 360} 72% 42%)`;
}

export function PriceHistoryChart({ history }: { history: PricePoint[] }) {
  const series = useMemo(() => {
    const groups = new Map<string, { label: string; points: PricePoint[] }>();
    for (const point of history) {
      const seriesKey = priceSeriesIdentity(point);
      const group = groups.get(seriesKey) ?? {
        label: `${productLabel(point)} · ${point.provider}/${point.price_domain}`,
        points: [],
      };
      group.points.push(point);
      groups.set(seriesKey, group);
    }

    const result: Array<{
      color: string;
      label: string;
      points: Array<PricePoint & { timestamp: number }>;
      seriesKey: string;
    }> = [];
    for (const [seriesKey, group] of groups) {
      const points: Array<PricePoint & { timestamp: number }> = [];
      for (const point of group.points) {
        const timestamp = new Date(point.observed_at).getTime();
        if (Number.isFinite(timestamp)) points.push({ ...point, timestamp });
      }
      if (points.length === 0) continue;
      points.sort((left, right) => left.timestamp - right.timestamp);
      result.push({ color: "", label: group.label, points, seriesKey });
    }
    result.sort((left, right) => left.seriesKey.localeCompare(right.seriesKey));
    for (const [index, item] of result.entries()) {
      item.color = seriesColor(index);
    }
    return result;
  }, [history]);

  const allPoints = series.flatMap((item) => item.points);
  if (allPoints.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
        그래프를 그릴 price history가 부족합니다.
      </div>
    );
  }

  const minTime = Math.min(...allPoints.map((point) => point.timestamp));
  const maxTime = Math.max(...allPoints.map((point) => point.timestamp));
  const minPrice = Math.min(...allPoints.map((point) => point.value_number));
  const maxPrice = Math.max(...allPoints.map((point) => point.value_number));
  const width = 360;
  const height = 160;
  const padX = 36;
  const padTop = 16;
  const padBottom = 28;
  const chartWidth = width - padX * 2;
  const chartHeight = height - padTop - padBottom;
  const timeSpan = Math.max(1, maxTime - minTime);
  const priceSpan = Math.max(1, maxPrice - minPrice);
  const x = (timestamp: number) =>
    maxTime === minTime
      ? padX + chartWidth / 2
      : padX + ((timestamp - minTime) / timeSpan) * chartWidth;
  const y = (value: number) =>
    padTop + chartHeight - ((value - minPrice) / priceSpan) * chartHeight;

  return (
    <div className="rounded-md border bg-muted/20 p-3">
      <svg
        aria-label="price history graph"
        className="h-40 w-full"
        preserveAspectRatio="none"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <line
          stroke="hsl(var(--border))"
          strokeWidth="1"
          x1={padX}
          x2={width - padX}
          y1={padTop + chartHeight}
          y2={padTop + chartHeight}
        />
        <line
          stroke="hsl(var(--border))"
          strokeWidth="1"
          x1={padX}
          x2={padX}
          y1={padTop}
          y2={padTop + chartHeight}
        />
        <text fill="currentColor" fontSize="10" x="2" y={padTop + 4}>
          {chartPriceFormatter.format(maxPrice)}
        </text>
        <text fill="currentColor" fontSize="10" x="2" y={padTop + chartHeight}>
          {chartPriceFormatter.format(minPrice)}
        </text>
        {series.map((item) => (
          <g key={item.seriesKey}>
            {item.points.length >= 2 ? (
              <polyline
                fill="none"
                points={item.points
                  .map((point) => `${x(point.timestamp)},${y(point.value_number)}`)
                  .join(" ")}
                stroke={item.color}
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
              />
            ) : null}
            {withOccurrenceKeys(
              item.points,
              (point) => point.observed_at,
            ).map(({ key, value: point }) => (
              <circle
                cx={x(point.timestamp)}
                cy={y(point.value_number)}
                fill={item.color}
                key={key}
                r="3"
                stroke="#ffffff"
                strokeWidth="1"
              >
                <title>
                  {item.label} {priceLabel(point)} {formatDateTime(point.observed_at)}
                </title>
              </circle>
            ))}
          </g>
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {series.map((item) => (
          <span className="inline-flex items-center gap-1" key={item.seriesKey}>
            <span
              className="size-2 rounded-full"
              style={{ backgroundColor: item.color }}
            />
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function FeaturePricePanel({
  featureId,
  compact = false,
}: {
  featureId: string | null;
  compact?: boolean;
}) {
  const price = useAdminFeaturePrice(featureId, {
    historyLimit: compact ? 30 : 100,
  });
  const data = price.data?.data;
  const current = data?.current ?? [];
  const history = data?.history ?? [];
  const historyColumns = useMemo<ColumnDef<PricePoint, unknown>[]>(() => {
    const cols: ColumnDef<PricePoint, unknown>[] = [
      {
        id: "product",
        header: "product",
        accessorFn: productLabel,
        cell: ({ row }) => {
          const point = row.original;
          return (
            <>
              <div className="font-medium">{productLabel(point)}</div>
              <div className="font-mono text-xs text-muted-foreground">
                {point.product_key}
              </div>
            </>
          );
        },
      },
      {
        id: "price",
        header: "price",
        accessorFn: (point) => point.value_number,
        cell: ({ row }) => (
          <span className="font-mono">{priceLabel(row.original)}</span>
        ),
      },
    ];

    if (!compact) {
      cols.push({
        id: "observed",
        header: "observed",
        accessorKey: "observed_at",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.observed_at)}
          </span>
        ),
      });
      cols.push({
        id: "provider",
        header: "provider",
        accessorKey: "provider",
        cell: ({ row }) => (
          <Badge variant="outline">{row.original.provider}</Badge>
        ),
      });
      cols.push({
        id: "price_domain",
        header: "domain",
        accessorKey: "price_domain",
        cell: ({ row }) => (
          <Badge variant="outline">{row.original.price_domain}</Badge>
        ),
      });
    }

    return cols;
  }, [compact]);

  return (
    <section className="rounded-lg border bg-background" data-testid="feature-price-panel">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 font-medium">
            <FuelIcon className="size-4 text-muted-foreground" />
            Price
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            provider/domain/product series별 최신 가격과 최근 이력
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={data?.is_stale ? "destructive" : "outline"}>
            {data?.is_stale ? "stale" : "fresh"}
          </Badge>
          <Badge variant="secondary">{current.length}</Badge>
        </div>
      </div>

      {price.isError ? (
        <Alert className="m-4" variant="destructive">
          <AlertTitle>price 호출 실패</AlertTitle>
          <AlertDescription>{price.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {data || price.isLoading ? (
        <div className="flex flex-col gap-4 p-4">
          {data ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="text-muted-foreground">latest</dt>
              <dd>{formatDateTime(data.latest_at)}</dd>
              <dt className="text-muted-foreground">asof</dt>
              <dd>{formatDateTime(data.asof)}</dd>
              <dt className="text-muted-foreground">current</dt>
              <dd className="flex flex-wrap gap-2">
                {current.length > 0
                  ? withOccurrenceKeys(current, priceSeriesIdentity).map(
                      ({ key, value: point }) => (
                        <Badge key={key} variant="outline">
                          {productLabel(point)} · {point.provider}/{point.price_domain}{" "}
                          {priceFormatter.format(point.value_number)}
                        </Badge>
                      ),
                    )
                  : "-"}
              </dd>
            </dl>
          ) : null}

          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium">
              <HistoryIcon className="size-4 text-muted-foreground" />
              Graph
            </div>
            <PriceHistoryChart history={history} />
          </div>

          <div className="overflow-auto">
            <div className="mb-2 flex items-center gap-2 text-sm font-medium">
              <HistoryIcon className="size-4 text-muted-foreground" />
              History
            </div>
            <DataTable
              columns={historyColumns}
              data={history}
              getRowId={(point) =>
                JSON.stringify([
                  point.provider,
                  point.price_domain,
                  point.product_key,
                  point.observed_at,
                ])
              }
              isLoading={price.isLoading}
              emptyMessage="price history가 없습니다."
              manualSorting={false}
            />
          </div>
          {data?.is_stale ? <StatusBadge status="stale" /> : null}
        </div>
      ) : null}
    </section>
  );
}
