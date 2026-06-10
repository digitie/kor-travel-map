import { describe, expect, it } from "vitest";

import {
  combine,
  jsonObject,
  numberInRange,
  required,
  validateForm,
} from "./form-validation";

type TargetForm = {
  externalSystem: string;
  targetKey: string;
  lon: string;
  lat: string;
  payload: string;
};

const baseValues: TargetForm = {
  externalSystem: "tripmate",
  targetKey: "poi-1",
  lon: "126.978",
  lat: "37.5665",
  payload: "",
};

describe("validateForm", () => {
  it("모든 규칙 통과 시 isValid=true, 에러 없음", () => {
    const result = validateForm(baseValues, [
      { field: "externalSystem", validate: required() },
      { field: "targetKey", validate: required() },
      { field: "lon", validate: numberInRange({ min: 124, max: 132 }) },
      { field: "lat", validate: numberInRange({ min: 33, max: 43 }) },
    ]);
    expect(result.isValid).toBe(true);
    expect(result.errors).toEqual({});
    expect(result.firstErrorField).toBeNull();
  });

  it("firstErrorField는 규칙 선언 순서 기준 첫 실패 필드", () => {
    const result = validateForm(
      { ...baseValues, externalSystem: "  ", targetKey: "" },
      [
        { field: "externalSystem", validate: required("외부 시스템 필수") },
        { field: "targetKey", validate: required("타겟 키 필수") },
      ],
    );
    expect(result.isValid).toBe(false);
    expect(result.firstErrorField).toBe("externalSystem");
    expect(result.errors).toEqual({
      externalSystem: "외부 시스템 필수",
      targetKey: "타겟 키 필수",
    });
  });

  it("한 필드의 후속 규칙은 첫 에러가 잡히면 건너뛴다", () => {
    const result = validateForm({ ...baseValues, lon: "" }, [
      { field: "lon", validate: required("경도 필수") },
      { field: "lon", validate: numberInRange({ min: 124 }) },
    ]);
    expect(result.errors.lon).toBe("경도 필수");
  });
});

describe("required", () => {
  it("null/undefined/공백 문자열을 거부", () => {
    expect(required()(null as never, {} as never)).not.toBeNull();
    expect(required()(undefined as never, {} as never)).not.toBeNull();
    expect(required()("   " as never, {} as never)).not.toBeNull();
  });
  it("비어있지 않은 값은 통과", () => {
    expect(required()("x" as never, {} as never)).toBeNull();
  });
});

describe("numberInRange", () => {
  it("빈 문자열은 통과(선택 필드)", () => {
    expect(numberInRange()("" as never, {} as never)).toBeNull();
  });
  it("비숫자 거부", () => {
    expect(numberInRange()("abc" as never, {} as never)).not.toBeNull();
  });
  it("범위 밖 거부, 안쪽 통과", () => {
    expect(numberInRange({ min: 124, max: 132 })("100" as never, {} as never)).not.toBeNull();
    expect(numberInRange({ min: 124, max: 132 })("200" as never, {} as never)).not.toBeNull();
    expect(numberInRange({ min: 124, max: 132 })("126.9" as never, {} as never)).toBeNull();
  });
});

describe("jsonObject", () => {
  it("빈 문자열은 통과", () => {
    expect(jsonObject()("" as never, {} as never)).toBeNull();
  });
  it("유효 JSON 통과, 깨진 JSON 거부", () => {
    expect(jsonObject()('{"a":1}' as never, {} as never)).toBeNull();
    expect(jsonObject()("{not json" as never, {} as never)).not.toBeNull();
  });
});

describe("combine", () => {
  it("첫 실패 검증기의 메시지를 반환", () => {
    const validator = combine<TargetForm>(
      required("필수"),
      jsonObject("JSON 오류"),
    );
    expect(validator("" as never, baseValues)).toBe("필수");
    expect(validator("{bad" as never, baseValues)).toBe("JSON 오류");
    expect(validator('{"ok":true}' as never, baseValues)).toBeNull();
  });
});
