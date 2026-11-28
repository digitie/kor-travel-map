import { expect, type Locator, type Page } from "@playwright/test";

import type { AdminNavHref } from "../../src/lib/admin-nav";

/** 운영 화면의 메뉴 링크를 정식 경로로 찾는다. */
export function adminNavLink(page: Page, href: AdminNavHref): Locator {
  return page
    .getByRole("navigation", { name: "주요 메뉴" })
    .locator(`a[href=${JSON.stringify(href)}]`);
}

/** 운영 사이드바의 메뉴 이름, 화면 제목, 페이지 콘텐츠가 함께 표시되는지 확인한다. */
export async function expectAdminPageLoaded(
  page: Page,
  href: AdminNavHref,
  timeout = 15000,
): Promise<void> {
  const link = adminNavLink(page, href).first();
  await expect(link).toBeVisible({ timeout });
  const label = (await link.innerText({ timeout })).trim();
  expect(label).not.toBe("");
  await expect(page.getByRole("heading", { level: 1, name: label })).toBeVisible({ timeout });
  await expect(page.locator('[data-slot="admin-shell-content"]').first()).toBeVisible({ timeout });
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
