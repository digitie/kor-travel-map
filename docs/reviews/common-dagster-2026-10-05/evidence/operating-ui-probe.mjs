import { chromium, firefox, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const results = [];
const output = '/evidence';
await fs.mkdir(output, { recursive: true });
for (const [browserName, browserType] of [['chromium', chromium], ['firefox', firefox]]) {
  const browser = await browserType.launch({ headless: true });
  let browserFailure = null;
  try {
  for (const app of ['map', 'pinvi']) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: false });
    const page = await context.newPage();
    page.setDefaultTimeout(60000);
    const base = process.env[`${app.toUpperCase()}_UI_URL`];
    const loginPath = app === 'map' ? '/login' : '/admin/login';
    const summaryPath = app === 'map' ? '/dagster-summary' : '/admin/etl/summary';
    let auth = null;
    let cleaned = false;
    let primaryFailure = null;
    try {
    let snapshot = null;
    page.on('response', async response => {
      if (response.url().includes(summaryPath) && response.ok()) {
        try { snapshot = await response.json(); } catch {}
      }
    });
    await page.goto(base + loginPath);
    await expect(page.locator('[data-slot=login-password]')).toBeVisible();
    await page.locator('[data-slot=login-username]').fill(process.env[`${app.toUpperCase()}_USERNAME`]);
    await page.locator('[data-slot=login-password]').fill(process.env[`${app.toUpperCase()}_PASSWORD`]);
    const authResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url().includes('/auth/login'));
    await page.locator('[data-slot=login-submit]').click();
    auth = await authResponse;
    if (auth.status() !== 200) throw new Error(`${app} actual login HTTP ${auth.status()}`);
    await expect(page).not.toHaveURL(new RegExp(`${loginPath}$`));
    const cookieName = app === 'map' ? 'ktm_admin_session' : 'pinvi_access';
    const authHeaders = await auth.allHeaders();
    if (!(authHeaders['set-cookie'] ?? '').includes(`${cookieName}=`)) throw new Error(`${app} login Set-Cookie missing`);
    const cookies = await context.cookies();
    if (!cookies.some(cookie => cookie.name === cookieName && cookie.value.length > 0 && cookie.httpOnly && cookie.secure)) {
      throw new Error(`${app} secure HttpOnly session cookie missing`);
    }
    await page.goto(base + (app === 'map' ? '/ops/pipeline' : '/admin/etl'));
    const panel = page.getByTestId(app === 'map' ? 'map-common-dagster' : 'admin-common-dagster');
    await expect(panel).toBeVisible();
    await expect.poll(() => snapshot, { timeout: 90000 }).not.toBeNull();
    const envelope = snapshot.data;
    const data = app === 'map' ? envelope : envelope.pinvi;
    if (data.status !== 'ok') throw new Error(`${app} Dagster summary status ${data.status}`);
    if (data.repositories.length !== 1) throw new Error(`${app} repository count mismatch`);
    const expectedLocation = app === 'map' ? 'kortravelmap.dagster.definitions' : 'pinvi.etl.definitions';
    if (data.repositories[0].name !== '__repository__' || data.repositories[0].location_name !== expectedLocation) {
      throw new Error(`${app} repository identity mismatch`);
    }
    const connectionError = panel.locator('[data-slot=dagster-operations-error]');
    await expect(connectionError).toHaveCount(0);
    const active = page.locator('a[aria-current=page]');
    if (await active.count() !== 1) throw new Error(`${app} active menu count mismatch`);
    let detail = 'no-live-runs';
    const select = panel.getByRole('button', { name: /^실행 상세:/ }).first();
    if (await select.count()) {
      const label = await select.getAttribute('aria-label');
      await select.click();
      const selected = panel.getByRole('region', { name: '선택한 실행 상세' });
      await expect(selected).toBeVisible();
      const runId = label.slice(label.lastIndexOf(', ') + 2);
      await expect(selected).toContainText(runId);
      if (app === 'map') await expect(page.getByTestId('map-selected-run-detail')).toContainText(runId);
      await panel.getByRole('button', { name: label, exact: true }).click();
      detail = 'selected-identity-visible';
    }
    const stableRunLabel = await select.count() ? await select.getAttribute('aria-label') : null;
    const jobCount = data.job_count;
    if (!(jobCount >= (app === 'map' ? 30 : 8))) throw new Error(`${app} expected jobs not loaded`);
    await panel.screenshot({ path: `${output}/${app}-${browserName}-desktop.png` });
    const summaryMatcher = url => url.pathname.includes(summaryPath);
    await page.route(summaryMatcher, route => route.abort('failed'));
    const summaryCards = panel.locator('[data-slot=dagster-operations-summary]');
    const lastChecked = panel.getByRole('heading', { name: /^최근 실행 · 마지막 확인/ });
    const savedSummary = await summaryCards.innerText();
    const savedChecked = await lastChecked.innerText();
    await panel.getByRole('button', { name: '새로고침', exact: true }).click();
    await expect(connectionError).toBeVisible({ timeout: 90000 });
    await expect(panel).toBeVisible();
    await expect(summaryCards).toHaveText(savedSummary, { useInnerText: true });
    await expect(lastChecked).toHaveText(savedChecked);
    if (stableRunLabel) await expect(panel.getByRole('button', { name: stableRunLabel, exact: true })).toBeVisible();
    await page.unroute(summaryMatcher);
    const recoveredResponse = page.waitForResponse(response => response.url().includes(summaryPath) && response.ok());
    await panel.getByRole('button', { name: '새로고침', exact: true }).click();
    await recoveredResponse;
    await expect(connectionError).toHaveCount(0, { timeout: 90000 });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(panel).toBeVisible();
    const geometry = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
    if (geometry.document > geometry.width + 1) throw new Error(`${app} mobile overflow`);
    const region = panel.getByRole('region', { name: '최근 Dagster 실행 표' });
    let keyboard = 'no-live-runs';
    if (await region.count()) {
      await region.focus();
      await expect(region).toBeFocused();
      const before = await region.evaluate(element => element.scrollLeft);
      await page.keyboard.press('ArrowRight');
      await expect.poll(() => region.evaluate(element => element.scrollLeft)).toBeGreaterThan(before);
      keyboard = 'focus-arrow-scroll';
    }
    await panel.screenshot({ path: `${output}/${app}-${browserName}-mobile.png` });
    await page.setViewportSize({ width: 1280, height: 900 });
    let logout;
    if (app === 'map') {
      const logoutResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url().includes('/auth/logout'));
      await page.getByRole('button', { name: '로그아웃', exact: true }).click();
      logout = await logoutResponse;
    } else {
      // PinVi Admin 셸에는 기존부터 로그아웃 버튼이 없다. 실제 auth endpoint로
      // 생성한 테스트 세션만 정리하며 UI 버튼 검증으로 집계하지 않는다.
      logout = await context.request.post(auth.url().replace(/\/login$/, '/logout'), {
        headers: { Origin: new URL(base).origin, Referer: base + '/admin/etl' },
      });
    }
    if (logout.status() !== (app === 'map' ? 200 : 204)) throw new Error(`${app} actual logout HTTP ${logout.status()}`);
    await expect.poll(async () => (await context.cookies()).some(cookie => cookie.name === cookieName && cookie.value.length > 0)).toBe(false);
    results.push({ app, browser: browserName, actual_login_status: auth.status(), session_cookie_present: true,
      login_set_cookie_present: true, secure_http_only_session: true, actual_logout_status: logout.status(), session_cookie_cleared: true,
      logout_scope: app === 'map' ? 'actual UI logout button' : 'actual API test-session cleanup; admin UI has no logout button',
      owned_repository: true, job_count: jobCount, recent_run_count: data.recent_runs.length,
      run_detail: detail, browser_request_abort_last_good_recovery: 'PASS', mobile_geometry: geometry,
      table_keyboard: keyboard });
    cleaned = true;
    } catch (error) {
      primaryFailure = error;
      throw error;
    } finally {
      try {
        if (!cleaned && auth?.status() === 200) {
          const cleanup = await context.request.post(auth.url().replace(/\/login$/, '/logout'), {
            headers: { Origin: new URL(base).origin, Referer: base + (app === 'map' ? '/ops/pipeline' : '/admin/etl') },
          });
          if (cleanup.status() !== (app === 'map' ? 200 : 204)) throw new Error(`${app} cleanup HTTP ${cleanup.status()}`);
        }
      } catch (cleanupError) {
        console.error(JSON.stringify({ app, browser: browserName, cleanup_failed: true, primary_assertion_failed: Boolean(primaryFailure) }));
        if (!primaryFailure) throw cleanupError;
      } finally {
        try { await context.close(); }
        catch (closeError) {
          console.error(JSON.stringify({ app, browser: browserName, context_close_failed: true, primary_assertion_failed: Boolean(primaryFailure) }));
          if (!primaryFailure) throw closeError;
        }
      }
    }
  }
  } catch (error) {
    browserFailure = error;
    throw error;
  } finally {
    try { await browser.close(); }
    catch (closeError) {
      console.error(JSON.stringify({ browser: browserName, browser_close_failed: true, primary_assertion_failed: Boolean(browserFailure) }));
      if (!browserFailure) throw closeError;
    }
  }
}
await fs.writeFile(`${output}/operating-ui-result.json`, JSON.stringify({
  map_product: process.env.MAP_PRODUCT, pinvi_product: process.env.PINVI_PRODUCT,
  scope: 'actual operating UI/API/GraphQL, browser summary request abort injection only; shared service or worker not stopped',
  cases: results,
}, null, 2) + '\n');
console.log(JSON.stringify({ status: 'PASS', cases: results }));
