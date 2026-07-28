import { expect, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

type ProblemDetail = components["schemas"]["ProblemDetail"];

const BACKEND_UNAVAILABLE: ProblemDetail = {
  code: "SERVICE_UNAVAILABLE",
  detail: "mocked backend unavailable",
  request_id: "e2e-pr617-shell-backend-unavailable",
  status: 503,
  title: "mocked backend unavailable",
  type: "https://kor-travel-map/errors/service-unavailable",
};

/**
 * codex PR #617(세션 UI 재반영) + #613 리뷰 fix(#618) 후속의 mocked shell e2e.
 *
 * API payload depth는 각 전용 spec이 담당한다. 여기서는 모든 BFF GET을 명시적 503으로
 * 격리해 backend 장애 중에도 변경된 shell/control이 렌더되는지만 검증한다.
 * 쓰기 확인 다이얼로그는 live 전용 spec으로 분리한다.
 */
test.describe("PR #617/#613 후속 UI", () => {
  test.beforeEach(async ({ page }) => {
    await installInertOpsLiveWebSocket(page);
    await page.route("**/api/proxy/**", async (route) => {
      const request = route.request();
      const apiPath = bffApiPath(request.url());
      if (request.method() !== "GET") {
        throw new Error(
          `PR #617/#613 shell에서 예상하지 않은 BFF 요청: ${request.method()} ${apiPath}`,
        );
      }
      await route.fulfill({
        body: JSON.stringify(BACKEND_UNAVAILABLE),
        contentType: "application/problem+json",
        status: 503,
      });
    });
  });

  test("운영 로그 — system/API 두 canonical stream만 노출", async ({ page }) => {
    await page.goto("/ops/logs");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("tab", { name: "System logs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "API call logs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Job events" })).toHaveCount(0);
  });

  test("중복 검토 — 다중 선택 combobox 필터(#617)", async ({ page }) => {
    await page.goto("/admin/features/dedup-reviews");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("combobox").first()).toBeVisible();
  });

  test("보강 검토 — 다중 선택 combobox 필터(#617)", async ({ page }) => {
    await page.goto("/admin/features/enrichment-reviews");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("combobox").first()).toBeVisible();
  });

  test("신규 Feature 작성 — 시군구 코드 자동검색 필드(#617)", async ({ page }) => {
    await page.goto("/admin/features/new");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(
      page.getByLabel("create sigungu code", { exact: true }),
    ).toBeVisible();
  });

  test("파이프라인 — 실행 타임라인 렌더", async ({ page }) => {
    await page.goto("/ops/pipeline");
    await expect(page.getByRole("heading", { name: "실행 타임라인" })).toBeVisible();
  });

  test("파이프라인 — 스케줄 컨트롤 렌더", async ({ page }) => {
    await page.goto("/ops/pipeline?tab=schedules");
    await expect(page.getByRole("heading", { name: "스케줄" })).toBeVisible();
  });

});
