import { describe, expect, it } from "vitest";

import {
  lastTickOrWindowNotice,
  SENSOR_TICK_WINDOW_LABEL,
} from "./dagster-tick-window";

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
