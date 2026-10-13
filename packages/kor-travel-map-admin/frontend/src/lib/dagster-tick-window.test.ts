import { describe, expect, it } from "vitest";

import {
  lastTickOrWindowNotice,
  SCHEDULE_TICK_WINDOW_LABEL,
  SENSOR_TICK_WINDOW_LABEL,
} from "./dagster-tick-window";

describe("window labels", () => {
  it("names the API windows in the operator's words", () => {
    expect(SCHEDULE_TICK_WINDOW_LABEL).toBe("최근 2일 tick 없음");
    expect(SENSOR_TICK_WINDOW_LABEL).toBe("최근 1시간 tick 없음");
  });
});

describe("lastTickOrWindowNotice", () => {
  it("returns the newest tick when the window has one", () => {
    expect(
      lastTickOrWindowNotice(
        [{ status: "SUCCESS", timestamp: 10 }, { status: "SKIPPED", timestamp: 5 }],
        "RUNNING",
        SENSOR_TICK_WINDOW_LABEL,
      ),
    ).toEqual({ status: "SUCCESS", timestamp: 10 });
  });

  it("labels a RUNNING instigator with an empty window instead of hiding it", () => {
    expect(lastTickOrWindowNotice([], "RUNNING", SENSOR_TICK_WINDOW_LABEL)).toEqual({
      status: SENSOR_TICK_WINDOW_LABEL,
      timestamp: null,
    });
  });

  it("keeps a STOPPED instigator without ticks empty", () => {
    expect(lastTickOrWindowNotice([], "STOPPED", SENSOR_TICK_WINDOW_LABEL)).toBeNull();
    expect(lastTickOrWindowNotice(undefined, null, SENSOR_TICK_WINDOW_LABEL)).toBeNull();
  });
});
