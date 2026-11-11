// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Button as CommonButton } from "@kor-travel/ui/button";
import { buttonVariants as commonButtonVariants } from "@kor-travel/ui/button-variants";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { Button } from "./button";
import { buttonVariants } from "./button-variants";

afterEach(cleanup);

function attributes(markup: string) {
  const document = new DOMParser().parseFromString(markup, "text/html");
  const button = document.querySelector("button");
  if (!button) throw new Error("버튼 root가 없다");
  return button;
}

it.each(["ghost", "link", "outline"] as const)(
  "%s/icon-xs를 공통 Button의 variant·size 계약으로 전달한다",
  (variant) => {
    const common = attributes(renderToStaticMarkup(
      <CommonButton variant={variant} size="icon-xs">동작</CommonButton>,
    ));
    const local = attributes(renderToStaticMarkup(
      <Button variant={variant} size="icon-xs">동작</Button>,
    ));
    expect(common.dataset.variant).toBe(variant);
    expect(common.dataset.size).toBe("icon-xs");
    expect(local.dataset.variant).toBe(common.dataset.variant);
    expect(local.dataset.size).toBe(common.dataset.size);
  },
);

it.each(["ghost", "link"] as const)("%s에 default 채움이 새지 않는다", (variant) => {
  const local = attributes(renderToStaticMarkup(<Button variant={variant}>동작</Button>));
  expect(local.classList.contains("bg-primary")).toBe(false);
});

it("Link용 recipe도 공통 icon-xs 크기를 사용한다", () => {
  const expectedSize = commonButtonVariants({ variant: "ghost", size: "icon-xs" })
    .split(" ").find((token) => /^size-[0-9]+$/.test(token));
  expect(expectedSize).toBeTruthy();
  expect(buttonVariants({ variant: "ghost", size: "icon-xs" }).split(" "))
    .toContain(expectedSize);
});

it("loading 전환은 root·라벨·포커스·접근성 이름을 유지하고 활성화를 막는다", () => {
  const onClick = vi.fn();
  const { rerender } = render(<Button onClick={onClick}>저장</Button>);
  const button = screen.getByRole("button", { name: "저장" });
  const label = button.querySelector('[data-slot="button-label"]');
  button.focus();
  rerender(<Button loading disabled onClick={onClick}>저장</Button>);
  expect(screen.getByRole("button", { name: "저장" })).toBe(button);
  expect(button.querySelector('[data-slot="button-label"]')).toBe(label);
  expect(document.activeElement).toBe(button);
  expect(button.hasAttribute("disabled")).toBe(false);
  expect(button.getAttribute("aria-disabled")).toBe("true");
  expect(button.getAttribute("aria-busy")).toBe("true");
  expect(button.classList.contains("disabled:opacity-50")).toBe(false);
  expect(fireEvent.click(button)).toBe(false);
  expect(onClick).not.toHaveBeenCalled();
  rerender(<Button onClick={onClick}>저장</Button>);
  expect(document.activeElement).toBe(button);
  fireEvent.click(button);
  expect(onClick).toHaveBeenCalledOnce();
});

it("실제 disabled와 설명은 loading 상태와 분리해 보존한다", () => {
  render(<Button disabled disabledReason="선택 필요">적용</Button>);
  const button = screen.getByRole("button", { name: "적용" });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(button.getAttribute("title")).toBe("선택 필요");
});
