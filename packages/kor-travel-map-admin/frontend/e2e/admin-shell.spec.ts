import { expect, test, type Locator, type Page } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

type ProblemDetail = components["schemas"]["ProblemDetail"];

const BACKEND_UNAVAILABLE: ProblemDetail = {
  code: "SERVICE_UNAVAILABLE",
  detail: "mocked backend unavailable",
  request_id: "e2e-admin-shell-backend-unavailable",
  status: 503,
  title: "mocked backend unavailable",
  type: "https://kor-travel-map/errors/service-unavailable",
};

const DESKTOP = { width: 1280, height: 800 } as const;
const MOBILE = { width: 390, height: 844 } as const;

/**
 * 공통 관리자 셸(@kor-travel/ui 0.2.3 `AdminShell`) 채택 계약.
 * - 맨 위는 한 줄 상단 바: h1 = "영역 - 페이지", 페이지 설명은 같은 줄에 작게(앱 설명 없음).
 * - lg 미만은 상단 바 메뉴 버튼 → 좌측 drawer. 메뉴 이동 시 닫힌다.
 * - 버튼 테두리(FS-7.8): 쉴 때 outline 없음, Tab 포커스 때 2px outline 하나, 누를 때 테두리 불변.
 * 이 계약은 backend 상태와 무관하므로 모든 BFF REST를 503으로 막고 셸만 본다.
 */
test.describe("admin shell (공통 AdminShell 0.2.3)", () => {
  test.beforeEach(async ({ page }) => {
    await installInertOpsLiveWebSocket(page);
    await page.route("**/api/proxy/**", async (route) => {
      const request = route.request();
      if (request.method() !== "GET") {
        throw new Error(
          `admin shell spec에서 예상하지 않은 BFF 요청: ${request.method()} ${bffApiPath(request.url())}`,
        );
      }
      await route.fulfill({
        body: JSON.stringify(BACKEND_UNAVAILABLE),
        contentType: "application/problem+json",
        status: 503,
      });
    });
  });

  for (const viewport of [
    { name: "desktop", ...DESKTOP },
    { name: "mobile", ...MOBILE },
  ] as const) {
    test(`${viewport.name}: 상단 바는 '영역 - 페이지' 한 줄 + 작은 설명`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto("/ops/logs");

      const header = page.locator('[data-slot="admin-shell-header"]');
      const heading = header.getByRole("heading", { level: 1 });
      await expect(heading).toHaveText("모니터링 - 운영 로그");
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      await expect(heading).toHaveAttribute("title", "모니터링 - 운영 로그");

      // 한 줄: 상단 바 높이는 48px 안팎이고 제목은 줄바꿈하지 않는다.
      const headerBox = await header.boundingBox();
      expect(headerBox?.height).toBeLessThanOrEqual(56);
      const lineHeight = await heading.evaluate((element) =>
        Number.parseFloat(window.getComputedStyle(element).lineHeight),
      );
      const headingBox = await heading.boundingBox();
      expect(headingBox?.height).toBeLessThanOrEqual(lineHeight + 1);

      // 페이지 설명은 같은 상단 바 안에서 제목보다 작은 글씨다.
      const description = header.locator('[data-slot="admin-shell-description"]');
      await expect(description).toHaveAttribute(
        "title",
        "시스템 로그와 API 호출 로그를 조회합니다.",
      );
      const [titleSize, descriptionSize] = await Promise.all(
        [heading, description].map((locator) =>
          locator.evaluate((element) =>
            Number.parseFloat(window.getComputedStyle(element).fontSize),
          ),
        ),
      );
      expect(descriptionSize).toBeLessThan(titleSize);
      // 앱 설명 문구(예전 rail 워드마크 옆 "admin")는 어디에도 없다.
      await expect(page.getByText("admin", { exact: true })).toHaveCount(0);

      await expect(page).toHaveTitle("모니터링 - 운영 로그 | kor-travel-map");
      const documentWidth = await page.evaluate(
        () => document.documentElement.scrollWidth,
      );
      expect(documentWidth).toBeLessThanOrEqual(viewport.width);
    });
  }

  test("desktop: 좌측 rail이 보이고 모바일 메뉴 버튼은 숨는다", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/ops/logs");
    const rail = page.locator('[data-slot="admin-shell-rail"]');
    await expect(rail).toBeVisible();
    await expect(
      rail.getByRole("navigation", { name: "주요 메뉴" }).getByRole("link"),
    ).toHaveCount(21);
    await expect(page.locator('[data-slot="admin-shell-menu-button"]')).toBeHidden();
    const railBox = await rail.boundingBox();
    expect(railBox?.x).toBe(0);
  });

  test("mobile: 메뉴 버튼이 좌측 drawer를 열고, 이동하면 닫힌다", async ({ page }) => {
    await page.setViewportSize(MOBILE);
    await page.goto("/ops/logs");

    // 닫힌 상태: rail도 메뉴 목록도 화면에 없다(상단을 메뉴가 차지하지 않는다).
    await expect(page.locator('[data-slot="admin-shell-rail"]')).toBeHidden();
    await expect(page.getByRole("navigation", { name: "주요 메뉴" })).toHaveCount(0);
    const headerBox = await page
      .locator('[data-slot="admin-shell-header"]')
      .boundingBox();
    const mainBox = await page.getByRole("main").boundingBox();
    expect(headerBox?.y).toBe(0);
    expect(mainBox?.y).toBeLessThanOrEqual((headerBox?.height ?? 0) + 1);

    const menuButton = page.locator('[data-slot="admin-shell-menu-button"]');
    await expect(menuButton).toHaveAttribute("aria-label", "메뉴 열기");
    await menuButton.click();

    const drawer = page.getByRole("dialog", { name: "주요 메뉴" });
    await expect(drawer).toBeVisible();
    const drawerBox = await drawer.boundingBox();
    expect(drawerBox?.x).toBe(0);
    expect(drawerBox?.width).toBeLessThanOrEqual(280);
    const menu = drawer.getByRole("navigation", { name: "주요 메뉴" });
    await expect(menu.getByRole("link")).toHaveCount(21);
    await expect(menu.getByRole("link", { name: "운영 로그" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // drawer에도 로그아웃이 있다(예전 상단 행 아이콘 대체).
    await expect(drawer.getByRole("button", { name: "로그아웃" })).toBeVisible();

    // 닫기 버튼으로 닫힌다.
    await drawer.getByRole("button", { name: "메뉴 닫기" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // 다시 열고 메뉴 항목으로 이동하면 닫힌 채 새 페이지가 뜬다.
    await menuButton.click();
    await expect(drawer).toBeVisible();
    await drawer.getByRole("link", { name: "정합성 점검", exact: true }).click();
    await expect(page).toHaveURL(/\/ops\/consistency$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "모니터링 - 정합성 점검",
    );
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  for (const viewport of [
    { name: "desktop", ...DESKTOP },
    { name: "mobile", ...MOBILE },
  ] as const) {
    test(`${viewport.name}: 버튼 outline은 쉴 때 없고 Tab 포커스 때 2px 하나, 누를 때 테두리 불변`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto("/ops/logs");
      const refresh = page
        .locator('[data-slot="admin-shell-actions"]')
        .getByRole("button", { name: "새로고침" });
      await expect(refresh).toBeVisible();

      // 쉴 때: 페이지의 모든 공통 Button에 상시 outline이 없다(예전 `outline-solid`가
      // 기본 폭 medium=3px outline을 모든 버튼에 그렸다).
      const restingOutlines = await page
        .locator('[data-slot="button"]')
        .evaluateAll((buttons) =>
          buttons
            .filter((button) => button.checkVisibility())
            .map((button) => window.getComputedStyle(button).outlineStyle),
        );
      expect(restingOutlines.length).toBeGreaterThan(0);
      expect(new Set(restingOutlines)).toEqual(new Set(["none"]));
      const rest = await focusStyle(refresh);

      // Tab 포커스: outline 2px solid 하나, offset 2px, ring(box-shadow)·테두리 변화 없음.
      await tabUntilFocused(page, refresh);
      const focused = await focusStyle(refresh);
      expect(focused.focusVisible).toBe(true);
      expect(focused.outlineStyle).toBe("solid");
      expect(focused.outlineWidth).toBe("2px");
      expect(focused.outlineOffset).toBe("2px");
      expect(focused.boxShadow).toBe(rest.boxShadow);
      expect(focused.borderWidth).toBe(rest.borderWidth);
      expect(focused.borderColor).toBe(rest.borderColor);

      // 포인터로 누르는 동안: 포커스 링이 생기지 않고 테두리 폭도 그대로다.
      // 비대화 요소(제목)를 눌러 마지막 입력을 포인터로 바꾼다(로그아웃 등 동작 버튼을 피한다).
      await page.locator('[data-slot="admin-shell-title"]').click();
      const box = await refresh.boundingBox();
      if (!box) throw new Error("새로고침 버튼 위치를 잴 수 없다");
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      const pressed = await focusStyle(refresh);
      await page.mouse.up();
      expect(pressed.focusVisible).toBe(false);
      expect(pressed.outlineStyle).toBe("none");
      expect(pressed.borderWidth).toBe(rest.borderWidth);
      expect(pressed.boxShadow).toBe(rest.boxShadow);
      const pressedBox = await refresh.boundingBox();
      expect(Math.abs((pressedBox?.height ?? 0) - box.height)).toBeLessThanOrEqual(1);
    });
  }

  test("mobile: 상단 바 동작은 아이콘 버튼이고 접근성 이름은 유지한다", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE);
    await page.goto("/ops/logs");
    const refresh = page
      .locator('[data-slot="admin-shell-actions"]')
      .getByRole("button", { name: "새로고침" });
    await expect(refresh).toBeVisible();
    const box = await refresh.boundingBox();
    // 라벨이 시각적으로 숨어 아이콘 폭만 남는다(텍스트 버튼이면 64px를 넘는다).
    expect(box?.width).toBeLessThanOrEqual(44);
  });
});

async function tabUntilFocused(page: Page, target: Locator) {
  for (let step = 0; step < 80; step += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => element === document.activeElement)) {
      return;
    }
  }
  throw new Error("Tab으로 대상 버튼에 도달하지 못했다");
}

function focusStyle(target: Locator) {
  return target.evaluate((element) => {
    const style = window.getComputedStyle(element);
    return {
      focusVisible: element.matches(":focus-visible"),
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      outlineOffset: style.outlineOffset,
      boxShadow: style.boxShadow,
      borderWidth: style.borderTopWidth,
      borderColor: style.borderTopColor,
    };
  });
}
