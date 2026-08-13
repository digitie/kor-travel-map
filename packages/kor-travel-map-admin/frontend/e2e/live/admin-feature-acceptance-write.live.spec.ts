import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import path from "node:path";

import type { components } from "../../src/api/types";

type AdminFeatureDetailResponse =
  components["schemas"]["AdminFeatureDetailResponse"];
type AdminFeatureFieldOverrideResponse =
  components["schemas"]["AdminFeatureFieldOverrideResponse"];
type AdminFeatureRevisionResponse =
  components["schemas"]["AdminFeatureRevisionResponse"];
type AdminFeatureStateResponse =
  components["schemas"]["AdminFeatureStateResponse"];
type AdminFeatureStateTransitionsResponse =
  components["schemas"]["AdminFeatureStateTransitionsResponse"];
type AdminFeaturesListResponse =
  components["schemas"]["AdminFeaturesListResponse"];

type FetchResult<T> = {
  body: T | null;
  entityTag: string | null;
  status: number;
};

type BrowserFetchOptions = {
  body?: unknown;
  headers?: Record<string, string>;
  method?: "GET" | "POST" | "PATCH" | "DELETE";
};

const FLOW_TIMEOUT = 5 * 60 * 1000;
const UI_TIMEOUT = 30_000;
const RUN_ID = process.env.E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID ?? "";
const EXECUTE = process.env.E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE === "1";
const RECOVERY_ONLY =
  process.env.E2E_ADMIN_FEATURE_ACCEPTANCE_RECOVERY_ONLY === "1";
const ISOLATED_EVIDENCE = process.env.E2E_ISOLATED_LIVE_EVIDENCE === "1";
const ARTIFACT_ROOT = process.env.PLAYWRIGHT_ARTIFACT_ROOT;
const RUN_ID_PATTERN = /^[a-z0-9][a-z0-9-]{15,79}$/;
const LON = 127.5;
const LAT = 36.5;
const FIXTURE_NAME = `E2E TVN36 state fixture ${RUN_ID}`;
const REASON = `tvn36-live-${RUN_ID}`;

let lastBrowserFetchStatus: number | null = null;

if (EXECUTE && !RUN_ID_PATTERN.test(RUN_ID)) {
  throw new Error(
    "E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID 형식이 올바르지 않습니다 (value redacted)",
  );
}

function adminFeaturePath(featureId: string): string {
  return `/v1/admin/features/${encodeURIComponent(featureId)}`;
}

function revisionPath(featureId: string): string {
  return `${adminFeaturePath(featureId)}/revision`;
}

function publicFeaturePath(featureId: string): string {
  return `/v1/features/${encodeURIComponent(featureId)}`;
}

function idempotencyKey(
  method: NonNullable<BrowserFetchOptions["method"]>,
  path: string,
  body: unknown,
): string {
  const digest = createHash("sha256")
    .update(JSON.stringify({ body, method, path }), "utf8")
    .digest("hex");
  const variant = (8 + (Number.parseInt(digest[16], 16) & 0x03)).toString(16);
  return [
    digest.slice(0, 8),
    digest.slice(8, 12),
    `4${digest.slice(13, 16)}`,
    `${variant}${digest.slice(17, 20)}`,
    digest.slice(20, 32),
  ].join("-");
}

async function browserFetch<T>(
  page: Page,
  path: string,
  options: BrowserFetchOptions = {},
): Promise<FetchResult<T>> {
  const method = options.method ?? "GET";
  const result = await page.evaluate(
    async ({ body, headers, key, method, path }) => {
      const response = await fetch(`/api/proxy${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...headers,
          ...(key === null ? {} : { "Idempotency-Key": key }),
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        credentials: "same-origin",
        cache: "no-store",
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      const text = await response.text();
      let parsed: unknown = null;
      try {
        parsed = text.length === 0 ? null : JSON.parse(text);
      } catch {
        parsed = null;
      }
      return {
        body: parsed,
        entityTag: response.headers.get("ETag"),
        status: response.status,
      };
    },
    {
      body: options.body,
      headers: options.headers,
      key:
        method === "GET" ? null : idempotencyKey(method, path, options.body),
      method,
      path,
    },
  );
  lastBrowserFetchStatus = result.status;
  return result as FetchResult<T>;
}

function requireBody<T>(result: FetchResult<T>, label: string): T {
  if (result.status !== 200 || result.body === null) {
    throw new Error(`${label} 실패: HTTP ${result.status} (response redacted)`);
  }
  return result.body;
}

function requireEntityTag<T>(result: FetchResult<T>, label: string): string {
  requireBody(result, label);
  if (result.entityTag === null || !/^"[1-9][0-9]*"$/.test(result.entityTag)) {
    throw new Error(`${label} raw strong ETag가 없습니다`);
  }
  return result.entityTag;
}

function writeSafeFailure(stage: string): void {
  if (!ISOLATED_EVIDENCE || ARTIFACT_ROOT === undefined) return;
  try {
    writeFileSync(
      path.join(ARTIFACT_ROOT, "admin-feature-acceptance-safe-debug.json"),
      `${JSON.stringify({ last_browser_fetch_status: lastBrowserFetchStatus, stage })}\n`,
      { encoding: "utf8", mode: 0o600 },
    );
  } catch {
    // 진단 artifact 실패가 원래 E2E 실패를 가리면 안 된다.
  }
}

async function listOwnedFeatures(page: Page): Promise<string[]> {
  const query = new URLSearchParams({ page_size: "100", q: RUN_ID });
  const response = requireBody(
    await browserFetch<AdminFeaturesListResponse>(
      page,
      `/v1/admin/features?${query.toString()}`,
    ),
    "owned feature list",
  );
  return response.data.items
    .filter((item) => item.name === FIXTURE_NAME)
    .map((item) => item.feature_id);
}

async function retireFeature(page: Page, featureId: string): Promise<void> {
  const detail = await browserFetch<AdminFeatureDetailResponse>(
    page,
    adminFeaturePath(featureId),
  );
  if (detail.status === 404) return;
  const current = requireBody(detail, "cleanup detail").data.feature;
  if (current.lifecycle_state === "retired") return;
  const tag = requireEntityTag(
    await browserFetch<AdminFeatureRevisionResponse>(page, revisionPath(featureId)),
    "cleanup revision",
  );
  const retired = requireBody(
    await browserFetch<AdminFeatureStateResponse>(
      page,
      `${adminFeaturePath(featureId)}/state`,
      {
        body: { action: "retire", reason_code: `${REASON}:cleanup` },
        headers: { "If-Match": tag },
        method: "PATCH",
      },
    ),
    "cleanup retire",
  );
  expect(retired.data.lifecycle_state).toBe("retired");
  expect(retired.data.publication_state).toBe("suppressed");
}

async function cleanupOwnedFeatures(page: Page): Promise<void> {
  for (const featureId of await listOwnedFeatures(page)) {
    await retireFeature(page, featureId);
    await expect
      .poll(
        async () =>
          (await browserFetch(page, publicFeaturePath(featureId))).status,
        { timeout: UI_TIMEOUT },
      )
      .toBe(404);
  }
}

test.describe.configure({ mode: "serial" });

test("@admin-feature-live-acceptance TVN36 direct state cutover", async ({
  page,
}) => {
  test.skip(
    !EXECUTE,
    "E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1일 때만 isolated write lane을 실행",
  );
  test.setTimeout(FLOW_TIMEOUT);
  lastBrowserFetchStatus = null;

  await page.goto("/");
  if (RECOVERY_ONLY) {
    await cleanupOwnedFeatures(page);
    return;
  }

  try {
    await cleanupOwnedFeatures(page);
    const created = requireBody(
      await browserFetch<AdminFeatureFieldOverrideResponse>(
        page,
        "/v1/admin/features",
        {
          body: {
            category: "01070300",
            coord: { lat: LAT, lon: LON },
            kind: "place",
            lifecycle_state: "active",
            marker_color: "P-02",
            marker_icon: "marker",
            name: FIXTURE_NAME,
            publication_state: "published",
            quality_state: "valid",
            reason: `${REASON}:create`,
          },
          method: "POST",
        },
      ),
      "create typed Feature",
    );
    const featureId = created.data.feature_id;

    const detail = requireBody(
      await browserFetch<AdminFeatureDetailResponse>(page, adminFeaturePath(featureId)),
      "created detail",
    );
    expect(detail.data.feature).toMatchObject({
      feature_id: featureId,
      lifecycle_state: "active",
      name: FIXTURE_NAME,
      publication_state: "published",
      quality_state: "valid",
    });
    expect((await browserFetch(page, publicFeaturePath(featureId))).status).toBe(200);

    await page.goto(`/features/${encodeURIComponent(featureId)}`);
    await expect(page.getByTestId("feature-detail-view")).toBeVisible({
      timeout: UI_TIMEOUT,
    });
    await expect(page.getByText(FIXTURE_NAME, { exact: true })).toBeVisible();

    const patchTag = requireEntityTag(
      await browserFetch<AdminFeatureRevisionResponse>(page, revisionPath(featureId)),
      "state patch revision",
    );
    const suppressed = requireBody(
      await browserFetch<AdminFeatureStateResponse>(
        page,
        `${adminFeaturePath(featureId)}/state`,
        {
          body: {
            action: "patch",
            publication_state: "suppressed",
            reason_code: `${REASON}:suppress`,
          },
          headers: { "If-Match": patchTag },
          method: "PATCH",
        },
      ),
      "state suppress",
    );
    expect(suppressed.data).toMatchObject({
      lifecycle_state: "active",
      publication_state: "suppressed",
      quality_state: "valid",
    });
    expect((await browserFetch(page, publicFeaturePath(featureId))).status).toBe(404);

    const retireTag = requireEntityTag(
      await browserFetch<AdminFeatureRevisionResponse>(page, revisionPath(featureId)),
      "state retire revision",
    );
    const retired = requireBody(
      await browserFetch<AdminFeatureStateResponse>(
        page,
        `${adminFeaturePath(featureId)}/state`,
        {
          body: { action: "retire", reason_code: `${REASON}:retire` },
          headers: { "If-Match": retireTag },
          method: "PATCH",
        },
      ),
      "state retire",
    );
    expect(retired.data).toMatchObject({
      lifecycle_state: "retired",
      publication_state: "suppressed",
      quality_state: "valid",
    });

    const timeline = requireBody(
      await browserFetch<AdminFeatureStateTransitionsResponse>(
        page,
        `${adminFeaturePath(featureId)}/state/transitions?page_size=20`,
      ),
      "state transition timeline",
    );
    expect(timeline.data.items).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ to_publication_state: "suppressed" }),
        expect.objectContaining({ to_lifecycle_state: "retired" }),
      ]),
    );
  } catch (error) {
    writeSafeFailure("tvn36-direct-state-cutover");
    throw error;
  } finally {
    await cleanupOwnedFeatures(page);
  }
});
