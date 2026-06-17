// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FormField } from "./form-field-input";
import { FormSelect } from "./form-select";
import { FormTextArea } from "./form-textarea";
import { NativeSelectOption } from "./native-select-option";

afterEach(() => cleanup());

/**
 * required 필드는 라벨에 장식용 별표(`<span aria-hidden> *</span>`)를 붙이는데, Chromium
 * accname이 그 별표를 접근성 이름에 포함시켜 `"name *"`가 되어 `getByLabel(name,{exact})`가
 * 미스됐다(라이브 e2e features-new.spec 적색). 컨트롤에 명시 aria-label을 부여해 접근성
 * 이름을 별표 없는 라벨로 고정한다. 본 테스트는 그 aria-label 배선을 결정적으로 가드한다.
 */
describe("required field accessible name (aria-label override)", () => {
  it("FormField(required) gives the input a clean aria-label = label", () => {
    render(<FormField label="name" required value="" onChange={() => {}} />);
    const input = screen.getByRole("textbox");
    expect(input.getAttribute("aria-label")).toBe("name");
    expect(input.getAttribute("aria-required")).toBe("true");
  });

  it("FormField(non-required) sets no aria-label (label alone names it)", () => {
    render(<FormField label="memo" value="" onChange={() => {}} />);
    expect(screen.getByRole("textbox").getAttribute("aria-label")).toBeNull();
  });

  it("caller-provided aria-label overrides the required default", () => {
    render(
      <FormField label="name" required aria-label="이름" value="" onChange={() => {}} />,
    );
    expect(screen.getByRole("textbox").getAttribute("aria-label")).toBe("이름");
  });

  it("FormSelect(required) gives the select a clean aria-label = label", () => {
    render(
      <FormSelect label="kind" required value="place" onChange={() => {}}>
        <NativeSelectOption value="place">place</NativeSelectOption>
      </FormSelect>,
    );
    expect(screen.getByRole("combobox").getAttribute("aria-label")).toBe("kind");
  });

  it("FormTextArea(required) gives the textarea a clean aria-label = label", () => {
    render(<FormTextArea label="reason" required value="" onChange={() => {}} />);
    expect(screen.getByRole("textbox").getAttribute("aria-label")).toBe("reason");
  });
});
