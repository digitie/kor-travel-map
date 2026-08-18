"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (detail) · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import { useAdminFeaturePrice, type PricePoint } from "@/api/features";
import { DetailList } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
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
import { formatCount, formatDateTime } from "@/lib/format";
import { withOccurrenceKeys } from "@/lib/occurrence-key";

const priceFormatter = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 1,
});

const chartPriceFormatter = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 0,
});

type CanonicalPricePoint = PricePoint & {
  provider_dataset_id: number;
  dataset_key: string;
  dataset_display_name: string;
  known_at: string;
};

function canonicalPricePoint(point: PricePoint): CanonicalPricePoint {
  // OpenAPI 재생성 전에도 0094 DTO의 정본 필드를 사용한다. generated type은
  // API export lane이 갱신한다.
  return point as CanonicalPricePoint;
}

function productLabel(point: PricePoint): string {
  return point.product_name ?? point.product_key;
}

function priceSeriesIdentity(point: PricePoint): string {
  const canonical = canonicalPricePoint(point);
  return JSON.stringify([
    canonical.provider_dataset_id,
    canonical.dataset_key,
    point.price_domain,
    point.product_key,
  ]);
}

function pricePointIdentity(point: PricePoint): string {
  return JSON.stringify([
    priceSeriesIdentity(point),
    point.observed_at,
    canonicalPricePoint(point).known_at,
  ]);
}

function datasetLabel(point: PricePoint): string {
  const canonical = canonicalPricePoint(point);
  return `${canonical.dataset_display_name} · ${canonical.dataset_key} · #${canonical.provider_dataset_id}`;
}

function priceLabel(point: PricePoint): string {
  return `${priceFormatter.format(point.value_number)}${point.unit ? ` ${point.unit}` : ""}`;
}

/**
 * series 색은 토큰만(design.md §Theme — 페이지 코드에 raw hsl/hex 없음). 비교 쌍 → 상태 잉크
 * 순으로 순환한다; series 수가 팔레트를 넘으면 순환하지만 legend 라벨이 항상 함께 붙는다.
 */
const SERIES_COLORS = [
  "var(--compare-a)",
  "var(--compare-b)",
  "var(--warning)",
  "var(--destructive)",
  "var(--success)",
  "var(--info)",
  "var(--brand-hover)",
  "var(--text-secondary)",
] as const;

function seriesColor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

export function PriceHistoryChart({ history }: { history: PricePoint[] }) {
  const series = useMemo(() => {
    const groups = new Map<string, { label: string; points: PricePoint[] }>();
    for (const point of history) {
      const seriesKey = priceSeriesIdentity(point);
      const group = groups.get(seriesKey) ?? {
        label: `${productLabel(point)} · ${datasetLabel(point)} · ${point.provider}/${point.price_domain}`,
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
      <EmptyState
        description="같은 series의 관측이 2건 이상 쌓이면 선으로 이어 그립니다."
        size="sm"
        title="그래프를 그릴 price history가 부족합니다."
      />
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
  const axisColor = "var(--border)";
  const pointOutline = "var(--card)";

  return (
    <div className="flex flex-col gap-2 rounded-panel border border-border bg-surface-subtle p-3">
      <svg
        aria-label="price history graph"
        className="h-40 w-full text-text-secondary"
        preserveAspectRatio="none"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <line
          stroke={axisColor}
          strokeWidth="1"
          style={{ stroke: axisColor }}
          x1={padX}
          x2={width - padX}
          y1={padTop + chartHeight}
          y2={padTop + chartHeight}
        />
        <line
          stroke={axisColor}
          strokeWidth="1"
          style={{ stroke: axisColor }}
          x1={padX}
          x2={padX}
          y1={padTop}
          y2={padTop + chartHeight}
        />
        <text
          className="font-mono tabular-nums"
          fill="currentColor"
          fontSize="10"
          x="2"
          y={padTop + 4}
        >
          {chartPriceFormatter.format(maxPrice)}
        </text>
        <text
          className="font-mono tabular-nums"
          fill="currentColor"
          fontSize="10"
          x="2"
          y={padTop + chartHeight}
        >
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
                style={{ stroke: item.color }}
              />
            ) : null}
            {withOccurrenceKeys(
              item.points,
              pricePointIdentity,
            ).map(({ key, value: point }) => (
              <circle
                cx={x(point.timestamp)}
                cy={y(point.value_number)}
                fill={item.color}
                key={key}
                r="3"
                stroke={pointOutline}
                strokeWidth="1"
                style={{ fill: item.color, stroke: pointOutline }}
              >
                <title>
                  {item.label} {priceLabel(point)} {formatDateTime(point.observed_at)}
                </title>
              </circle>
            ))}
          </g>
        ))}
      </svg>
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-2xs text-text-secondary">
        {series.map((item) => (
          <li className="inline-flex items-center gap-1" key={item.seriesKey}>
            <span
              aria-hidden="true"
              className="size-2 shrink-0 rounded-full"
              style={{ backgroundColor: item.color }}
            />
            {item.label}
          </li>
        ))}
      </ul>
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
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate font-medium">{productLabel(point)}</span>
              <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
                {point.product_key}
              </span>
            </div>
          );
        },
      },
      {
        id: "price",
        header: "price",
        accessorFn: (point) => point.value_number,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => <span className="tabular-nums">{priceLabel(row.original)}</span>,
      },
    ];

    if (!compact) {
      cols.push({
        id: "observed",
        header: "observed",
        accessorKey: "observed_at",
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.observed_at)}
          </span>
        ),
      });
      cols.push({
        id: "dataset",
        header: "dataset",
        accessorFn: datasetLabel,
        cell: ({ row }) => {
          const canonical = canonicalPricePoint(row.original);
          return (
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate font-medium">{canonical.dataset_display_name}</span>
              <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
                {canonical.dataset_key} · #{canonical.provider_dataset_id}
              </span>
            </div>
          );
        },
      });
      cols.push({
        id: "provider",
        header: "provider",
        accessorKey: "provider",
        cell: ({ row }) => (
          <span className="font-mono text-xs text-text-secondary">{row.original.provider}</span>
        ),
      });
      cols.push({
        id: "price_domain",
        header: "domain",
        accessorKey: "price_domain",
        cell: ({ row }) => (
          <span className="font-mono text-xs text-text-secondary">
            {row.original.price_domain}
          </span>
        ),
      });
      cols.push({
        id: "known",
        header: "known",
        accessorFn: (point) => canonicalPricePoint(point).known_at,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(canonicalPricePoint(row.original).known_at)}
          </span>
        ),
      });
    }

    return cols;
  }, [compact]);

  return (
    <section className="flex min-w-0 flex-col gap-3" data-testid="feature-price-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <div className="flex min-w-0 items-baseline gap-2">
          <h3 className="text-sm leading-snug font-semibold text-text-primary">Price</h3>
          {data ? (
            <span
              aria-label={`현재 가격 series ${formatCount(current.length)}건`}
              className="text-xs text-text-secondary tabular-nums"
            >
              {formatCount(current.length)}
            </span>
          ) : null}
        </div>
        {data ? (
          <StatusBadge
            label={data.is_stale ? "stale" : "fresh"}
            status={data.is_stale ? "stale" : "fresh"}
          />
        ) : null}
        <p className="basis-full text-xs text-text-secondary">
          canonical dataset/domain/product series별 최신 가격과 최근 이력
        </p>
      </div>

      {price.isError ? (
        <Alert variant="destructive">
          <AlertTitle>price 호출 실패</AlertTitle>
          <AlertDescription>{price.error.message}</AlertDescription>
          <AlertActions>
            <Button
              loading={price.isFetching}
              size="sm"
              type="button"
              variant="outline"
              onClick={() => void price.refetch()}
            >
              다시 시도
            </Button>
          </AlertActions>
        </Alert>
      ) : null}
      {price.isLoading ? (
        <div aria-busy="true" className="flex flex-col gap-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : null}
      {data ? (
        <div className="flex flex-col gap-4">
          <DetailList
            items={[
              { label: "latest", value: formatDateTime(data.latest_at) },
              {
                label: "current",
                value:
                  current.length > 0 ? (
                    <ul className="flex flex-col gap-0.5">
                      {withOccurrenceKeys(current, priceSeriesIdentity).map(
                        ({ key, value: point }) => (
                          <li className="text-xs tabular-nums" key={key}>
                            {productLabel(point)} · {datasetLabel(point)} · {point.provider}/
                            {point.price_domain} {priceFormatter.format(point.value_number)}
                          </li>
                        ),
                      )}
                    </ul>
                  ) : null,
              },
            ]}
            layout="inline"
          />

          <div className="flex flex-col gap-2">
            <h4 className="text-xs font-semibold text-text-primary">Graph</h4>
            <PriceHistoryChart history={history} />
          </div>

          <div className="flex flex-col gap-2">
            <h4 className="text-xs font-semibold text-text-primary">History</h4>
            <DataTable
              columns={historyColumns}
              data={history}
              emptyState={{
                title: "price history가 없습니다.",
                description: "가격 관측이 적재되면 series별로 최근 이력이 표시됩니다.",
              }}
              getRowId={(point) => pricePointIdentity(point)}
              isLoading={price.isLoading}
              manualSorting={false}
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}
