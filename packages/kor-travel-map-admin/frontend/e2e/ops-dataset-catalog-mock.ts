import type { Page, Route } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";

type OpsDatasetsGridResponse =
  components["schemas"]["OpsDatasetsGridResponse"];

const EMPTY_CATALOG: OpsDatasetsGridResponse = {
  data: {
    items: [],
    latest_execution_coverage: "db_recorded_canonical_operations",
    schedule_source_errors: [],
    schedule_source_status: "ok",
  },
  meta: {
    duration_ms: 1,
    page: null,
    request_id: "e2e-ops-dataset-catalog",
  },
};

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status: 200,
  });
}

/** legacy provider API를 대체한 canonical 입력 후보 조회를 mock 경계 안에 둔다. */
export async function mockOpsDatasetCatalog(page: Page) {
  await page.route("**/api/proxy/v1/ops/datasets**", async (route) => {
    const request = route.request();
    const path = bffApiPath(request.url());
    if (request.method() === "GET" && path === "/v1/ops/datasets") {
      await fulfillJson(route, EMPTY_CATALOG);
      return;
    }
    throw new Error(`Unhandled dataset catalog route: ${request.method()} ${path}`);
  });
}
