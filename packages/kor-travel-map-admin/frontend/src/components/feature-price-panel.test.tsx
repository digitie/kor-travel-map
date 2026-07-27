// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PricePoint } from "@/api/features";

import { PriceHistoryChart } from "./feature-price-panel";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function point(overrides: Partial<PricePoint> = {}): PricePoint {
  return {
    observed_at: "2026-07-13T06:00:00.000Z",
    price_domain: "opinet_gas_station",
    product_key: "gasoline",
    product_name: "휘발유",
    provider: "python-opinet-api",
    source_product_key: "B027",
    source_product_name: "휘발유",
    unit: "KRW/L",
    value_number: 1_820,
    ...overrides,
  };
}

describe("PriceHistoryChart", () => {
  it("단일 관측시점의 다중 유종을 각각 점으로 그린다", () => {
    render(
      <PriceHistoryChart
        history={[
          point(),
          point({
            product_key: "diesel",
            product_name: "경유",
            source_product_key: "D047",
            source_product_name: "경유",
            value_number: 1_650,
          }),
          point({
            product_key: "premium_gasoline",
            product_name: "고급휘발유",
            source_product_key: "B034",
            source_product_name: "고급휘발유",
            value_number: 2_050,
          }),
        ]}
      />,
    );

    const graph = screen.getByRole("img", { name: "price history graph" });
    expect(graph.querySelectorAll("circle")).toHaveLength(3);
    expect(graph.querySelectorAll("polyline")).toHaveLength(0);
    expect(
      Array.from(graph.querySelectorAll("circle"), (circle) => circle.getAttribute("cx")),
    ).toEqual(["180", "180", "180"]);
  });

  it("같은 유종의 다중 관측은 점과 선을 함께 그린다", () => {
    render(
      <PriceHistoryChart
        history={[
          point({ observed_at: "2026-07-12T06:00:00.000Z", value_number: 1_800 }),
          point({ observed_at: "2026-07-13T06:00:00.000Z", value_number: 1_820 }),
        ]}
      />,
    );

    const graph = screen.getByRole("img", { name: "price history graph" });
    expect(graph.querySelectorAll("circle")).toHaveLength(2);
    expect(graph.querySelectorAll("polyline")).toHaveLength(1);
  });

  it("같은 product라도 provider·price domain이 다르면 별도 series로 그린다", () => {
    render(
      <PriceHistoryChart
        history={[
          point({ observed_at: "2026-07-12T06:00:00.000Z" }),
          point({ observed_at: "2026-07-13T06:00:00.000Z" }),
          point({
            provider: "manual-admin",
            price_domain: "curated_price",
            observed_at: "2026-07-12T06:00:00.000Z",
            value_number: 1_810,
          }),
          point({
            provider: "manual-admin",
            price_domain: "curated_price",
            observed_at: "2026-07-13T06:00:00.000Z",
            value_number: 1_830,
          }),
        ]}
      />,
    );

    const graph = screen.getByRole("img", { name: "price history graph" });
    expect(graph.querySelectorAll("circle")).toHaveLength(4);
    expect(graph.querySelectorAll("polyline")).toHaveLength(2);
    expect(graph.querySelectorAll(":scope > g")).toHaveLength(2);
    expect(
      new Set(
        Array.from(graph.querySelectorAll("polyline"), (line) =>
          line.getAttribute("stroke"),
        ),
      ).size,
    ).toBe(2);
    expect(
      new Set(
        Array.from(graph.querySelectorAll("circle"), (circle) =>
          circle.getAttribute("fill"),
        ),
      ).size,
    ).toBe(2);
  });

  it("동일 series·시각의 중복 관측도 고유 React key로 표시한다", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<PriceHistoryChart history={[point(), point()]} />);

    const graph = screen.getByRole("img", { name: "price history graph" });
    expect(graph.querySelectorAll("circle")).toHaveLength(2);
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain(
      "Encountered two children with the same key",
    );
  });
});
