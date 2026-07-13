import { describe, expect, it } from "vitest";

import { getMakiGlyph, resolveMarkerLabel } from "./maki";

describe("weather provider marker glyphs", () => {
  it("KMA 날씨와 AirKorea 대기질을 서로 다른 글리프로 표시한다", () => {
    expect(getMakiGlyph("weather")).toBe("☀");
    expect(getMakiGlyph("air-quality")).toBe("🌫");
    expect(resolveMarkerLabel("weather")).not.toBe(
      resolveMarkerLabel("air-quality"),
    );
  });
});
