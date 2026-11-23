// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { Badge } from "./badge";
import { Checkbox } from "./checkbox";
import { Input } from "./input";
import { NativeSelect } from "./native-select";
import { NativeSelectOption } from "./native-select-option";

afterEach(cleanup);

const SINGLE_OUTLINE = [
  "focus-visible:outline-2",
  "focus-visible:outline-kt-focus",
  "focus-visible:outline-offset-2",
];

/** focus 관련 클래스만 — ring·테두리 색·outline-none이 다시 끼어들면 목록이 달라진다. */
function focusTokens(element: Element): string[] {
  return element.className
    .split(/\s+/)
    .filter((token) => /focus|outline-none/.test(token))
    .sort();
}

it("입력·선택·체크박스·배지 focus는 공통 0.2.5의 단일 outline 2px·offset 2px뿐이다(FS-7.8)", () => {
  render(
    <>
      <Input aria-label="입력" />
      <NativeSelect aria-label="선택">
        <NativeSelectOption value="a">가</NativeSelectOption>
      </NativeSelect>
      <Checkbox aria-label="체크" />
      <Badge asChild>
        <a href="#x">배지</a>
      </Badge>
    </>,
  );
  for (const element of [
    screen.getByRole("textbox", { name: "입력" }),
    screen.getByRole("combobox", { name: "선택" }),
    screen.getByRole("checkbox", { name: "체크" }),
    screen.getByRole("link", { name: "배지" }),
  ]) {
    expect(focusTokens(element), element.tagName).toEqual(SINGLE_OUTLINE);
  }
});

it("체크박스는 md 미만에서 터치 영역을 44px 이상으로 넓힌다(14px + 2×15px)", () => {
  render(<Checkbox aria-label="체크" />);
  const tokens = screen.getByRole("checkbox", { name: "체크" }).className.split(/\s+/);
  expect(tokens).toContain("max-md:after:-inset-[15px]");
});
