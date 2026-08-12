import { describe, expect, it } from "vitest";

import {
  priceMarkerLabel,
  type ClusterPriceSummaryPoint,
} from "@/lib/price-marker-label";

function point(
  overrides: Partial<ClusterPriceSummaryPoint> = {},
): ClusterPriceSummaryPoint {
  return {
    provider_dataset_id: 17,
    dataset_key: "opinet_gas_station_prices",
    dataset_display_name: "OpiNet 주유소 가격",
    known_at: "2026-07-27T00:05:00.000Z",
    observed_at: "2026-07-27T00:00:00.000Z",
    price_domain: "opinet_gas_station",
    product_key: "gasoline",
    product_name: "휘발유",
    provider: "python-opinet-api",
    unit: "KRW/L",
    value_number: 1_820,
    ...overrides,
  };
}

describe("priceMarkerLabel", () => {
  it("같은 product의 다중 series를 canonical dataset/domain까지 구분한다", () => {
    const label = priceMarkerLabel([
      point(),
      point({
        provider_dataset_id: 29,
        dataset_key: "expressway_rest_area_prices",
        dataset_display_name: "휴게소 유가",
        price_domain: "rest_area_fuel",
        value_number: 1_790,
      }),
    ]);

    expect(label).toContain("OpiNet 주유소 가격 #17");
    expect(label).toContain("휴게소 유가 #29");
    expect(label).toContain("1,820");
    expect(label).toContain("1,790");
  });

  it("product가 한 series뿐이면 짧은 marker label을 유지한다", () => {
    const label = priceMarkerLabel([point()]);

    expect(label).toContain("휘 1,820");
    expect(label).not.toContain("python-opinet-api");
    expect(label).not.toContain("opinet_gas_station");
  });
});
