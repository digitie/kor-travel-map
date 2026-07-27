import { describe, expect, it } from "vitest";

import { withOccurrenceKeys } from "./occurrence-key";

describe("withOccurrenceKeys", () => {
  it("동일 identity의 occurrence마다 유일하고 재현 가능한 key를 만든다", () => {
    const values = [{ code: "A" }, { code: "B" }, { code: "A" }];
    const first = withOccurrenceKeys(values, (value) => value.code);
    const second = withOccurrenceKeys(values, (value) => value.code);

    expect(first.map(({ key }) => key)).toEqual(second.map(({ key }) => key));
    expect(new Set(first.map(({ key }) => key))).toHaveLength(values.length);
    expect(first.map(({ value }) => value)).toEqual(values);
  });
});
