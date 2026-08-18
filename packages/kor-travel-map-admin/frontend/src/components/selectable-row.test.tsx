// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import * as React from "react";
import { afterEach, describe, expect, it } from "vitest";

import { SelectableRow, SelectableRowGroup } from "./selectable-row";

afterEach(() => cleanup());

/** 그룹 안 세 행 중 하나가 선택된 목록. `groupRef`는 호출부가 ref를 넘기는 경우를 재현한다. */
function Fixture({ groupRef }: { groupRef?: React.Ref<HTMLDivElement> }) {
  const [selected, setSelected] = React.useState("b");
  return (
    <SelectableRowGroup aria-label="목록" ref={groupRef}>
      {["a", "b", "c"].map((id) => (
        <SelectableRow
          key={id}
          selected={selected === id}
          onSelect={() => setSelected(id)}
        >
          {id}
        </SelectableRow>
      ))}
    </SelectableRowGroup>
  );
}

/** roving tabindex의 관찰 지점 — 탭 순서에 남은 행. 언제나 정확히 하나여야 한다. */
function tabStops(): HTMLElement[] {
  return screen.getAllByRole("option").filter((row) => row.tabIndex === 0);
}

describe("SelectableRowGroup roving tabindex", () => {
  it("leaves exactly one tab stop (the selected row) with no caller ref", () => {
    render(<Fixture />);

    const stops = tabStops();
    expect(stops).toHaveLength(1);
    expect(stops[0].textContent).toBe("b");
  });

  it("keeps the tab stop when the caller passes an object ref", () => {
    // 회귀 가드: ref가 props에 남아 `{...props}`가 내부 containerRef를 덮어쓰면 syncRoving이
    // 조기 반환해 모든 행이 tabIndex=-1이 된다 — 목록 전체가 Tab으로 도달 불가능해진다.
    const groupRef = React.createRef<HTMLDivElement>();
    render(<Fixture groupRef={groupRef} />);

    expect(groupRef.current === screen.getByRole("listbox")).toBe(true);
    const stops = tabStops();
    expect(stops).toHaveLength(1);
    expect(stops[0].textContent).toBe("b");
  });

  it("keeps the tab stop when the caller passes a callback ref", () => {
    const seen: (HTMLDivElement | null)[] = [];
    render(
      <Fixture
        groupRef={(element) => {
          seen.push(element);
        }}
      />,
    );

    expect(seen.at(-1) === screen.getByRole("listbox")).toBe(true);
    expect(tabStops()).toHaveLength(1);
  });

  it("moves focus and the tab stop with ArrowDown while a caller ref is attached", () => {
    const groupRef = React.createRef<HTMLDivElement>();
    render(<Fixture groupRef={groupRef} />);

    const rows = screen.getAllByRole("option");
    rows[1].focus();
    fireEvent.keyDown(rows[1], { key: "ArrowDown" });

    expect(document.activeElement === rows[2]).toBe(true);
    // 탭 스톱은 여전히 하나뿐이다(포커스를 따라 옮겨 가든, 아직 이전 행에 있든 — 옮기는 일은
    // focusin이 하고 그건 브라우저 몫이다). 500행짜리 목록도 Tab 한 번이면 빠져나간다.
    expect(tabStops()).toHaveLength(1);
  });
});
