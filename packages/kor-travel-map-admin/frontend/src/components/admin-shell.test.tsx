// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({ pathname: "/admin/features/dedup-reviews" }));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
}));

import { AdminShell, AdminShellFrame } from "./admin-shell";
import { ShellActionLabel } from "./shell-action-label";

const STORAGE_KEY = "kor-travel-map:sidebar-collapsed";

beforeEach(() => {
  navigation.pathname = "/admin/features/dedup-reviews";
  window.localStorage.clear();
});

afterEach(cleanup);

it("상단 바 h1은 '영역 - 페이지' 한 줄이고 설명은 상단 바에 작게 둔다", () => {
  render(
    <AdminShellFrame>
      <AdminShell description="중복 후보를 검토합니다." title="중복 검토">
        <p>본문</p>
      </AdminShell>
    </AdminShellFrame>,
  );
  const heading = screen.getByRole("heading", { level: 1 });
  expect(heading.textContent).toBe("Feature 관리 - 중복 검토");
  expect(heading.getAttribute("title")).toBe("Feature 관리 - 중복 검토");
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);

  const header = heading.closest('[data-slot="admin-shell-header"]');
  if (!(header instanceof HTMLElement)) throw new Error("상단 바가 없다");
  const description = header.querySelector('[data-slot="admin-shell-description"]');
  expect(description?.textContent).toBe("중복 후보를 검토합니다.");
  // 앱 설명 문구("admin" 등)는 상단 바에 두지 않는다.
  expect(header.textContent).not.toContain("admin");

  const main = screen.getByRole("main");
  expect(main.id).toBe("main-content");
  expect(within(main).getByText("본문")).toBeTruthy();
});

it("section 오버라이드가 nav 유도 영역보다 우선하고, 홈은 '개요'다", () => {
  navigation.pathname = "/";
  const { rerender } = render(
    <AdminShellFrame>
      <AdminShell title="운영 홈">
        <p>홈</p>
      </AdminShell>
    </AdminShellFrame>,
  );
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
    "개요 - 운영 홈",
  );
  rerender(
    <AdminShellFrame>
      <AdminShell section="임시" title="운영 홈">
        <p>홈</p>
      </AdminShell>
    </AdminShellFrame>,
  );
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
    "임시 - 운영 홈",
  );
});

it("help와 actions는 상단 바 동작 영역에, meta는 본문 맨 위 한 줄에 둔다", () => {
  render(
    <AdminShellFrame>
      <AdminShell
        actions={
          <button type="button">
            <svg aria-hidden="true" data-icon="inline-start" />
            <ShellActionLabel>새로고침</ShellActionLabel>
          </button>
        }
        help="도움말 본문"
        meta={<span>저장소 /backups</span>}
        title="백업"
      >
        <p>본문</p>
      </AdminShell>
    </AdminShellFrame>,
  );
  const actions = document.querySelector('[data-slot="admin-shell-actions"]');
  if (!(actions instanceof HTMLElement)) throw new Error("동작 영역이 없다");
  expect(within(actions).getByRole("button", { name: "도움말: 백업" })).toBeTruthy();
  const refresh = within(actions).getByRole("button", { name: "새로고침" });
  // 좁은 폭에서 아이콘만 남기되 접근성 이름은 유지한다.
  expect(
    refresh.querySelector('[data-slot="shell-action-label"]')?.className,
  ).toContain("max-md:sr-only");

  const meta = document.querySelector('[data-slot="admin-shell-meta"]');
  expect(meta?.textContent).toBe("저장소 /backups");
  expect(screen.getByRole("main").contains(meta)).toBe(true);
});

it("nav는 21개 링크이고 현재 경로를 aria-current로 표시한다", () => {
  render(
    <AdminShellFrame>
      <AdminShell title="중복 검토">
        <p>본문</p>
      </AdminShell>
    </AdminShellFrame>,
  );
  const nav = screen.getByTestId("map-common-menu");
  expect(within(nav).getAllByRole("link")).toHaveLength(21);
  const current = within(nav).getByRole("link", { name: "중복 검토" });
  expect(current.getAttribute("aria-current")).toBe("page");
  expect(current.getAttribute("href")).toBe("/admin/features/dedup-reviews");
});

it("rail 접힘은 기존 키와 '1'/'0' 형식을 유지한다", () => {
  window.localStorage.setItem(STORAGE_KEY, "0");
  render(
    <AdminShellFrame>
      <AdminShell title="중복 검토">
        <p>본문</p>
      </AdminShell>
    </AdminShellFrame>,
  );
  fireEvent.click(screen.getByRole("button", { name: "좌측 메뉴 접기" }));
  expect(window.localStorage.getItem(STORAGE_KEY)).toBe("1");
  const rail = document.querySelector('[data-slot="admin-shell-rail"]');
  expect(rail?.getAttribute("data-collapsed")).toBe("true");
  // 접힌 rail에서도 로그아웃은 접근성 이름을 가진 아이콘 버튼으로 남는다.
  expect(
    within(rail as HTMLElement).getByRole("button", { name: "로그아웃" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "좌측 메뉴 펼치기" }));
  expect(window.localStorage.getItem(STORAGE_KEY)).toBe("0");
});

it("모바일 메뉴 버튼은 좌측 drawer를 열고 링크를 누르면 닫는다", () => {
  render(
    <AdminShellFrame>
      <AdminShell title="중복 검토">
        <p>본문</p>
      </AdminShell>
    </AdminShellFrame>,
  );
  const menuButton = document.querySelector(
    '[data-slot="admin-shell-menu-button"]',
  );
  if (!(menuButton instanceof HTMLElement)) throw new Error("메뉴 버튼이 없다");
  expect(menuButton.getAttribute("aria-label")).toBe("메뉴 열기");
  fireEvent.click(menuButton);
  const dialog = screen.getByRole("dialog", { name: "주요 메뉴" });
  expect(dialog.getAttribute("data-slot")).toBe("admin-shell-drawer");
  const link = within(dialog).getByRole("link", { name: "이슈" });
  fireEvent.click(link, { button: 0 });
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("셸은 레이아웃에 한 번 있고 페이지가 바뀌어도 같은 노드로 남는다(제목만 바뀐다)", () => {
  navigation.pathname = "/ops/logs";
  const { rerender } = render(
    <AdminShellFrame>
      <AdminShell title="운영 로그">
        <p>로그</p>
      </AdminShell>
    </AdminShellFrame>,
  );
  const shell = screen.getByTestId("map-admin-shell");
  const main = screen.getByRole("main");
  navigation.pathname = "/ops/consistency";
  rerender(
    <AdminShellFrame>
      <AdminShell key="/ops/consistency" title="정합성 점검">
        <p>정합성</p>
      </AdminShell>
    </AdminShellFrame>,
  );
  expect(screen.getByTestId("map-admin-shell")).toBe(shell);
  expect(screen.getByRole("main")).toBe(main);
  expect(within(main).getByText("정합성")).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
    "모니터링 - 정합성 점검",
  );
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
});

it("로그인 화면은 셸 없이 그린다", () => {
  navigation.pathname = "/login";
  render(
    <AdminShellFrame>
      <p>로그인 폼</p>
    </AdminShellFrame>,
  );
  expect(screen.getByText("로그인 폼")).toBeTruthy();
  expect(screen.queryByTestId("map-admin-shell")).toBeNull();
  expect(screen.queryByRole("main")).toBeNull();
});
