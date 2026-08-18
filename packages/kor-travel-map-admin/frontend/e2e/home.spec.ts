import { expect, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

type ProblemDetail = components["schemas"]["ProblemDetail"];

const BACKEND_UNAVAILABLE: ProblemDetail = {
  code: "SERVICE_UNAVAILABLE",
  detail: "mocked backend unavailable",
  request_id: "e2e-home-backend-unavailable",
  status: 503,
  title: "mocked backend unavailable",
  type: "https://kor-travel-map/errors/service-unavailable",
};

/**
 * 홈(`/`) — 운영 홈 대시보드 smoke.
 * 실 API 데이터가 비어 있거나 일시 실패해도 shell, 주요 metric, 운영 내비게이션은
 * 렌더되어야 한다.
 */
test.describe("home page (/)", () => {
  test.beforeEach(async ({ page }) => {
    // 이 smoke의 계약은 backend 실패와 무관한 shell/navigation 렌더다.
    // 세부 happy/error payload는 home-nav.spec.ts가 생성 OpenAPI 타입에
    // 바인딩해 검증하므로, 여기서는 navigation 목적지까지 모든 BFF REST와
    // ops-live WebSocket을 차단해 mocked suite가 실 backend에 닿지 않게 한다.
    await installInertOpsLiveWebSocket(page);
    await page.route("**/api/proxy/**", async (route) => {
      const request = route.request();
      const apiPath = bffApiPath(request.url());
      if (request.method() !== "GET") {
        throw new Error(
          `home smoke에서 예상하지 않은 BFF 요청: ${request.method()} ${apiPath}`,
        );
      }
      await route.fulfill({
        body: JSON.stringify(BACKEND_UNAVAILABLE),
        contentType: "application/problem+json",
        status: 503,
      });
    });
  });

  test("운영 홈 shell + 주요 운영 내비 링크 렌더", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { level: 1, name: "운영 홈" }),
    ).toBeVisible();
    const navigation = page.getByRole("navigation");
    for (const linkName of [
      "Feature 지도",
      "파이프라인",
      "데이터셋",
      "정합성 점검",
      "중복 검토",
      "POI 캐시 대상",
      "오프라인 업로드",
    ]) {
      await expect(
        navigation.getByRole("link", { name: linkName, exact: true }),
      ).toBeVisible();
    }
  });

  test("운영 metric 카드와 상태 카드가 렌더", async ({ page }) => {
    await page.goto("/");

    // 요약 KPI는 StatStrip 한 덩어리다(라벨은 heading이 아니라 dt 안의 딥링크) —
    // 값/라벨 단언은 소유 stat testid(home-client.tsx `HOME_STAT_TEST_ID`)로 scope한다.
    for (const [testId, label] of [
      ["home-stat-features", "Feature"],
      ["home-stat-pipeline", "파이프라인 작업"],
      ["home-stat-dedup", "중복 검수"],
      ["home-stat-issues", "이슈"],
    ] as const) {
      await expect(
        page.getByTestId(testId).getByRole("link", { name: label, exact: true }),
      ).toBeVisible();
    }

    for (const heading of ["서비스 상태", "중복 검수 대기"]) {
      await expect(
        page.getByRole("heading", { name: heading, exact: true }),
      ).toBeVisible();
    }
    // Backend/Dagster는 '서비스 상태' 카드 내부 패널(span label) — testid로 스코프.
    await expect(page.getByTestId("service-backend")).toBeVisible();
    await expect(page.getByTestId("service-dagster")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "최근 파이프라인 실행" }),
    ).toBeVisible();
  });

  test("홈에서 새 운영 화면으로 이동", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "파이프라인", exact: true }).click();
    await expect(page).toHaveURL(/\/ops\/pipeline$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "파이프라인" }),
    ).toBeVisible();

    await page.getByRole("link", { name: "데이터셋", exact: true }).click();
    await expect(page).toHaveURL(/\/ops\/datasets$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "데이터셋" }),
    ).toBeVisible();
  });
});
