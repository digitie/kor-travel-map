import { describe, expect, it } from "vitest";

import {
  combine,
  dateOrdered,
  integerString,
  jsonObject,
  numberInRange,
  ordered,
  pairRequired,
  parseJsonObjectField,
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
  externalSystem: "external-app",
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

describe("pairRequired", () => {
  type Pair = { lon: string; lat: string };
  it("상대 필드만 채워져 있으면 에러", () => {
    const validate = pairRequired<Pair>("lat", "경도와 위도를 함께 입력하세요.");
    expect(validate("", { lon: "", lat: "37.5" })).toBe(
      "경도와 위도를 함께 입력하세요.",
    );
  });
  it("둘 다 비었거나 둘 다 채워지면 통과", () => {
    const validate = pairRequired<Pair>("lat");
    expect(validate("", { lon: "", lat: "" })).toBeNull();
    expect(validate("127.0", { lon: "127.0", lat: "37.5" })).toBeNull();
  });
});

describe("ordered", () => {
  type Policy = { min: string; optimal: string; system: string };
  it("오름차순 위반 시 에러", () => {
    const validate = ordered<Policy>(["min", "optimal", "system"]);
    expect(
      validate("", { min: "600", optimal: "300", system: "900" }),
    ).not.toBeNull();
  });
  it("오름차순(동률 허용) + 빈 값 건너뛰기", () => {
    const validate = ordered<Policy>(["min", "optimal", "system"]);
    expect(validate("", { min: "300", optimal: "300", system: "900" })).toBeNull();
    expect(validate("", { min: "300", optimal: "", system: "900" })).toBeNull();
  });
});

describe("dateOrdered", () => {
  type Period = { start: string; end: string };
  it("시작일 > 종료일이면 에러", () => {
    const validate = dateOrdered<Period>("end");
    expect(validate("2026-07-10", { start: "2026-07-10", end: "2026-07-01" })).toBe(
      "시작일은 종료일보다 늦을 수 없습니다.",
    );
  });
  it("한쪽만 있으면 통과", () => {
    const validate = dateOrdered<Period>("end");
    expect(validate("2026-07-10", { start: "2026-07-10", end: "" })).toBeNull();
  });
});

describe("integerString", () => {
  type F = { priority: string };
  it("정수 아닌 값 거부(빈 값은 통과)", () => {
    const validate = integerString<F>();
    expect(validate("abc", { priority: "abc" })).toBe("정수를 입력하세요.");
    expect(validate("1.5", { priority: "1.5" })).toBe("정수를 입력하세요.");
    expect(validate("", { priority: "" })).toBeNull();
    expect(validate("42", { priority: "42" })).toBeNull();
  });
  it("범위 검사", () => {
    const validate = integerString<F>({ min: 0, max: 100 });
    expect(validate("-1", { priority: "-1" })).toBe("0 이상이어야 합니다.");
    expect(validate("101", { priority: "101" })).toBe("100 이하여야 합니다.");
  });
});

describe("parseJsonObjectField", () => {
  it("빈 문자열 → value null(미지정)", () => {
    expect(parseJsonObjectField("")).toEqual({ value: null });
  });
  it("JSON 아님 → 한국어 에러", () => {
    expect(parseJsonObjectField("{oops").error).toBe(
      "올바른 JSON 형식이 아닙니다.",
    );
  });
  it("object 아님(배열/스칼라) → 라벨 포함 에러", () => {
    expect(parseJsonObjectField("[1,2]", "메타데이터").error).toBe(
      "메타데이터은(는) JSON object여야 합니다.",
    );
    expect(parseJsonObjectField("42", "메타데이터").error).toBe(
      "메타데이터은(는) JSON object여야 합니다.",
    );
  });
  it("object → 파싱된 값", () => {
    expect(parseJsonObjectField('{"sido_code": "11"}')).toEqual({
      value: { sido_code: "11" },
    });
  });
});
