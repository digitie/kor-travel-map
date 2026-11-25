import type { Locator, Page } from "@playwright/test";

import { ADMIN_NAV_GROUPS, type AdminNavHref } from "../../src/lib/admin-nav";

/**
 * live 스펙용 관리자 화면 이름 — 하드코딩 대신 nav 정본(`src/lib/admin-nav.ts`)에서 읽는다.
 *
 * 2026-11-25 운영 e2e에서 `uploads-backups-poi`·`reviews` 실패 60여 건은 코드 회귀가 아니라
 * 화면 이름 drift였다(`Offline uploads`→`오프라인 업로드`, nav `Issues`→`이슈`). 화면 제목은
 * #1534부터 nav 라벨과 같고 상단 바 h1은 "영역 - 페이지"라, nav 정본 라벨 하나로 h1과
 * 사이드바 링크를 모두 찾을 수 있다. 라벨을 바꾸면 스펙이 함께 따라온다.
 */
const NAV_LABELS: ReadonlyMap<string, string> = new Map(
  ADMIN_NAV_GROUPS.flatMap((group) =>
    group.items.map((item) => [item.href, item.label] as const),
  ),
);

/** nav 정본에서 화면 라벨을 꺼낸다. 없는 href는 스펙 쪽 오타이므로 즉시 실패한다. */
export function adminNavLabel(href: AdminNavHref): string {
  const label = NAV_LABELS.get(href);
  if (label === undefined) {
    throw new Error(`admin-nav.ts에 없는 href: ${href}`);
  }
  return label;
}

/**
 * 화면 h1. 상단 바 h1은 "영역 - 페이지"(예: "수집 파이프라인 - 오프라인 업로드")라
 * 접근성 이름의 부분 일치로 찾는다(Playwright 기본 비-exact).
 */
export function adminPageHeading(page: Page, href: AdminNavHref): Locator {
  return page.getByRole("heading", { level: 1, name: adminNavLabel(href) });
}

/** 좌측 "주요 메뉴" 내비게이션의 해당 화면 링크(접근성 이름 정확 일치). */
export function adminNavLink(page: Page, href: AdminNavHref): Locator {
  return page
    .getByRole("navigation", { name: "주요 메뉴" })
    .getByRole("link", { name: adminNavLabel(href), exact: true });
}

/**
 * 공용 pager(`components/pagination-bar.tsx`)의 버튼. 접근성 이름은 `<접두어> 첫 페이지`
 * 또는 `첫 페이지`라 접미 일치로 찾는다 — 화면마다 접두어(dedup 등)가 달라도 같은 계약을 본다.
 */
export function pagerButton(
  scope: Page | Locator,
  label: "첫 페이지" | "이전 페이지" | "다음 페이지" | "마지막 페이지",
): Locator {
  return scope.getByRole("button", { name: new RegExp(`(^|\\s)${label}$`) });
}

/** 공용 pager nav(`pagination`, `<접두어> pagination top|bottom`). */
export function pagerNavs(page: Page): Locator {
  return page.getByRole("navigation", { name: /(^|\s)pagination( top| bottom)?$/ });
}
