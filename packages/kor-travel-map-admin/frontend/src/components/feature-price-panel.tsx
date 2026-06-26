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

function productLabel(point: PricePoint): string {
  return point.product_name ?? point.product_key;
}

function priceLabel(point: PricePoint): string {
  return `${priceFormatter.format(point.value_number)}${point.unit ? ` ${point.unit}` : ""}`;
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
