import { expect, test, type Page } from "@playwright/test";

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

type PublicApiKeyRecord = {
  public_api_key_id: string;
  key_hint: string;
  state: "active" | "revoked";
  label?: string | null;
};

type PublicApiKeyListResponse = {
  data: { items: PublicApiKeyRecord[] };
};

type PublicApiKeyCreateResponse = {
  data: {
    item: PublicApiKeyRecord;
    key: string;
  };
};

type AdminAuthEventResponse = {
  data: {
    item: {
      auth_event_id: string;
      reason?: string | null;
      request_id?: string | null;
    };
  };
};

const T = { timeout: 15_000 } as const;
const FLOW_TIMEOUT = 60_000;
const EXECUTE_SETTINGS_WRITE =
  process.env.E2E_ADMIN_WRITE === "1" || process.env.E2E_SETTINGS_WRITE === "1";

test.describe.configure({ mode: "serial" });
test.use({ screenshot: "off", trace: "off" });

async function browserFetch<TBody>(
  page: Page,
  path: string,
  options: { body?: unknown; method?: "GET" | "POST" } = {},
): Promise<BrowserFetchResult<TBody>> {
  return page.evaluate(
    async ({ body, method, path }) => {
      const response = await fetch(`/api/proxy${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        credentials: "same-origin",
        cache: "no-store",
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      const text = await response.text();
      let parsed: unknown = null;
      try {
        parsed = text.length > 0 ? JSON.parse(text) : null;
      } catch {
        parsed = null;
      }
      return { body: parsed as TBody | null, status: response.status, text };
    },
    {
      body: options.body,
      method: options.method ?? "GET",
      path,
    },
  );
}

async function expectSettingsReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Settings" }),
  ).toBeVisible(T);
  await expect(
    page.getByRole("heading", { level: 2, name: "Public API keys" }),
  ).toBeVisible(T);
  await expect(
    page.getByRole("heading", { level: 2, name: "Login audit" }),
  ).toBeVisible(T);
}

async function listPublicApiKeys(
  page: Page,
  pageSize = 200,
): Promise<PublicApiKeyRecord[]> {
  const response = await browserFetch<PublicApiKeyListResponse>(
    page,
    `/v1/admin/public-api-keys?page_size=${pageSize}`,
  );
  expect(response.status).toBe(200);
  return response.body?.data.items ?? [];
}

async function revokePublicApiKey(
  page: Page,
  publicApiKeyId: string,
): Promise<void> {
  const response = await browserFetch(
    page,
    `/v1/admin/public-api-keys/${encodeURIComponent(publicApiKeyId)}/revoke`,
    { body: {}, method: "POST" },
  );
  expect([200, 404]).toContain(response.status);
}

async function revokeActivePublicApiKeysByLabel(
  page: Page,
  label: string,
): Promise<void> {
  const items = await listPublicApiKeys(page);
  for (const item of items) {
    if (item.label === label && item.state === "active") {
      await revokePublicApiKey(page, item.public_api_key_id);
    }
  }
}

test.describe("/admin/settings live write", () => {
  test("settings page loads key and audit tables", async ({ page }) => {
    await page.goto("/admin/settings");
    await expectSettingsReady(page);
    await expect(page.getByRole("table").first()).toBeVisible(T);
    await expect(page.getByRole("table").nth(1)).toBeVisible(T);
  });

  test("UI creates a public API key, API sees it, then UI/API see revoke", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_SETTINGS_WRITE,
      "E2E_SETTINGS_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 public API key write flow를 실행",
    );
    const runId = `live-settings-${Date.now()}-${Math.random()
      .toString(36)
      .slice(2, 8)}`;
    const label = `e2e ${runId}`;
    let createdId: string | null = null;

    await page.goto("/admin/settings");
    await expectSettingsReady(page);
    await page.addStyleTag({
      content: "code { visibility: hidden !important; }",
    });

    try {
      const createResponsePromise = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname.endsWith(
            "/api/proxy/v1/admin/public-api-keys",
          ),
        { timeout: FLOW_TIMEOUT },
      );
      await page.getByPlaceholder("예: production-service").fill(label);
      await page.getByRole("button", { name: "랜덤 생성" }).click();
      const createResponse = await createResponsePromise;
      expect(createResponse.status()).toBe(200);
      const created =
        (await createResponse.json()) as PublicApiKeyCreateResponse;
      createdId = created.data.item.public_api_key_id;
      expect(created.data.item.label).toBe(label);
      expect(created.data.item.state).toBe("active");
      expect(created.data.item.key_hint.length).toBeGreaterThanOrEqual(6);

      await expect(page.getByText(label)).toBeVisible(T);
      let items = await listPublicApiKeys(page);
      expect(items.some((item) => item.public_api_key_id === createdId)).toBe(
        true,
      );

      const row = page.getByRole("row", { name: new RegExp(label) });
      const revokeResponsePromise = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname.endsWith(
            `/api/proxy/v1/admin/public-api-keys/${createdId}/revoke`,
          ),
        { timeout: FLOW_TIMEOUT },
      );
      await row.getByRole("button", { name: "폐기" }).click();
      const revokeResponse = await revokeResponsePromise;
      expect(revokeResponse.status()).toBe(200);

      items = await listPublicApiKeys(page);
      expect(
        items.find((item) => item.public_api_key_id === createdId)?.state,
      ).toBe("revoked");
      await expect(row).toContainText("revoked", T);
    } finally {
      if (createdId) {
        await revokePublicApiKey(page, createdId);
      }
      await revokeActivePublicApiKeysByLabel(page, label);
    }
  });

  test("API-created auth audit event appears in Settings UI", async ({ page }) => {
    test.skip(
      !EXECUTE_SETTINGS_WRITE,
      "E2E_SETTINGS_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 삭제 불가 audit event write flow를 실행",
    );
    const requestId = `live-settings-audit-${Date.now()}-${Math.random()
      .toString(36)
      .slice(2, 8)}`;
    const reason = `e2e-settings-audit-${requestId.slice(-8)}`;

    await page.goto("/admin/settings");
    await expectSettingsReady(page);

    const response = await browserFetch<AdminAuthEventResponse>(
      page,
      "/v1/admin/auth-events",
      {
        body: {
          attempted_username: "e2e-admin",
          event_type: "login",
          outcome: "denied",
          reason,
          request_id: requestId,
        },
        method: "POST",
      },
    );
    expect(response.status).toBe(200);
    expect(response.body?.data.item.reason).toBe(reason);

    await page.getByRole("button", { name: "새로고침" }).click();
    await expect(page.getByRole("row", { name: new RegExp(reason) })).toBeVisible(
      T,
    );
  });
});
