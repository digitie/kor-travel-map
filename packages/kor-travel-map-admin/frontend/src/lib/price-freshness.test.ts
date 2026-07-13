import { afterEach, describe, expect, it, vi } from "vitest";

import {
  isSameKstCalendarDate,
  millisecondsUntilNextKstMidnight,
  opinetPastPriceLabel,
  scheduleKstMidnightTicks,
} from "./price-freshness";

const OPINET = "python-opinet-api";

describe("OpiNet 가격 KST 날짜 판정", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("KST 자정 직전은 과거, 자정 직후는 오늘로 판정한다", () => {
    const now = new Date("2026-07-13T15:01:00.000Z"); // 7/14 00:01 KST
    const yesterday = "2026-07-13T14:59:00.000Z"; // 7/13 23:59 KST
    const today = "2026-07-13T15:00:00.000Z"; // 7/14 00:00 KST

    expect(isSameKstCalendarDate(yesterday, now)).toBe(false);
    expect(isSameKstCalendarDate(today, now)).toBe(true);
    expect(
      opinetPastPriceLabel([{ provider: OPINET, observed_at: yesterday }], now),
    ).toBe("과거 7/13");
    expect(
      opinetPastPriceLabel([{ provider: OPINET, observed_at: today }], now),
    ).toBeNull();
  });

  it("오늘과 과거 관측이 섞이면 각 유종을 독립적으로 판정한다", () => {
    const now = new Date("2026-07-13T15:01:00.000Z"); // 7/14 00:01 KST
    const yesterday = { provider: OPINET, observed_at: "2026-07-13T14:59:00.000Z" };
    const today = { provider: OPINET, observed_at: "2026-07-13T15:00:00.000Z" };

    expect(opinetPastPriceLabel([yesterday], now)).toBe("과거 7/13");
    expect(opinetPastPriceLabel([today], now)).toBeNull();
  });

  it("OpiNet이 아닌 provider의 예전 가격은 표시하지 않는다", () => {
    expect(
      opinetPastPriceLabel(
        [{ provider: "python-krex-api", observed_at: "2026-07-01T00:00:00Z" }],
        new Date("2026-07-14T00:00:00+09:00"),
      ),
    ).toBeNull();
  });

  it("KST 자정 경계에서만 freshness callback을 실행하고 다음 자정을 예약한다", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-13T14:59:59.000Z")); // 23:59:59 KST
    const callback = vi.fn();
    const cleanup = scheduleKstMidnightTicks(callback);

    expect(millisecondsUntilNextKstMidnight()).toBe(1_000);
    vi.advanceTimersByTime(999);
    expect(callback).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(callback).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(24 * 60 * 60 * 1_000);
    expect(callback).toHaveBeenCalledTimes(2);

    cleanup();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cleanup은 아직 도달하지 않은 자정 timer를 제거한다", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-13T14:59:59.000Z"));
    const callback = vi.fn();
    const cleanup = scheduleKstMidnightTicks(callback);

    cleanup();
    vi.advanceTimersByTime(1_000);

    expect(callback).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
