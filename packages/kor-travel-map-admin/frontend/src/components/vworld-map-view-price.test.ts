import { describe, expect, it } from "vitest";

import {
  priceMarkerLabel,
  type ClusterPriceSummaryPoint,
} from "./vworld-map-view";

function point(
  overrides: Partial<ClusterPriceSummaryPoint> = {},
): ClusterPriceSummaryPoint {
  return {
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
  it("같은 product의 다중 series를 provider/domain까지 구분한다", () => {
    const label = priceMarkerLabel([
      point(),
      point({
        provider: "python-korea-expressway-api",
        price_domain: "rest_area_fuel",
        value_number: 1_790,
      }),
    ]);

    expect(label).toContain("python-opinet-api/opinet_gas_station");
    expect(label).toContain(
      "python-korea-expressway-api/rest_area_fuel",
    );
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
