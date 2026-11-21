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

const BUTTON_VARIANTS = [
  "default",
  "outline",
  "secondary",
  "ghost",
  "destructive",
  "destructive-solid",
  "link",
] as const;

it.each(BUTTON_VARIANTS)(
  "%s: focus outline은 공통 recipe의 한 벌뿐이고 상시 outline·ring 덧대기가 없다(FS-7.8)",
  (variant) => {
    for (const tokens of [
      buttonVariants({ variant }).split(" "),
      attributes(
        renderToStaticMarkup(<Button variant={variant}>동작</Button>),
      ).className.split(" "),
    ]) {
      // 조건 없는 outline-style은 모든 버튼에 medium(3px) 테두리를 상시로 그렸다.
      expect(tokens.filter((token) => /^outline-(solid|dashed|double|dotted|\d)/.test(token)))
        .toEqual([]);
      expect(tokens.filter((token) => token.startsWith("focus-visible:outline")).toSorted())
        .toEqual([
          "focus-visible:outline-2",
          "focus-visible:outline-kt-focus",
          "focus-visible:outline-offset-2",
        ]);
      expect(tokens.some((token) => /^focus-visible:(ring|border)/.test(token))).toBe(false);
      expect(tokens).not.toContain("outline-none");
    }
  },
);

it.each(["icon", "icon-sm", "icon-xs", "icon-lg"] as const)(
  "%s: 모바일(md 미만)에서만 터치 표적 하한 44px(min-size)을 건다",
  (size) => {
    for (const tokens of [
      buttonVariants({ variant: "ghost", size }).split(" "),
      attributes(
        renderToStaticMarkup(
          <Button aria-label="닫기" size={size} variant="ghost">
            x
          </Button>,
        ),
      ).className.split(" "),
    ]) {
      expect(tokens).toContain("max-md:min-h-11");
      expect(tokens).toContain("max-md:min-w-11");
      // 데스크톱 밀도(공통 recipe의 size-*)는 그대로 남는다.
      expect(tokens.some((token) => /^size-\d+$/.test(token))).toBe(true);
      expect(tokens.some((token) => /^(min-h|min-w)-/.test(token))).toBe(false);
    }
  },
);

it("텍스트 버튼에는 모바일 min-size를 덧대지 않는다", () => {
  const tokens = attributes(
    renderToStaticMarkup(<Button size="sm">저장</Button>),
  ).className.split(" ");
  expect(tokens).not.toContain("max-md:min-h-11");
});

it("focusableWhenDisabled: 사유가 있으면 포커스 가능한 aria-disabled + 설명 + tooltip", async () => {
  const onClick = vi.fn();
  render(
    <Button
      disabled
      disabledReason="큐 sensor 확인 필요"
      focusableWhenDisabled
      onClick={onClick}
    >
      요청 생성
    </Button>,
  );
  const button = screen.getByRole("button", { name: "요청 생성" });
  expect(button.hasAttribute("disabled")).toBe(false);
  expect(button.getAttribute("aria-disabled")).toBe("true");
  // title(네이티브 tooltip)과 Radix tooltip이 겹치지 않는다.
  expect(button.hasAttribute("title")).toBe(false);
  // 접근성 설명은 상시(tooltip이 닫혀 있어도) 사유를 가리킨다.
  const describedBy = button.getAttribute("aria-describedby");
  expect(describedBy).toBeTruthy();
  expect(document.getElementById(describedBy ?? "")?.textContent).toBe(
    "큐 sensor 확인 필요",
  );
  // 활성화는 막힌다(클릭·폼 제출 모두 preventDefault).
  expect(fireEvent.click(button)).toBe(false);
  expect(onClick).not.toHaveBeenCalled();
  // 키보드 포커스로 닿고, 포커스 때 tooltip이 사유를 보여 준다.
  button.focus();
  expect(document.activeElement).toBe(button);
  expect(
    await screen.findByRole("tooltip", { name: "큐 sensor 확인 필요" }),
  ).toBeTruthy();
});

it("focusableWhenDisabled: 사유가 없거나 활성이면 기존 동작 그대로", () => {
  const { rerender } = render(
    <Button disabled focusableWhenDisabled>
      적용
    </Button>,
  );
  const button = screen.getByRole("button", { name: "적용" });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(button.hasAttribute("aria-describedby")).toBe(false);
  rerender(
    <Button disabledReason="선택 필요" focusableWhenDisabled>
      적용
    </Button>,
  );
  expect(button.hasAttribute("disabled")).toBe(false);
  expect(button.hasAttribute("aria-disabled")).toBe(false);
  expect(button.hasAttribute("aria-describedby")).toBe(false);
  expect(document.querySelector('[data-slot="button-disabled-reason"]')).toBeNull();
});
