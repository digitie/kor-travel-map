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

function importRow(status: "valid" | "imported" | "unmatched") {
  const unmatched = status === "unmatched";
  return {
    row_number: unmatched ? 3 : 2,
    status,
    collection_key: "lighthouse-stamp-tour",
    theme_slug: "lighthouse-stamp-tour",
    title: "등대 스탬프투어",
    edition_key: "2026",
    place_name: unmatched ? "간절곶 등대" : "국립해양박물관",
    address_hint: unmatched ? "울산 울주군" : "부산 영도구",
    requested_feature_id: "",
    resolved_feature_id: unmatched ? null : "feature-maritime-museum",
    source_item_key: unmatched ? "lighthouse-ganjeolgot" : "museum-busan",
    candidates: unmatched
      ? []
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
      : [],
  };
}

function importResponse(dryRun: boolean) {
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
      issues: [],
    },
    meta: {},
  };
}

async function mockCsvImportRoutes(page: Page): Promise<ImportRequests> {
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
      await fulfillJson(route, importResponse(dryRun));
      return;
    }
    await fulfillJson(route, { data: { items: [] }, meta: {} });
  });

  return requests;
}

test.describe("큐레이션 CSV import", () => {
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
});
