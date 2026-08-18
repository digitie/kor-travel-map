"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * SelectableRow — 목록에서 하나를 고르는 행의 유일한 idiom(m7). 테두리 없는 행: hover는 배경만,
 * 선택은 `bg-brand-tint` + 좌측 2px brand 마크(색 1채널이 아니게 형태를 더한다), 키보드는 option처럼
 * (Enter/Space 선택, 그룹 안에서 ↑/↓·Home/End 이동). 안쪽 버튼/링크는 stopPropagation 한다.
 *
 *   <SelectableRowGroup aria-label="컬렉션">
 *     <SelectableRow selected={id === current} onSelect={() => setCurrent(id)}>…</SelectableRow>
 *   </SelectableRowGroup>
 *
 * 그룹 안에서는 **roving tabindex**다 — 탭 순서에 들어오는 행은 언제나 하나(포커스가 그룹 안에
 * 있으면 그 행, 아니면 선택 행, 그것도 없으면 첫 행). 500행 목록도 Tab 한 번이면 빠져나간다
 * (WAI-ARIA listbox 규약). 그룹 밖에서 단독으로 쓰면 예전처럼 각 행이 탭 순서에 들어온다.
 */

/** 그룹이 tabIndex를 관리 중인지. 값이 상수(`true`)라 rerender를 만들지 않는다. */
const SelectableRowManagedContext = React.createContext(false);

type SelectableRowProps = Omit<
  React.ComponentProps<"div">,
  "role" | "onSelect" | "aria-selected" | "aria-disabled"
> & {
  selected: boolean;
  onSelect: () => void;
  /** 선택 불가 — 사유(`disabledReason`)를 inline note + title로 함께 보여 준다. */
  disabled?: boolean;
  disabledReason?: string;
  /** 우측 정렬 보조 슬롯(배지/카운트). */
  trailing?: React.ReactNode;
  /** 밀도. */
  size?: "default" | "sm";
};

function SelectableRow({
  selected,
  onSelect,
  disabled = false,
  disabledReason,
  trailing,
  size = "default",
  className,
  children,
  onClick,
  onKeyDown,
  title,
  ...props
}: SelectableRowProps) {
  // 그룹 안이면 초깃값은 -1이고 그룹이 한 행만 0으로 승격한다(아래 `syncRoving`).
  // 이 prop 값은 이후 바뀌지 않으므로 React가 속성을 다시 쓰지 않고, 승격이 유지된다.
  const managed = React.use(SelectableRowManagedContext);
  const activate = () => {
    if (disabled) return;
    onSelect();
  };
  return (
    <div
      aria-disabled={disabled || undefined}
      aria-selected={selected}
      className={cn(
        // 전환 대상은 열거한다(design.md §금지 패턴 1) — v4의 축약 전환 유틸은 전환 목록에
        // `outline-color`까지 넣어 포커스 링이 100ms에 걸쳐 스며든다(§Focus: 링은 즉시).
        "group/row relative flex w-full cursor-pointer items-start gap-3 rounded-control text-left text-sm text-text-primary transition-[color,background-color] select-none",
        size === "default" ? "px-3 py-2" : "px-2 py-1.5",
        "hover:bg-surface-subtle focus-visible:bg-surface-subtle focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus active:bg-surface-muted",
        "aria-selected:bg-brand-tint aria-selected:hover:bg-brand-tint aria-selected:focus-visible:bg-brand-tint aria-selected:before:absolute aria-selected:before:inset-y-2 aria-selected:before:left-0 aria-selected:before:w-0.5 aria-selected:before:rounded-full aria-selected:before:bg-brand aria-selected:before:content-['']",
        // P2-7: opacity는 컨트롤 본체(아래 content/trailing)에만 건다 — 사유 텍스트까지 흐려지면
        // "왜 못 고르는지"가 가장 읽기 어려운 글자가 된다.
        "aria-disabled:cursor-not-allowed aria-disabled:hover:bg-transparent",
        className,
      )}
      data-slot="selectable-row"
      data-state={selected ? "selected" : undefined}
      role="option"
      tabIndex={disabled || managed ? -1 : 0}
      title={disabled && disabledReason ? disabledReason : title}
      onClick={(event) => {
        onClick?.(event);
        if (event.defaultPrevented) return;
        activate();
      }}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (event.defaultPrevented) return;
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      }}
      {...props}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex min-w-0 flex-col gap-0.5 group-aria-disabled/row:opacity-55">
          {children}
        </div>
        {/* disabled 사유는 정상 잉크 — 흐려진 글자로 이유를 설명할 수는 없다(design.md §States). */}
        {disabled && disabledReason ? (
          <span className="text-2xs text-text-secondary">{disabledReason}</span>
        ) : null}
      </div>
      {trailing ? (
        <div className="flex shrink-0 items-center gap-1 self-center text-xs text-text-secondary group-aria-disabled/row:opacity-55">
          {trailing}
        </div>
      ) : null}
    </div>
  );
}

/** 행의 1차 텍스트(이름) — 500 ink, 한 줄 말줄임. */
function SelectableRowTitle({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn("truncate font-medium text-text-primary", className)}
      data-slot="selectable-row-title"
      {...props}
    />
  );
}

/** 행의 2차 텍스트(식별자·요약) — 13.5px secondary. 식별자면 `font-mono`를 더한다. */
function SelectableRowDescription({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn("truncate text-xs text-text-secondary", className)}
      data-slot="selectable-row-description"
      {...props}
    />
  );
}

type SelectableRowGroupProps = Omit<React.ComponentProps<"div">, "role"> & {
  /** 행 사이 hairline. */
  divided?: boolean;
};

const ROW_SELECTOR = '[role="option"]';
const OPTION_SELECTOR = '[role="option"]:not([aria-disabled="true"])';

/**
 * listbox 컨테이너 — ↑/↓·Home/End로 행 사이 포커스를 옮기고(roving), 탭 순서에는 한 행만 남긴다.
 * `aria-label` 또는 `aria-labelledby`를 반드시 준다.
 */
function SelectableRowGroup({
  divided = false,
  className,
  onKeyDown,
  onFocusCapture,
  ref,
  ...props
}: SelectableRowGroupProps) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  /**
   * 호출부 ref와 내부 `containerRef`를 함께 채운다. ref를 props에 남겨 두면 `{...props}`가
   * `ref={containerRef}`를 **덮어써** `containerRef.current`가 영원히 null이 되고, 그러면
   * `syncRoving`이 조기 반환해 모든 행이 `tabIndex=-1`로 남는다 — 목록 전체가 Tab으로 도달
   * 불가능해진다(지금은 두 호출부가 ref를 안 넘겨 잠복해 있을 뿐이다). 그래서 ref는 떼어서
   * 여기서 합친다.
   */
  const setContainer = React.useCallback(
    (node: HTMLDivElement | null) => {
      containerRef.current = node;
      if (typeof ref === "function") {
        ref(node);
        return;
      }
      if (ref && typeof ref === "object") ref.current = node;
    },
    [ref],
  );

  /**
   * 탭 순서에 남길 한 행을 고른다: 포커스가 그룹 안에 있으면 그 행, 없으면 선택 행,
   * 그것도 없으면 첫 행. state가 아니라 DOM 속성만 만지므로 렌더 캐스케이드(그리고
   * `react-hooks/set-state-in-effect`)가 없다.
   */
  const syncRoving = React.useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const rows = Array.from(container.querySelectorAll<HTMLElement>(ROW_SELECTOR));
    const options = rows.filter(
      (row) => row.getAttribute("aria-disabled") !== "true",
    );
    const active =
      options.find((option) => option === document.activeElement) ??
      options.find((option) => option.getAttribute("aria-selected") === "true") ??
      options[0];
    for (const row of rows) {
      row.tabIndex = row === active ? 0 : -1;
    }
  }, []);

  // 행이 늘거나 줄거나 선택이 바뀔 때마다(= 그룹이 다시 그려질 때마다) 탭 스톱을 다시 고른다.
  // 페이지가 갈려 활성 행이 사라져도 목록에 Tab으로 들어갈 수 있어야 하기 때문이다.
  React.useEffect(() => {
    syncRoving();
  });

  return (
    <SelectableRowManagedContext value={true}>
      <div
        className={cn("flex flex-col", divided && "divide-y divide-border", className)}
        data-slot="selectable-row-group"
        ref={setContainer}
        role="listbox"
        onFocusCapture={(event) => {
          onFocusCapture?.(event);
          syncRoving();
        }}
        onKeyDown={(event) => {
          onKeyDown?.(event);
          if (event.defaultPrevented) return;
          const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
          if (!keys.includes(event.key)) return;
          const options = Array.from(
            event.currentTarget.querySelectorAll<HTMLElement>(OPTION_SELECTOR),
          );
          if (options.length === 0) return;
          const current = options.indexOf(document.activeElement as HTMLElement);
          let next = current;
          if (event.key === "ArrowDown")
            next = current < 0 ? 0 : Math.min(current + 1, options.length - 1);
          if (event.key === "ArrowUp")
            next = current < 0 ? 0 : Math.max(current - 1, 0);
          if (event.key === "Home") next = 0;
          if (event.key === "End") next = options.length - 1;
          if (next === current) return;
          event.preventDefault();
          // 포커스를 옮기면 onFocusCapture가 이어서 tabIndex도 함께 옮긴다.
          options[next]?.focus();
        }}
        {...props}
      />
    </SelectableRowManagedContext>
  );
}

export { SelectableRow, SelectableRowDescription, SelectableRowGroup, SelectableRowTitle };
export type { SelectableRowGroupProps, SelectableRowProps };
