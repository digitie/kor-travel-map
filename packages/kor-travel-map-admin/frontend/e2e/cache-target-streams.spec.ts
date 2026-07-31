import { expect, type Page, type Route, test } from "@playwright/test";

import { bffApiPath } from "./bff-api-path";

const STREAMS_PATH = "/v1/ops/cache-target-streams";
const DEAD_LIST_PATH = "/v1/ops/cache-target-event-dead-letters";
const EVENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const DETAIL_PATH = `${DEAD_LIST_PATH}/${EVENT_ID}`;
const REPLAY_PATH = `/v1/admin/cache-target-event-dead-letters/${EVENT_ID}/replays`;
const RECONCILE_PATH = "/v1/admin/cache-target-reconciliations";
const ENTITY_TAG = `"${EVENT_ID}:3"`;
const MERKLE_ROOT =
  "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

type RawStream = {
  external_system: string;
  restore_epoch: number;
  control_version: number;
  consumer_enabled: boolean;
  state: string;
  pending_count: number;
  leased_count: number;
  retry_count: number;
  dead_count: number;
  delivered_count: number;
  blocked_event_id: string | null;
  last_snapshot: {
    snapshot_id: string;
    count: number;
    merkle_root: string;
    high_watermark_cursor: string;
    created_at: string;
  } | null;
  updated_at: string;
};

type RawDeadLetter = {
  event_id: string;
  event_type: string;
  external_system: string;
  relay_order: number;
  target_key: string;
  restore_epoch: number;
  source_generation: number;
  target_sequence: number;
  attempt_count: number;
  error_class: string | null;
  error_code: string | null;
  payload_fingerprint: string;
  delivery_version: number;
  entity_tag: string;
  occurred_at: string;
  updated_at: string;
};

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: status >= 400 ? "application/problem+json" : "application/json",
    status,
  });
}

function streamFixture(): RawStream {
  return {
    blocked_event_id: EVENT_ID,
    consumer_enabled: false,
    control_version: 14,
    dead_count: 1,
    delivered_count: 91,
    external_system: "pinvi",
    last_snapshot: {
      count: 128,
      created_at: "2026-07-31T01:20:00.000Z",
      high_watermark_cursor: "relay:91",
      merkle_root: MERKLE_ROOT,
      snapshot_id: "snap-20260731-pinvi",
    },
    leased_count: 1,
    pending_count: 2,
    restore_epoch: 7,
    retry_count: 3,
    state: "blocked",
    updated_at: "2026-07-31T01:22:00.000Z",
  };
}

function deadLetterFixture(): RawDeadLetter {
  return {
    attempt_count: 5,
    delivery_version: 3,
    entity_tag: ENTITY_TAG,
    error_class: "PermanentDeliveryError",
    error_code: "PINVI_CONFLICT",
    event_id: EVENT_ID,
    event_type: "cache_target.links_reconciled",
    external_system: "pinvi",
    occurred_at: "2026-07-31T01:21:00.000Z",
    payload_fingerprint:
      "abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd",
    relay_order: 92,
    restore_epoch: 7,
    source_generation: 42,
    target_key: "poi::seoul-station",
    target_sequence: 4,
    updated_at: "2026-07-31T01:22:00.000Z",
  };
}

function accepted(operationId: string) {
  return {
    data: {
      operation_id: operationId,
      status: "accepted",
      status_url: `/v1/ops/cache-target-operations/${operationId}`,
    },
    meta: { duration_ms: 1, request_id: `e2e-${operationId}` },
  };
}

async function installCacheStreamRoutes(
  page: Page,
  options: { replayFails?: boolean } = {},
) {
  const captured = {
    reconcileBody: null as Record<string, unknown> | null,
    reconcileHeaders: null as Record<string, string> | null,
    replayBody: null as Record<string, unknown> | null,
    replayHeaders: null as Record<string, string> | null,
  };

  await page.route("**/v1/service/cache-target**", async (route) => {
    throw new Error(`service route 직접 호출 금지: ${route.request().url()}`);
  });

  await page.route("**/api/proxy/**", async (route) => {
    const request = route.request();
    const apiPath = bffApiPath(request.url());
    if (apiPath.startsWith("/v1/service/cache-target")) {
      throw new Error(`service route 직접 호출 금지: ${apiPath}`);
    }
    if (request.method() === "GET" && apiPath === STREAMS_PATH) {
      await fulfillJson(route, {
        data: { items: [streamFixture()] },
        meta: { duration_ms: 1, request_id: "e2e-streams" },
      });
      return;
    }
    if (request.method() === "GET" && apiPath === DEAD_LIST_PATH) {
      await fulfillJson(route, {
        data: { items: [deadLetterFixture()] },
        meta: { duration_ms: 1, request_id: "e2e-dead-list" },
      });
      return;
    }
    if (request.method() === "GET" && apiPath === DETAIL_PATH) {
      await fulfillJson(route, {
        data: deadLetterFixture(),
        meta: { duration_ms: 1, request_id: "e2e-dead-detail" },
      });
      return;
    }
    if (request.method() === "POST" && apiPath === REPLAY_PATH) {
      captured.replayBody = request.postDataJSON() as Record<string, unknown>;
      captured.replayHeaders = request.headers();
      if (options.replayFails) {
        await fulfillJson(
          route,
          {
            code: "CACHE_TARGET_DEAD_LETTER_STALE",
            detail: "delivery ETag stale",
            request_id: "e2e-replay-stale",
            status: 412,
            title: "Precondition Failed",
            type: "about:blank",
          },
          412,
        );
        return;
      }
      await route.fulfill({
        body: JSON.stringify(accepted("replay-op-1")),
        contentType: "application/json",
        headers: {
          Location: "/v1/ops/cache-target-operations/replay-op-1",
          "Retry-After": "3",
        },
        status: 202,
      });
      return;
    }
    if (request.method() === "POST" && apiPath === RECONCILE_PATH) {
      captured.reconcileBody = request.postDataJSON() as Record<string, unknown>;
      captured.reconcileHeaders = request.headers();
      await route.fulfill({
        body: JSON.stringify(accepted("reconcile-op-1")),
        contentType: "application/json",
        headers: {
          Location: "/v1/ops/cache-target-operations/reconcile-op-1",
          "Retry-After": "5",
        },
        status: 202,
      });
      return;
    }
    throw new Error(`Unhandled cache target stream route: ${request.method()} ${apiPath}`);
  });

  return captured;
}

test.describe("/ops/cache-target-streams", () => {
  test("status/dead read와 replay/reconcile command가 BFF operator route를 사용한다", async ({
    page,
  }) => {
    const captured = await installCacheStreamRoutes(page);

    await page.goto("/ops/cache-target-streams");

    await expect(
      page.getByRole("heading", { level: 1, name: "캐시 전파 스트림" }),
    ).toBeVisible();
    await expect(page.getByRole("row", { name: /pinvi/ })).toBeVisible();
    await expect(page.getByText("2 pending / 1 lease / 3 retry")).toBeVisible();
    await expect(page.getByText(MERKLE_ROOT)).toBeVisible();
    await expect(
      page.getByRole("row", { name: /cache_target.links_reconciled/ }),
    ).toBeVisible();
    await expect(page.getByText(ENTITY_TAG)).toBeVisible();

    const replayButton = page.getByRole("button", { name: "replay 요청" });
    await expect(replayButton).toBeDisabled();
    await page.getByLabel("사유").first().fill("PinVi conflict fixed");
    await expect(replayButton).toBeEnabled();
    await replayButton.click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "replay 요청" })
      .click();

    expect(captured.replayBody).toEqual({ reason: "PinVi conflict fixed" });
    expect(captured.replayHeaders?.["if-match"]).toBe(ENTITY_TAG);
    expect(captured.replayHeaders?.["idempotency-key"]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    await expect(page.getByRole("status")).toContainText("replay-op-1");

    const reconcileButton = page.getByRole("button", {
      name: "reconciliation 요청",
    });
    await expect(reconcileButton).toBeDisabled();
    await page.getByLabel("사유").nth(1).fill("checksum mismatch investigation");
    await expect(reconcileButton).toBeEnabled();
    await reconcileButton.click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "reconciliation 요청" })
      .click();

    expect(captured.reconcileBody).toEqual({
      external_system: "pinvi",
      reason: "checksum mismatch investigation",
    });
    expect(captured.reconcileHeaders?.["idempotency-key"]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    await expect(page.getByRole("status")).toContainText("reconcile-op-1");
  });

  test("replay RFC7807 problem을 destructive alert로 표시한다", async ({ page }) => {
    await installCacheStreamRoutes(page, { replayFails: true });

    await page.goto("/ops/cache-target-streams");
    await page.getByLabel("사유").first().fill("stale replay");
    await page.getByRole("button", { name: "replay 요청" }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "replay 요청" })
      .click();

    const alert = page
      .getByRole("alert")
      .filter({ hasText: "복구 명령 실패" });
    await expect(alert).toContainText("복구 명령 실패");
    await expect(alert).toContainText("CACHE_TARGET_DEAD_LETTER_STALE");
    await expect(alert).toContainText("delivery ETag stale");
  });
});
