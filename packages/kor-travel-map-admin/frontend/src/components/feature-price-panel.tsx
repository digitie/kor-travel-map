"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { FuelIcon, HistoryIcon } from "lucide-react";
import { useMemo } from "react";

import { useFeaturePrice, type PricePoint } from "@/api/features";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { formatDateTime } from "@/lib/format";

const priceFormatter = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 1,
});

const chartPriceFormatter = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 0,
});

const PRODUCT_COLORS: Record<string, string> = {
  gasoline: "#2563eb",
  diesel: "#16a34a",
  premium_gasoline: "#dc2626",
  lpg: "#9333ea",
};

function productLabel(point: PricePoint): string {
  return point.product_name ?? point.product_key;
}

function priceLabel(point: PricePoint): string {
  return `${priceFormatter.format(point.value_number)}${point.unit ? ` ${point.unit}` : ""}`;
}

function productColor(productKey: string): string {
  return PRODUCT_COLORS[productKey] ?? "#475569";
}

function PriceHistoryChart({ history }: { history: PricePoint[] }) {
  const series = useMemo(() => {
    const groups = new Map<string, PricePoint[]>();
    for (const point of history) {
      const bucket = groups.get(point.product_key) ?? [];
      bucket.push(point);
      groups.set(point.product_key, bucket);
    }
    return Array.from(groups.entries())
      .map(([productKey, points]) => ({
        productKey,
        label: productLabel(points[0] as PricePoint),
        points: points
          .map((point) => ({
            ...point,
            timestamp: new Date(point.observed_at).getTime(),
          }))
          .filter((point) => Number.isFinite(point.timestamp))
          .sort((a, b) => a.timestamp - b.timestamp),
      }))
      .filter((item) => item.points.length > 0);
  }, [history]);

  const allPoints = series.flatMap((item) => item.points);
  if (allPoints.length < 2) {
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
  const x = (timestamp: number) => padX + ((timestamp - minTime) / timeSpan) * chartWidth;
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
          <polyline
            fill="none"
            key={item.productKey}
            points={item.points
              .map((point) => `${x(point.timestamp)},${y(point.value_number)}`)
              .join(" ")}
            stroke={productColor(item.productKey)}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2"
          />
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {series.map((item) => (
          <span className="inline-flex items-center gap-1" key={item.productKey}>
            <span
              className="size-2 rounded-full"
              style={{ backgroundColor: productColor(item.productKey) }}
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
  const price = useFeaturePrice(featureId, {
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
            제품별 최신 가격과 최근 이력
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
                  ? current.map((point) => (
                      <Badge key={point.product_key} variant="outline">
                        {productLabel(point)} {priceFormatter.format(point.value_number)}
                      </Badge>
                    ))
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
                `${point.provider}:${point.product_key}:${point.observed_at}`
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
