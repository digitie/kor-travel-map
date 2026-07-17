import { expect, test, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

type PipelineExecutionsListResponse =
  components["schemas"]["PipelineExecutionsListResponse"];
type PipelineOverviewResponse =
  components["schemas"]["PipelineOverviewResponse"];

const TIMEOUT = 30_000;

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

function waitForGet(page: Page, path: string): Promise<Response> {
  return page.waitForResponse(
    (response) =>
      response.request().method() === "GET" && apiPath(response) === path,
    { timeout: TIMEOUT },
  );
}

function shortId(value: string, size = 12): string {
  return value.length > size ? `${value.slice(0, size)}...` : value;
}

test.describe("운영 홈 live canonical round-trip", () => {
  test("pipeline overview와 root 목록을 실제 응답으로 렌더한다", async ({
    page,
  }) => {
    const overviewResponse = waitForGet(page, "/v1/ops/pipeline/overview");
    const executionsResponse = waitForGet(page, "/v1/ops/pipeline/executions");

    await page.goto("/");

    const overview = await overviewResponse;
    const executions = await executionsResponse;
    expect(overview.ok()).toBeTruthy();
    expect(executions.ok()).toBeTruthy();
    const overviewBody = (await overview.json()) as PipelineOverviewResponse;
    const executionsBody =
      (await executions.json()) as PipelineExecutionsListResponse;

    await expect(
      page.getByRole("heading", { level: 1, name: "운영 홈" }),
    ).toBeVisible({ timeout: TIMEOUT });
    await expect(
      page.getByRole("heading", { name: "최근 파이프라인 실행" }),
    ).toBeVisible();
    await expect(page.getByTestId("service-dagster")).toContainText(
      `${overviewBody.data.dagster.recent_runs?.length ?? 0} recent runs`,
    );

    const first = executionsBody.data.items[0];
    if (first) {
      const row = page.getByRole("row", {
        name: new RegExp(first.kind),
      });
      await expect(row).toContainText(shortId(first.id));
      await expect(row.getByRole("link")).toHaveAttribute(
        "href",
        `/ops/pipeline?execution=${first.kind}:${encodeURIComponent(first.id)}`,
      );
    } else {
      await expect(page.getByText("파이프라인 실행이 없습니다.")).toBeVisible();
    }
  });

  test("존치 운영 화면만 홈 내비게이션에 노출한다", async ({ page }) => {
    await page.goto("/");
    const navigation = page.getByRole("navigation");

    await expect(
      navigation.getByRole("link", { name: "파이프라인", exact: true }),
    ).toHaveAttribute("href", "/ops/pipeline");
    await expect(
      navigation.getByRole("link", { name: "데이터셋", exact: true }),
    ).toHaveAttribute("href", "/ops/datasets");
    for (const removed of [
      "Provider 상태",
      "적재 작업",
      "갱신 요청",
      "작업 자동화",
      "ETL 미리보기",
    ]) {
      await expect(
        navigation.getByRole("link", { name: removed, exact: true }),
      ).toHaveCount(0);
    }
  });
});
