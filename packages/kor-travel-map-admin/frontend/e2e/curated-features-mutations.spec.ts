import { expect, type Page, type Route, test } from "@playwright/test";

interface ImportRequests {
  commit: number;
  preview: number;
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status: 200,
  });
}

function importRow(
  status: "valid" | "imported" | "unmatched" | "review_required",
) {
  const unmatched = status === "unmatched";
  const reviewRequired = status === "review_required";
  return {
    row_number: unmatched ? 3 : reviewRequired ? 4 : 2,
    status,
    collection_key: "lighthouse-stamp-tour",
    theme_slug: "lighthouse-stamp-tour",
    title: "등대 스탬프투어",
    edition_key: "2026",
    place_name: unmatched ? "간절곶 등대" : reviewRequired ? "남이섬" : "국립해양박물관",
    address_hint: unmatched ? "울산 울주군" : reviewRequired ? "" : "부산 영도구",
    requested_feature_id: "",
    resolved_feature_id: unmatched || reviewRequired ? null : "feature-maritime-museum",
    source_item_key: unmatched
      ? "lighthouse-ganjeolgot"
      : reviewRequired
        ? "tourism-namiseom"
        : "museum-busan",
    candidates: unmatched
      ? []
      : reviewRequired
        ? [
            {
              feature_id: "feature-seoul-namesake",
              name: "남이섬",
              address: { road_address: "서울특별시 중구" },
              lon: 126.99,
              lat: 37.56,
            },
          ]
      : [
          {
            feature_id: "feature-maritime-museum",
            name: "국립해양박물관",
            address: { road_address: "부산 영도구 해양로301번길 45" },
            lon: 129.0785,
            lat: 35.0787,
          },
        ],
    issues: unmatched
      ? [
          {
            code: "unmatched",
            message: "기존 Feature와 일치하는 후보가 없어 미연결 항목으로 저장합니다.",
            row_number: 3,
            column: null,
          },
        ]
      : reviewRequired
        ? [
            {
              code: "name_only_match",
              message: "이름만 일치하는 후보는 자동 링크하지 않습니다.",
              row_number: 4,
              column: null,
            },
          ]
      : [],
  };
}

function importResponse(dryRun: boolean, fileIssues: unknown[] = []) {
  return {
    data: {
      dry_run: dryRun,
      rows_total: 2,
      valid_rows: 2,
      invalid_rows: 0,
      unresolved_rows: 1,
      inserted: dryRun ? 0 : 2,
      updated: 0,
      removed: 1,
      collections: 1,
      removals: [
        {
          curation_item_id: "removed-item",
          title: "이전 등대 목록",
          place_name: "폐지된 등대",
          external_item_id: "removed-lighthouse",
          feature_id: null,
        },
      ],
      items: [importRow(dryRun ? "valid" : "imported"), importRow("unmatched")],
      issues: fileIssues,
    },
    meta: {},
  };
}

function reviewRequiredImportResponse(dryRun: boolean, fileIssues: unknown[] = []) {
  const response = importResponse(dryRun, fileIssues);
  response.data.rows_total = 1;
  response.data.valid_rows = 1;
  response.data.unresolved_rows = 1;
  response.data.inserted = dryRun ? 0 : 1;
  response.data.removed = 0;
  response.data.removals = [];
  response.data.items = [importRow("review_required")];
  return response;
}

async function mockCsvImportRoutes(
  page: Page,
  fileIssues: unknown[] = [],
  responseFactory = importResponse,
): Promise<ImportRequests> {
  const requests: ImportRequests = { commit: 0, preview: 0 };

  await page.route("**/api/proxy/v1/admin/curated-themes**", (route) =>
    fulfillJson(route, { data: { items: [] }, meta: {} }),
  );
  await page.route("**/api/proxy/v1/admin/curated-sources**", (route) =>
    fulfillJson(route, { data: { items: [] }, meta: {} }),
  );
  await page.route("**/api/proxy/v1/admin/curations**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/import") && request.method() === "POST") {
      const dryRun = url.searchParams.get("dry_run") === "true";
      if (dryRun) requests.preview += 1;
      else requests.commit += 1;
      expect(request.headers()["content-type"]).toContain("multipart/form-data");
      await fulfillJson(route, responseFactory(dryRun, dryRun ? fileIssues : []));
      return;
    }
    await fulfillJson(route, { data: { items: [] }, meta: {} });
  });

  return requests;
}

test.describe("큐레이션 CSV import", () => {
  test("이름 단독 후보를 후보 다수가 아닌 수동 검토로 표시한다", async ({ page }) => {
    await mockCsvImportRoutes(page, [], reviewRequiredImportResponse);
    await page.goto("/admin/features/curated");

    await page.getByLabel("CSV 파일").setInputFiles({
      name: "name-only.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(
        "collection_key,theme_slug,title,place_name\nlighthouse-stamp-tour,lighthouse-stamp-tour,등대 스탬프투어,남이섬\n",
      ),
    });
    await page.getByRole("button", { name: "매칭 미리보기" }).click();

    const report = page.getByTestId("curation-import-report");
    await expect(report.getByText("수동 검토", { exact: true })).toBeVisible();
    await expect(report.getByText("후보 다수", { exact: true })).toHaveCount(0);
    await expect(
      report.getByText("이름만 일치하는 후보는 자동 링크하지 않습니다."),
    ).toBeVisible();
    await expect(
      report.getByText("feature-seoul-namesake", { exact: true }),
    ).toBeVisible();
    await expect(
      report.getByRole("button", { name: "남이섬 후보 Feature ID 복사" }),
    ).toBeVisible();
  });

  test("dry-run에서 미연결 행을 보여주고 형식 오류가 없으면 전체 반영한다", async ({
    page,
  }) => {
    const requests = await mockCsvImportRoutes(page);
    await page.goto("/admin/features/curated");

    await page.getByLabel("CSV 파일").setInputFiles({
      name: "lighthouse-stamp-tour.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(
        "collection_key,theme_slug,title,place_name\nlighthouse-stamp-tour,lighthouse-stamp-tour,등대 스탬프투어,간절곶 등대\n",
      ),
    });
    await page.getByRole("button", { name: "매칭 미리보기" }).click();

    const report = page.getByTestId("curation-import-report");
    await expect(report.getByText("미리보기")).toBeVisible();
    await expect(report.getByText("전체 2")).toBeVisible();
    await expect(report.getByText("오류 0")).toBeVisible();
    await expect(report.getByText("미연결 1")).toBeVisible();
    await expect(report.getByText("제거 예정 1")).toBeVisible();
    await expect(report.getByText(/폐지된 등대/)).toBeVisible();
    await expect(report.getByText(/간절곶 등대/)).toBeVisible();
    await expect(report.getByText("미일치")).toBeVisible();
    await expect(
      report.getByText(
        "기존 Feature와 일치하는 후보가 없어 미연결 항목으로 저장합니다.",
      ),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "전체 반영" })).toBeEnabled();
    expect(requests.preview).toBe(1);

    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toBe(
        "2개 행을 DB에 반영할까요?\nCSV에 없는 기존 항목 1개가 제거됩니다.",
      );
      await dialog.accept();
    });
    await page.getByRole("button", { name: "전체 반영" }).click();

    await expect(page.getByText("CSV 반영 완료: 신규 2개, 갱신 0개")).toBeVisible();
    await expect(report.getByText("반영 결과")).toBeVisible();
    await expect(report.getByText("반영됨")).toBeVisible();
    await expect(report.getByText("미일치")).toBeVisible();
    expect(requests.commit).toBe(1);
  });

  test("파일 전체 오류가 있으면 전체 반영을 막는다", async ({ page }) => {
    const requests = await mockCsvImportRoutes(page, [
      {
        code: "too_many_rows",
        message: "CSV 데이터 행은 2000개 이하여야 합니다.",
        row_number: null,
        column: null,
      },
    ]);
    await page.goto("/admin/features/curated");

    await page.getByLabel("CSV 파일").setInputFiles({
      name: "too-many.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("collection_key\ntoo-many\n"),
    });
    await page.getByRole("button", { name: "매칭 미리보기" }).click();

    await expect(page.getByText("CSV 데이터 행은 2000개 이하여야 합니다.")).toBeVisible();
    await expect(page.getByRole("button", { name: "전체 반영" })).toBeDisabled();
    expect(requests.preview).toBe(1);
    expect(requests.commit).toBe(0);
  });
});
