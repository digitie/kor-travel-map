import { describe, expect, it } from "vitest";

import { getMakiGlyph, KNOWN_MAKI_NAMES, resolveMarkerLabel } from "./maki";

describe("weather provider marker glyphs", () => {
  it("KMA 날씨와 AirKorea 대기질을 서로 다른 글리프로 표시한다", () => {
    expect(getMakiGlyph("weather")).toBe("☀");
    expect(getMakiGlyph("air-quality")).toBe("🌫");
    expect(resolveMarkerLabel("weather")).not.toBe(
      resolveMarkerLabel("air-quality"),
    );
  });
});

describe("provider-direct notice marker glyphs", () => {
  // 모르는 이름은 첫 글자 배지("R", "W")로 떨어진다 — 그 배지가 아니라 글리프여야 한다.
  it.each([
    ["roadblock", "🚧", "R"], // providers.krex TRAFFIC_NOTICE_MARKER_ICON
    ["warning", "⚠", "W"], // providers.krforest_safety LANDSLIDE_FORECAST_MARKER_ICON
  ])("%s는 글리프 %s로 표시하고 첫 글자 배지 %s로 떨어지지 않는다", (name, glyph, badge) => {
    expect(KNOWN_MAKI_NAMES).toContain(name);
    expect(getMakiGlyph(name)).toBe(glyph);
    expect(resolveMarkerLabel(name)).toBe(glyph);
    expect(resolveMarkerLabel(name)).not.toBe(badge);
  });

  it("모르는 이름은 여전히 첫 글자 배지로 떨어진다(대조군)", () => {
    expect(getMakiGlyph("no-such-icon")).toBeNull();
    expect(resolveMarkerLabel("no-such-icon")).toBe("N");
  });
});
