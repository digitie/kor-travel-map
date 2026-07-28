import { opinetPastPriceLabel } from "@/lib/price-freshness";

export interface ClusterPriceSummaryPoint {
  provider: string;
  price_domain: string;
  product_key: string;
  product_name?: string | null;
  value_number: number;
  unit: string;
  observed_at: string;
}

const PRICE_FORMATTER = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 0,
});
const FUEL_PRICE_ORDER = ["gasoline", "diesel", "premium_gasoline"] as const;
const FUEL_PRICE_KEYS = new Set<string>(FUEL_PRICE_ORDER);

function fuelPriceOrder(productKey: string): number {
  const index = FUEL_PRICE_ORDER.indexOf(
    productKey as (typeof FUEL_PRICE_ORDER)[number],
  );
  return index === -1 ? 99 : index;
}

function fuelShortLabel(
  productKey: string,
  productName: string | null | undefined,
): string {
  if (productKey === "gasoline") return "휘";
  if (productKey === "diesel") return "경";
  if (productKey === "premium_gasoline") return "고";
  return productName ?? productKey;
}

export function priceMarkerLabel(
  summary: readonly ClusterPriceSummaryPoint[] | null | undefined,
): string | null {
  const points: ClusterPriceSummaryPoint[] = [];
  for (const point of summary ?? []) {
    if (FUEL_PRICE_KEYS.has(point.product_key)) points.push(point);
  }
  points.sort(
    (left, right) =>
      fuelPriceOrder(left.product_key) - fuelPriceOrder(right.product_key) ||
      left.provider.localeCompare(right.provider) ||
      left.price_domain.localeCompare(right.price_domain),
  );
  if (points.length === 0) return null;

  const countByProduct = new Map<string, number>();
  for (const point of points) {
    countByProduct.set(
      point.product_key,
      (countByProduct.get(point.product_key) ?? 0) + 1,
    );
  }
  return points
    .map((point) => {
      const identity =
        (countByProduct.get(point.product_key) ?? 0) > 1
          ? ` ${point.provider}/${point.price_domain}`
          : "";
      const price = `${fuelShortLabel(
        point.product_key,
        point.product_name,
      )}${identity} ${PRICE_FORMATTER.format(point.value_number)}`;
      const pastLabel = opinetPastPriceLabel([point]);
      return pastLabel ? `${price} · ${pastLabel}` : price;
    })
    .join("\n");
}
