import { expect, test, type Page } from "@playwright/test";

import {
  KMA_DATASET_KEY,
  KMA_NOWCAST_OPERATION_KEY,
  KMA_PROVIDER,
  bootstrapC7SameOriginPage,
  browserFetch,
  requireBody,
  resolveKmaProviderDatasetId,
  type OpsDatasetDetailResponse,
  type OpsDatasetsGridResponse,
} from "./_ops-c7-admin-api";
import { assertC7ReadAuthLiveEnvironment } from "./_ops-live-browser";

const FOREIGN_OPERATION_KEY = "feature_weather_kma_short_forecast_job";

function exactDetailPath(
  providerDatasetId: number,
  syncScope: string,
  operationKey: string,
): string {
  const query = new URLSearchParams({
    operation_key: operationKey,
    sync_scope: syncScope,
  });
  return `/v1/ops/datasets/${providerDatasetId}?${query.toString()}`;
}

function foreignSyncScope(): string {
  return `external_system:c7-contract-foreign-${Date.now()}`;
}

async function canonicalKmaScope(
  page: Page,
  providerDatasetId: number,
): Promise<string> {
  const grid = requireBody(
    await browserFetch<OpsDatasetsGridResponse>(page, "/v1/ops/datasets"),
    200,
  );
  const scopes = [
    ...new Set(
      grid.data.items
        .filter(
          (row) =>
            row.catalog_state === "canonical" &&
            row.provider === KMA_PROVIDER &&
            row.dataset_key === KMA_DATASET_KEY &&
            row.provider_dataset_id === providerDatasetId,
        )
        .map((row) => row.sync_scope)
        .filter((scope): scope is string => scope.length > 0),
    ),
  ].sort();
  if (scopes.length === 0 || scopes[0] === undefined) {
    throw new Error("C7 KMA exact-triple preflight scope projection이 없습니다");
  }
  return scopes[0];
}

test.describe("C7 KMA exact-triple API preflight (read-only, live)", () => {
  test.describe.configure({ mode: "serial", retries: 0 });

  test.beforeAll(({}, testInfo) => {
    assertC7ReadAuthLiveEnvironment(testInfo.config.workers);
  });

  test("다른 operation_key detail query를 서버가 거부한다", async ({ page }) => {
    await bootstrapC7SameOriginPage(page, "/ops/datasets");
    const providerDatasetId = await resolveKmaProviderDatasetId(page);
    const syncScope = await canonicalKmaScope(page, providerDatasetId);

    const canonical = requireBody(
      await browserFetch<OpsDatasetDetailResponse>(
        page,
        exactDetailPath(
          providerDatasetId,
          syncScope,
          KMA_NOWCAST_OPERATION_KEY,
        ),
      ),
      200,
    );
    expect(canonical.data.provider_dataset_id).toBe(providerDatasetId);
    expect(canonical.data.operation_key).toBe(KMA_NOWCAST_OPERATION_KEY);
    expect(canonical.data.scopes).toHaveLength(1);
    expect(canonical.data.scopes[0]?.sync_scope).toBe(syncScope);

    const foreign = await browserFetch<unknown>(
      page,
      exactDetailPath(providerDatasetId, syncScope, FOREIGN_OPERATION_KEY),
    );
    expect([404, 422]).toContain(foreign.status);

    const wrongScope = await browserFetch<unknown>(
      page,
      exactDetailPath(
        providerDatasetId,
        foreignSyncScope(),
        KMA_NOWCAST_OPERATION_KEY,
      ),
    );
    expect([404, 422]).toContain(wrongScope.status);
  });
});
