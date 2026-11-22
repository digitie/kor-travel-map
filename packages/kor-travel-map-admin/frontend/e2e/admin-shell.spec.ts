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

  // 서버 렌더 첫 화면의 상단 바는 nav 정본의 영역·라벨이고, hydration 뒤에는 페이지가
  // `AdminPageTitle`로 등록한 제목이다. 둘이 다르면 첫 화면에서 제목이 한 번 바뀐다(깜빡임).
  // nav 라벨 = 페이지 제목으로 맞춘 네 화면을 SSR HTML과 hydration 뒤 DOM 양쪽에서 고정한다.
  for (const [route, title] of [
    ["/", "개요 - 운영 홈"],
    ["/admin/manual-provider-dedup", "Feature 관리 - 수동/provider 중복 판정"],
    ["/admin/curations/candidates", "Feature 관리 - 큐레이션 후보 검토"],
    ["/ops/cache-target-streams", "수집 파이프라인 - 캐시 전파 스트림"],
  ] as const) {
    test(`SSR 상단 바 제목 = hydration 뒤 제목: ${route}`, async ({ page }) => {
      const response = await page.request.get(route);
      expect(response.status()).toBe(200);
      expect(ssrHeadings(await response.text())).toEqual([title]);

      // 파서가 넣은 SSR h1부터 hydration 뒤 h1까지 상단 바 제목이 거친 모든 값을 기록한다.
      await page.addInitScript(() => {
        const seen: string[] = [];
        (window as unknown as { __h1Titles: string[] }).__h1Titles = seen;
        const record = () => {
          for (const heading of document.querySelectorAll("h1")) {
            const text = heading.textContent?.trim() ?? "";
            if (text && seen.at(-1) !== text) seen.push(text);
          }
        };
        new MutationObserver(record).observe(document, {
          characterData: true,
          childList: true,
          subtree: true,
        });
      });
      await page.goto(route);
      const heading = page.getByRole("heading", { level: 1 });
      await expect(heading).toHaveText(title);
      await expect(page).toHaveTitle(`${title} | kor-travel-map`);
      await waitForAnimations(page);
      expect(
        await page.evaluate(
          () => (window as unknown as { __h1Titles: string[] }).__h1Titles,
        ),
      ).toEqual([title]);
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
    // drawer는 slide-in-from-left 애니메이션으로 들어온다. 열린 직후 boundingBox는 이동 중인
    // translateX를 재므로(x<0) 애니메이션이 끝나 자리를 잡을 때까지 기다린 뒤 잰다.
    await expect(drawer).toHaveAttribute("data-state", "open");
    await drawer.evaluate((element) =>
      Promise.all(
        element.getAnimations().map((animation) =>
          animation.finished.catch(() => undefined),
        ),
      ),
    );
    await expect.poll(async () => (await drawer.boundingBox())?.x).toBe(0);
    const drawerBox = await drawer.boundingBox();
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

  // drawer 메뉴로 이동하면 포커스는 새 화면의 본문(#main-content)에 남아야 한다. 셸이 페이지마다
  // 다시 마운트되면 공통 셸이 옛 본문에 포커스를 돌려준 직후 그 노드가 사라져 BODY로 떨어진다
  // (n150 prod 390px 실측). 셸은 레이아웃에 한 번만 두고 navigationKey로 이동을 알린다.
  for (const activation of ["click", "Enter"] as const) {
    test(`mobile: drawer 메뉴 이동(${activation}) 뒤 포커스는 본문(#main-content)이다`, async ({
      page,
    }) => {
      await page.setViewportSize(MOBILE);
      await page.goto("/ops/logs");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        "모니터링 - 운영 로그",
      );
      const shellBefore = await page
        .locator('[data-slot="admin-shell"]')
        .elementHandle();

      await page.locator('[data-slot="admin-shell-menu-button"]').click();
      const drawer = page.getByRole("dialog", { name: "주요 메뉴" });
      await expect(drawer).toHaveAttribute("data-state", "open");
      await waitForAnimations(page);

      const link = drawer.getByRole("link", { name: "정합성 점검", exact: true });
      if (activation === "click") {
        await link.click();
      } else {
        await link.focus();
        await page.keyboard.press("Enter");
      }
      await expect(page).toHaveURL(/\/ops\/consistency$/);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        "모니터링 - 정합성 점검",
      );
      // drawer 닫힘 애니메이션과 그 뒤 포커스 복귀가 모두 끝난 다음에 본다.
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await waitForAnimations(page);

      await expect
        .poll(() =>
          page.evaluate(() => {
            const active = document.activeElement;
            return active?.isConnected ? active.id || active.tagName : null;
          }),
        )
        .toBe("main-content");
      await expect(page.locator("#main-content")).toBeFocused();
      // 셸은 이동 사이에 같은 DOM 노드로 남는다(다시 마운트되지 않는다).
      expect(
        await shellBefore?.evaluate((element) => element.isConnected),
      ).toBe(true);
    });
  }

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
        .locator('button, a[href], [role="tab"]')
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

      // 탭 트리거도 버튼과 같은 단일 outline이다(공통 0.2.4 tabs recipe 그대로 — Map wrapper의
      // 0.2.3용 focus 덧대기는 지웠다). ring·테두리 색 변화가 없어야 한다.
      // Radix Tabs는 roving tabindex라 선택된 탭만 Tab으로 닿는다.
      const tab = page.getByRole("tab", { selected: true }).first();
      await expect(tab).toBeVisible();
      const tabRest = await focusStyle(tab);
      await tabUntilFocused(page, tab);
      const tabFocused = await focusStyle(tab);
      expect(tabFocused.focusVisible).toBe(true);
      expect(tabFocused.outlineStyle).toBe("solid");
      expect(tabFocused.outlineWidth).toBe("2px");
      expect(tabFocused.outlineOffset).toBe("2px");
      // "spread가 양수인 그림자(= 보이는 ring)가 새로 생기지 않았다"를 본다.
      expect(spreadRings(tabFocused.boxShadow)).toEqual(spreadRings(tabRest.boxShadow));
      expect(tabFocused.borderWidth).toBe(tabRest.borderWidth);
      expect(tabFocused.borderColor).toBe(tabRest.borderColor);
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

  test("mobile: 상단 바 버튼은 터치 표적 44px 이상, 데스크톱 밀도는 그대로", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE);
    await page.goto("/ops/logs");
    const header = page.locator('[data-slot="admin-shell-header"]');
    const refresh = header
      .locator('[data-slot="admin-shell-actions"]')
      .getByRole("button", { name: "새로고침" });
    await expect(refresh).toBeVisible();
    // 상단 바의 모든 보이는 버튼(메뉴 버튼·도움말·동작)이 WCAG 2.5.5 44×44를 넘는다.
    const mobileBoxes = await header.locator("button").evaluateAll((buttons) =>
      buttons
        .filter((button) => button.checkVisibility())
        .map((button) => {
          const rect = button.getBoundingClientRect();
          return {
            name: button.getAttribute("aria-label") ?? button.textContent ?? "",
            width: rect.width,
            height: rect.height,
          };
        }),
    );
    expect(mobileBoxes.length).toBeGreaterThanOrEqual(2);
    for (const box of mobileBoxes) {
      expect(box.width, `${box.name} width`).toBeGreaterThanOrEqual(44);
      expect(box.height, `${box.name} height`).toBeGreaterThanOrEqual(44);
    }
    // 상단 바는 여전히 한 줄(48px 안팎)이다.
    expect((await header.boundingBox())?.height).toBeLessThanOrEqual(56);

    // 데스크톱은 기존 밀도(공통 Button 기본 h-8 = 32px)를 유지한다.
    await page.setViewportSize(DESKTOP);
    await expect
      .poll(async () => (await refresh.boundingBox())?.height)
      .toBe(32);
  });
});

/** 문서의 모든 CSS 애니메이션(drawer slide·overlay fade)이 끝날 때까지 기다린다. */
/** SSR HTML의 h1 텍스트 목록(React 텍스트 경계 주석·태그 제거, 기본 엔티티 복원). */
function ssrHeadings(html: string): string[] {
  return [...html.matchAll(/<h1(?=[\s>])[^>]*>([\s\S]*?)<\/h1>/g)].map((match) =>
    match[1]!
      .replace(/<!--[\s\S]*?-->/g, "")
      .replace(/<[^>]+>/g, "")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#x27;/g, "'")
      .replace(/&amp;/g, "&")
      .trim(),
  );
}

async function waitForAnimations(page: Page) {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .map((animation) => animation.finished.catch(() => undefined)),
    ),
  );
}

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

/** box-shadow 목록에서 spread(네 번째 길이)가 0보다 큰 항목만 — 포커스 ring의 흔적. */
function spreadRings(boxShadow: string): string[] {
  if (boxShadow === "none") return [];
  return boxShadow
    .split(/,(?![^(]*\))/)
    .map((shadow) => shadow.trim())
    .filter((shadow) => {
      const lengths = shadow.match(/-?\d+(\.\d+)?px/g) ?? [];
      return lengths.length >= 4 && Number.parseFloat(lengths[3] ?? "0") > 0;
    });
}
